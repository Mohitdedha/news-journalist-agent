"""
Image discovery, processing, and upload.
Uses Unsplash API. Tracks used photo IDs in history.json to avoid repeats across runs.
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

# In-memory set for this run (also backed by history.json across runs)
_used_photo_ids = set()


def init_used_photos(history):
    """Load previously used photo IDs from history into memory."""
    global _used_photo_ids
    _used_photo_ids = set(history.get("used_photo_ids", []))
    print(f"[INFO] Loaded {len(_used_photo_ids)} used photo IDs from history")


def save_used_photos(history):
    """Persist current used photo IDs back to history dict (caller saves to disk)."""
    # Keep only last 500 to avoid bloat
    all_ids = list(_used_photo_ids)
    history["used_photo_ids"] = all_ids[-500:]


def search_unsplash(query, per_page=10):
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
        photos = []
        for r in results:
            photos.append({
                "id": r.get("id", ""),
                "url": r.get("urls", {}).get("regular", ""),
            })
        return photos
    except Exception as e:
        print(f"[WARN] Unsplash search error: {e}")
        return []


def download_image(url, timeout=15):
    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        return resp.content
    except Exception as e:
        print(f"[WARN] Image download error: {e}")
        return None


def process_image(image_bytes):
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
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
        print(f"[INFO] Image processed: 1200x630, {len(result)//1024}KB")
        return result
    except Exception as e:
        print(f"[WARN] Image processing error: {e}")
        return None


def upload_to_wordpress(image_bytes, filename, alt_text, caption=""):
    """Upload image. Returns (media_id, media_url) or (None, None)."""
    try:
        auth = (WP_USER, WP_APP_PASSWORD)
        headers = {
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": "image/jpeg",
        }
        resp = requests.post(
            f"{WP_URL}/wp-json/wp/v2/media",
            auth=auth, headers=headers, data=image_bytes, timeout=30
        )
        resp.raise_for_status()
        media = resp.json()
        media_id = media["id"]
        # source_url is the public URL of the uploaded image
        media_url = media.get("source_url", "") or media.get("guid", {}).get("rendered", "")
        requests.post(
            f"{WP_URL}/wp-json/wp/v2/media/{media_id}",
            auth=auth, json={"alt_text": alt_text, "caption": caption}, timeout=15
        )
        return media_id, media_url
    except Exception as e:
        print(f"[WARN] WordPress media upload error: {e}")
        return None, None


_GENERIC_FALLBACKS = ["news", "world news", "politics", "government", "city"]


def _build_fallback_queries(image_query, headline):
    """Build progressively simpler search queries, ending with generic fallbacks."""
    queries = [image_query]

    stop = {"the","a","an","of","in","on","at","to","for","is","are","was","were",
            "and","or","but","with","from","by","as","its","it","this","that","s",
            "pm","new","over","after","than","will","have","been","amid","say","says"}

    words = [w.strip("'\",.!?:()") for w in headline.split()
             if len(w.strip("'\",.!?:()")) > 3
             and w.strip("'\",.!?:()").lower() not in stop]

    if len(words) >= 2:
        queries.append(" ".join(words[:2]))  # first 2 meaningful words
    if words:
        queries.append(words[0])             # single most important word

    # Generic fallbacks so we ALWAYS find something
    queries.extend(_GENERIC_FALLBACKS)

    seen = set()
    unique = []
    for q in queries:
        if q and q not in seen:
            seen.add(q)
            unique.append(q)
    return unique


def find_and_process_image(image_query, headline, context, history=None):
    """
    Search → download → process → upload path.
    Tracks used photo IDs in memory + history.json to prevent repeats across runs.
    Returns (bytes, alt_text, caption) or (None, None, None).
    """
    fallback_queries = _build_fallback_queries(image_query, headline)

    for query in fallback_queries:
        photos = search_unsplash(query, per_page=20)
        if not photos:
            print(f"[INFO] No results for query: '{query}'")
            continue

        for photo in photos:
            photo_id = photo.get("id", "")
            photo_url = photo.get("url", "")
            if not photo_url or not photo_id:
                continue

            if photo_id in _used_photo_ids:
                print(f"[INFO] Skipping used photo id={photo_id}")
                continue

            image_bytes = download_image(photo_url)
            if not image_bytes:
                continue

            processed = process_image(image_bytes)
            if not processed:
                continue

            # Mark as used globally
            _used_photo_ids.add(photo_id)

            alt_text = headline[:100]
            caption = f"Representational image — {headline[:70]}"
            print(f"[INFO] Image found (query='{query}', id={photo_id}): {headline[:50]}")
            return processed, alt_text, caption

    print("[WARN] No suitable image found.")
    return None, None, None
