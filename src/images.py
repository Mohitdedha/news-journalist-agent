"""
Image discovery, processing, and upload.
Uses Unsplash API. Tracks used photo IDs in history.json to avoid repeats across runs.
"""
import io
import re
import time
import random
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


_TEXT_KEYWORDS = {"bible","scripture","text","book","manuscript","letter","document",
                  "newspaper","magazine","page","word","writing","quote","sign","poster",
                  "whiteboard","chalkboard","code","screen","monitor","data","chart",
                  "graph","infographic","map","diagram","logo","icon","flag"}


def search_unsplash(query, per_page=20, randomize_page=False):
    if not UNSPLASH_ACCESS_KEY:
        print("[WARN] UNSPLASH_ACCESS_KEY not set")
        return []
    try:
        # Use random page offset for generic fallback queries to get variety
        page = random.randint(1, 4) if randomize_page else 1
        resp = requests.get(
            UNSPLASH_SEARCH,
            headers={"Authorization": f"Client-ID {UNSPLASH_ACCESS_KEY}"},
            params={
                "query": query,
                "per_page": per_page,
                "orientation": "landscape",
                "page": page,
                "content_filter": "high",  # filter unsafe/irrelevant content
            },
            timeout=10
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
        # Shuffle results so we don't always pick the top result
        random.shuffle(results)
        photos = []
        for r in results:
            # Skip photos whose tags suggest text/documents — they look terrible as news images
            photo_tags = {t.get("title", "").lower() for t in r.get("tags", [])}
            alt_desc = (r.get("alt_description") or "").lower()
            desc = (r.get("description") or "").lower()
            combined = photo_tags | set(alt_desc.split()) | set(desc.split())
            if combined & _TEXT_KEYWORDS:
                continue
            w = r.get("width", 0)
            h = r.get("height", 0)
            # Prefer full/regular over small; skip tiny images
            if w < 800 or h < 400:
                continue
            url = r.get("urls", {}).get("full", "") or r.get("urls", {}).get("regular", "")
            photos.append({
                "id": r.get("id", ""),
                "url": url,
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


def _brand_image(img):
    """
    Add indiabbcnews.com branding to a PIL Image (already 1200x630).
    - Subtle dark gradient at bottom 25%
    - Red accent bar (bottom 28px) with 'indiabbcnews.com' text
    Returns branded PIL Image.
    """
    try:
        from PIL import ImageDraw, ImageFont

        W, H = img.size  # 1200 x 630

        # ── Gradient overlay (bottom 25%) ────────────────────────────────────
        grad_h = int(H * 0.25)
        grad_top = H - grad_h
        overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        draw_ov = ImageDraw.Draw(overlay)
        for y in range(grad_top, H):
            alpha = int(140 * (y - grad_top) / grad_h)
            draw_ov.line([(0, y), (W, y)], fill=(0, 0, 0, alpha))
        img = img.convert("RGBA")
        img = Image.alpha_composite(img, overlay).convert("RGB")

        draw = ImageDraw.Draw(img)

        # ── Red accent bar at very bottom ────────────────────────────────────
        bar_h = 30
        draw.rectangle([(0, H - bar_h), (W, H)], fill=(204, 0, 0))

        # ── Font: try system fonts, fall back to default ─────────────────────
        font_paths = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",  # Ubuntu/Actions
            "C:/Windows/Fonts/arialbd.ttf",                           # Windows
            "C:/Windows/Fonts/arial.ttf",
        ]
        font_url = None
        for fp in font_paths:
            try:
                font_url = ImageFont.truetype(fp, 18)
                break
            except Exception:
                pass
        if font_url is None:
            font_url = ImageFont.load_default()

        # ── Website URL centred on red bar ───────────────────────────────────
        text = "indiabbcnews.com"
        # Get text width for centering
        try:
            bbox = draw.textbbox((0, 0), text, font=font_url)
            tw = bbox[2] - bbox[0]
        except Exception:
            tw = len(text) * 10
        tx = (W - tw) // 2
        ty = H - bar_h + (bar_h - 20) // 2
        draw.text((tx, ty), text, fill="white", font=font_url)

        # ── Small logo text top-left corner ──────────────────────────────────
        try:
            font_logo = ImageFont.truetype(font_paths[0] if font_url != ImageFont.load_default() else "", 14)
        except Exception:
            font_logo = font_url
        draw.rectangle([(0, 0), (160, 26)], fill=(0, 0, 0, 140))
        draw.text((8, 5), "INDIA BBC NEWS", fill=(255, 50, 50), font=font_logo)

        return img
    except Exception as e:
        print(f"[WARN] Branding failed: {e}")
        return img


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

        # ── Custom editing: contrast + sharpness + slight cool tone ──────────
        from PIL import ImageEnhance, ImageFilter
        img = ImageEnhance.Contrast(img).enhance(1.15)      # +15% contrast
        img = ImageEnhance.Sharpness(img).enhance(1.4)      # sharpen
        img = ImageEnhance.Color(img).enhance(1.1)          # slightly more vivid
        # Subtle cool/blue tint (news feel) via channel tweak
        r, g, b = img.split()
        b = b.point(lambda px: min(255, int(px * 1.06)))    # boost blue slightly
        r = r.point(lambda px: int(px * 0.97))              # reduce red slightly
        img = Image.merge("RGB", (r, g, b))

        # Add indiabbcnews.com branding to every image
        img = _brand_image(img)

        buf = io.BytesIO()
        quality = 85
        while quality >= 55:
            buf.seek(0)
            buf.truncate()
            img.save(buf, format="JPEG", quality=quality, optimize=True)
            if len(buf.getvalue()) <= MAX_FILE_KB * 1024:
                break
            quality -= 8

        result = buf.getvalue()
        print(f"[INFO] Image processed+branded: {TARGET_WIDTH}x{TARGET_HEIGHT}, {len(result)//1024}KB")
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
    generic_fallbacks = set(_GENERIC_FALLBACKS)

    for query in fallback_queries:
        # Randomize page for generic fallbacks to avoid always getting the same top results
        is_generic = query in generic_fallbacks
        photos = search_unsplash(query, per_page=20, randomize_page=is_generic)
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
            caption = ""
            print(f"[INFO] Image found (query='{query}', id={photo_id}): {headline[:50]}")
            return processed, alt_text, caption

    # Unsplash exhausted — generate image with Pollinations.ai (free, no API key)
    print("[INFO] Unsplash exhausted — trying AI-generated image (Pollinations.ai)...")
    ai_image = _generate_ai_image(image_query or headline)
    if ai_image:
        processed = process_image(ai_image)
        if processed:
            print(f"[INFO] AI image generated for: {headline[:50]}")
            return processed, headline[:100], ""

    print("[WARN] No suitable image found.")
    return None, None, None


def _generate_ai_image(prompt):
    """
    Generate image using Pollinations.ai — completely free, no API key needed.
    Returns raw image bytes or None.
    """
    try:
        import urllib.parse
        # Clean prompt: remove special chars, keep it descriptive
        clean = re.sub(r'[^\w\s]', ' ', prompt)
        clean = re.sub(r'\s+', ' ', clean).strip()[:120]
        # Add style guidance for news photography look
        full_prompt = f"{clean}, professional news photography, high quality, photorealistic"
        encoded = urllib.parse.quote(full_prompt)
        url = f"https://image.pollinations.ai/prompt/{encoded}?width=1200&height=630&nologo=true&seed={random.randint(1,9999)}"
        resp = requests.get(url, timeout=60)
        if resp.status_code == 200 and resp.headers.get("content-type", "").startswith("image"):
            return resp.content
    except Exception as e:
        print(f"[WARN] AI image generation failed: {e}")
    return None
