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

# Set before process_image() call so make_thumbnail() can read them
_current_headline = ""
_current_category = "global"


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
            raw_url = r.get("urls", {}).get("regular", "") or r.get("urls", {}).get("full", "")
            # Unsplash requires utm params for API usage compliance (free, copyright-free)
            url = raw_url + ("&" if "?" in raw_url else "?") + "auto=format&fit=crop&w=1200&h=630&q=85&utm_source=indiabbcnews&utm_medium=referral" if raw_url else ""
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


_CATEGORY_COLORS = {
    "india":       (220, 38,  38),   # red
    "global":      (37,  99,  235),  # blue
    "technology":  (5,   150, 105),  # green
    "economy":     (217, 119, 6),    # amber
    "business":    (217, 119, 6),    # amber
    "sports":      (124, 58,  237),  # purple
    "cricket":     (124, 58,  237),  # purple
    "science":     (6,   182, 212),  # cyan
    "lifestyle":   (236, 72,  153),  # pink
    "entertainment":(236, 72,  153), # pink
    "education":   (16,  185, 129),  # teal
    "europe-uk":   (37,  99,  235),  # blue
    "auto":        (234, 88,  12),   # orange
}
_DEFAULT_CAT_COLOR = (204, 0, 0)


def _load_font(size):
    """Try to load a bold font at the given size."""
    from PIL import ImageFont
    paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/ubuntu/Ubuntu-B.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]
    for p in paths:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            pass
    return ImageFont.load_default()


def _wrap_text(text, font, draw, max_width):
    """Word-wrap text to fit max_width pixels. Returns list of lines."""
    words = text.split()
    lines, current = [], ""
    for word in words:
        test = (current + " " + word).strip()
        try:
            w = draw.textbbox((0, 0), test, font=font)[2]
        except Exception:
            w = len(test) * (font.size if hasattr(font, 'size') else 10)
        if w <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines[:3]  # max 3 lines


def make_thumbnail(img, headline="", category="global"):
    """
    Convert a plain PIL Image into a branded news thumbnail (1200x630).
    Layout:
      - Full-bleed background image (slightly darkened)
      - Heavy dark gradient over bottom 45%
      - Category badge (top-left, colored)
      - INDIA BBC NEWS logo (top-right)
      - Bold white headline text (bottom area, 2-3 lines)
      - Red bottom bar with indiabbcnews.com
    """
    try:
        from PIL import ImageDraw, ImageEnhance, ImageFilter

        W, H = img.size   # 1200 x 630

        # ── Enhance image: contrast + saturation + slight cool tone ─────────
        img = ImageEnhance.Contrast(img).enhance(1.25)
        img = ImageEnhance.Color(img).enhance(1.15)      # richer colours
        img = ImageEnhance.Brightness(img).enhance(0.88)  # slight darkening

        # ── Subtle gradient overlay: bottom 30% only (no heavy cover) ───────
        grad_h = int(H * 0.30)
        grad_top = H - grad_h
        overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        drv = ImageDraw.Draw(overlay)
        for y in range(grad_top, H):
            alpha = int(140 * ((y - grad_top) / grad_h) ** 1.4)
            drv.line([(0, y), (W, y)], fill=(0, 0, 0, min(alpha, 140)))
        img = img.convert("RGBA")
        img = Image.alpha_composite(img, overlay).convert("RGB")

        draw = ImageDraw.Draw(img)

        # ── Fonts ─────────────────────────────────────────────────────────────
        f_url = _load_font(17)  # bottom bar URL

        # ── Thin red line + black bottom bar with indiabbcnews.com ──────────
        bar_h = 34
        draw.rectangle([(0, H - bar_h - 3), (W, H - bar_h)], fill=(204, 0, 0))
        draw.rectangle([(0, H - bar_h), (W, H)], fill=(15, 15, 15))
        url_text = "Website: indiabbcnews.com"
        try:
            ub = draw.textbbox((0, 0), url_text, font=f_url)
            uw = ub[2] - ub[0]
        except Exception:
            uw = len(url_text) * 10
        draw.text(((W - uw) // 2, H - bar_h + 8), url_text,
                   fill=(210, 210, 210), font=f_url)

        return img

    except Exception as e:
        print(f"[WARN] Thumbnail creation failed: {e}")
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

        # ── Sharpen before thumbnail ──────────────────────────────────────────
        from PIL import ImageEnhance
        img = ImageEnhance.Sharpness(img).enhance(1.3)

        # make_thumbnail() handles all branding + headline overlay
        # headline/category injected via find_and_process_image
        img = make_thumbnail(img, headline=_current_headline, category=_current_category)

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


_CATEGORY_FALLBACKS = {
    "auto":        ["car road highway", "motorcycle bike", "automobile showroom"],
    "sports":      ["sports stadium crowd", "athletes training"],
    "cricket":     ["cricket match stadium India", "cricket bat ball"],
    "technology":  ["smartphone laptop technology", "coding computer"],
    "india":       ["India cityscape", "New Delhi India"],
    "business":    ["business office meeting", "corporate building"],
    "economy":     ["stock market trading", "financial charts"],
    "science":     ["science laboratory research", "space technology"],
    "education":   ["school classroom India", "students studying"],
    "lifestyle":   ["healthy lifestyle wellness", "modern home living"],
    "entertainment":["concert music stage", "entertainment show"],
}
_GENERIC_FALLBACKS = ["news", "world news", "city", "business meeting", "newspaper"]


def _build_fallback_queries(image_query, headline, category="global"):
    """Build progressively simpler search queries, ending with generic fallbacks."""
    queries = [image_query]

    stop = {"the","a","an","of","in","on","at","to","for","is","are","was","were",
            "and","or","but","with","from","by","as","its","it","this","that","s",
            "pm","new","over","after","than","will","have","been","amid","say","says"}

    words = [w.strip("'\",.!?:()") for w in headline.split()
             if len(w.strip("'\",.!?:()")) > 3
             and w.strip("'\",.!?:()").lower() not in stop]

    if len(words) >= 2:
        queries.append(" ".join(words[:2]))
    if words:
        queries.append(words[0])

    # Category-specific fallbacks before generic ones
    cat_fallbacks = _CATEGORY_FALLBACKS.get(category, [])
    queries.extend(cat_fallbacks)
    queries.extend(_GENERIC_FALLBACKS)

    seen = set()
    unique = []
    for q in queries:
        if q and q not in seen:
            seen.add(q)
            unique.append(q)
    return unique


def find_and_process_image(image_query, headline, context, history=None, category="global"):
    """
    Search → download → process → upload path.
    Tracks used photo IDs in memory + history.json to prevent repeats across runs.
    Returns (bytes, alt_text, caption) or (None, None, None).
    """
    global _current_headline, _current_category
    _current_headline = headline
    _current_category = category

    fallback_queries = _build_fallback_queries(image_query, headline, category=category)
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
