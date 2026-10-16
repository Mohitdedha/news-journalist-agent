"""
Image discovery, processing, and upload.
Uses Unsplash API for photos; skips AI vision check (using text-only Groq).
"""
import io
import re
import time
import requests
from PIL import Image
from config import UNSPLASH_ACCESS_KEY, WP_URL, WP_USER, WP_APP_PASSWORD

UNSPLASH_SEARCH = "https://api.unsplash.com/search/photos"
TARGET_WIDTH = 1200
TARGET_HEIGHT = 630
MAX_FILE_KB = 200


def search_unsplash(query, per_page=8):
    """Search Unsplash for relevant landscape photos."""
    if not UNSPLASH_ACCESS_KEY:
        print("[WARN] UNSPLASH_ACCESS_KEY not set")
        return []
    try:
        resp = requests.get(
            UNSPLASH_SEARCH,
            headers={"Authorization": f"Client-ID {UNSPLASH_ACCESS_KEY}"},
            params={"query": query, "per_page": per_page, "orientation": "landscape"},
            timeout=10
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
        # Normalize to consistent structure
        photos = []
        for r in results:
            photos.append({
                "url": r.get("urls", {}).get("regular", ""),
                "photographer": r.get("user", {}).get("name", ""),
                "photographer_url": r.get("user", {}).get("links", {}).get("html", ""),
            })
        return photos
    except Exception as e:
        print(f"[WARN] Unsplash search error: {e}")
        return []


def download_image(url, timeout=15):
    """Download image bytes from URL."""
    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        return resp.content
    except Exception as e:
        print(f"[WARN] Image download error: {e}")
        return None


def verify_image_relevance(image_bytes, article_headline, article_context):
    """
    Accepts all Unsplash images (Unsplash search already ensures relevance).
    Returns (is_relevant: bool, description: str).
    """
    return True, f"Unsplash photo for: {article_headline[:80]}"


def process_image(image_bytes, alt_text):
    """Resize, crop to 1200x630, compress to web format. Returns processed bytes."""
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        print(f"[INFO] Original image size: {img.width}x{img.height}")

        # Smart crop to 1200x630
        src_ratio = img.width / img.height
        target_ratio = TARGET_WIDTH / TARGET_HEIGHT

        if src_ratio > target_ratio:
            new_h = img.height
            new_w = int(new_h * target_ratio)
            left = (img.width - new_w) // 2
            img = img.crop((left, 0, left + new_w, new_h))
        else:
            new_w = img.width
            new_h = int(new_w / target_ratio)
            top = (img.height - new_h) // 2
            img = img.crop((0, top, new_w, top + new_h))

        img = img.resize((TARGET_WIDTH, TARGET_HEIGHT), Image.LANCZOS)

        # Compress to JPEG
        buf = io.BytesIO()
        quality = 82
        while quality >= 50:
            buf.seek(0)
            buf.truncate()
            img.save(buf, format="JPEG", quality=quality, optimize=True)
            if len(buf.getvalue()) <= MAX_FILE_KB * 1024:
                break
            quality -= 8

        result = buf.getvalue()
        print(f"[INFO] Processed image: 1200x630, {len(result)//1024}KB")
        return result
    except Exception as e:
        print(f"[WARN] Image processing error: {e}")
        return None


def upload_to_wordpress(image_bytes, filename, alt_text, caption=""):
    """Upload image to WordPress media library. Returns media ID or None."""
    try:
        auth = (WP_USER, WP_APP_PASSWORD)
        headers = {
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": "image/jpeg",
        }
        resp = requests.post(
            f"{WP_URL}/wp-json/wp/v2/media",
            auth=auth,
            headers=headers,
            data=image_bytes,
            timeout=30
        )
        resp.raise_for_status()
        media = resp.json()
        media_id = media["id"]

        # Set alt text
        requests.post(
            f"{WP_URL}/wp-json/wp/v2/media/{media_id}",
            auth=auth,
            json={"alt_text": alt_text, "caption": caption},
            timeout=15
        )
        return media_id
    except Exception as e:
        print(f"[WARN] WordPress media upload error: {e}")
        return None


# Track used photo URLs within a run to avoid same image on multiple posts
_used_photo_urls = set()


def find_and_process_image(image_query, headline, context):
    """
    End-to-end: search → download → verify → process → return (bytes, alt_text, caption).
    Skips photos already used in this run to prevent duplicates across posts.
    """
    photos = search_unsplash(image_query, per_page=10)

    for photo in photos:
        photo_url = photo.get("url", "")
        if not photo_url:
            continue

        # Skip photos already used in this run
        if photo_url in _used_photo_urls:
            print(f"[INFO] Skipping already-used photo: {photo_url[:60]}")
            continue

        image_bytes = download_image(photo_url)
        if not image_bytes:
            continue

        is_relevant, description = verify_image_relevance(image_bytes, headline, context)
        if not is_relevant:
            print(f"[INFO] Image rejected: {description[:80]}")
            continue

        processed = process_image(image_bytes, description)
        if not processed:
            continue

        _used_photo_urls.add(photo_url)

        # Short, clean caption — no Unsplash attribution in public text
        alt_text = headline[:100]
        caption = f"Representational image — {headline[:70]}"

        print(f"[INFO] Image accepted for: {headline[:60]}")
        return processed, alt_text, caption

    print("[WARN] No suitable image found for this article.")
    return None, None, None
