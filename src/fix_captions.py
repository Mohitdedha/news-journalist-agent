"""
Batch caption fixer — finds all WordPress media with 'Representational image'
captions and clears them.
Run via: python src/fix_captions.py
"""
import sys
import os
import re
import time
import requests

sys.path.insert(0, os.path.dirname(__file__))
from config import WP_URL, WP_USER, WP_APP_PASSWORD

BAD_PREFIX = "Representational image"


def get_media_with_bad_captions(per_page=50):
    media_list = []
    page = 1
    while True:
        resp = requests.get(
            f"{WP_URL}/wp-json/wp/v2/media",
            params={
                "per_page": per_page,
                "page": page,
                "_fields": "id,caption,title"
            },
            auth=(WP_USER, WP_APP_PASSWORD),
            timeout=20
        )
        if resp.status_code == 400:
            break
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        for item in batch:
            caption_raw = item.get("caption", {}).get("raw", "") or ""
            caption_rendered = item.get("caption", {}).get("rendered", "") or ""
            caption_text = re.sub(r'<[^>]+>', '', caption_rendered).strip() or caption_raw.strip()
            if BAD_PREFIX in caption_text:
                media_list.append({
                    "id": item["id"],
                    "caption": caption_text[:80],
                    "title": item.get("title", {}).get("rendered", "")[:60]
                })
                print(f"  [FOUND] Media {item['id']}: {caption_text[:60]}")
        if len(batch) < per_page:
            break
        page += 1
        time.sleep(0.5)
    return media_list


def clear_caption(media_id):
    resp = requests.post(
        f"{WP_URL}/wp-json/wp/v2/media/{media_id}",
        auth=(WP_USER, WP_APP_PASSWORD),
        json={"caption": ""},
        timeout=15
    )
    resp.raise_for_status()
    return True


def main():
    print("[START] Caption fixer — removing 'Representational image' captions")
    media_list = get_media_with_bad_captions()
    print(f"\n[INFO] Found {len(media_list)} media items with bad captions")

    if not media_list:
        print("[INFO] No bad captions found. Nothing to do.")
        return

    fixed = 0
    for item in media_list:
        try:
            clear_caption(item["id"])
            print(f"[OK] Cleared caption on media {item['id']}: {item['title']}")
            fixed += 1
        except Exception as e:
            print(f"[ERROR] Media {item['id']}: {e}")
        time.sleep(0.3)

    print(f"\n[DONE] Fixed {fixed}/{len(media_list)} media captions")


if __name__ == "__main__":
    main()
