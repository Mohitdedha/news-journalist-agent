"""
Batch image fixer — finds all published posts with featured_media=0 and adds images.
Run via: python src/fix_images.py
"""
import sys
import os
import re
import time

sys.path.insert(0, os.path.dirname(__file__))

from config import WP_URL, WP_USER, WP_APP_PASSWORD, UNSPLASH_ACCESS_KEY
from images import search_unsplash, download_image, process_image, upload_to_wordpress, _used_photo_ids


def get_posts_without_image(per_page=50):
    import requests
    posts = []
    page = 1
    while True:
        resp = requests.get(
            f"{WP_URL}/wp-json/wp/v2/posts",
            params={
                "per_page": per_page,
                "page": page,
                "status": "publish",
                "_fields": "id,title,featured_media,link"
            },
            timeout=15
        )
        if resp.status_code == 400:
            break
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        for p in batch:
            if p.get("featured_media", 0) == 0:
                posts.append({
                    "id": p["id"],
                    "title": p.get("title", {}).get("rendered", ""),
                    "link": p.get("link", "")
                })
        if len(batch) < per_page:
            break
        page += 1
    return posts


def set_featured_image(post_id, media_id):
    import requests
    resp = requests.post(
        f"{WP_URL}/wp-json/wp/v2/posts/{post_id}",
        auth=(WP_USER, WP_APP_PASSWORD),
        json={"featured_media": media_id},
        timeout=15
    )
    resp.raise_for_status()
    return resp.json()


def build_queries(title):
    stop = {"the","a","an","of","in","on","at","to","for","is","are","was","were",
            "and","or","but","with","from","by","as","its","it","this","that","s",
            "pm","new","over","after","than","will","have","been","amid","say","says",
            "forces","marks","faces","leaves","loses","reveal","reveals","takes",
            "scores","shake","shakes","scorches","sparks","turns","cuts","capture",
            "captures","announces","unveils","dies"}
    words = [w.strip("'\",.!?:()&#;") for w in re.split(r'[\s\-]+', title)
             if len(w.strip("'\",.!?:()&#;")) > 3
             and w.strip("'\",.!?:()&#;").lower() not in stop]
    queries = []
    if len(words) >= 2:
        queries.append(" ".join(words[:2]))
    if words:
        queries.append(words[0])
    # Generic fallbacks that always return results
    queries.extend(["world news", "news", "politics", "city street"])
    return queries


def fix_post_image(post):
    post_id = post["id"]
    title = post["title"]
    print(f"\n[FIX] Post {post_id}: {title[:60]}")

    queries = build_queries(title)
    print(f"[FIX] Trying queries: {queries}")

    for query in queries:
        photos = search_unsplash(query, per_page=20)
        for photo in photos:
            photo_id = photo.get("id", "")
            photo_url = photo.get("url", "")
            if not photo_url or not photo_id:
                continue
            if photo_id in _used_photo_ids:
                continue

            image_bytes = download_image(photo_url)
            if not image_bytes:
                continue

            processed = process_image(image_bytes)
            if not processed:
                continue

            _used_photo_ids.add(photo_id)

            slug = re.sub(r'[^a-z0-9\-]', '', title.lower()[:40].replace(" ", "-"))
            filename = f"{slug}-fix.jpg"
            alt_text = title[:100]
            caption = ""

            media_id, _ = upload_to_wordpress(processed, filename, alt_text, caption)
            if not media_id:
                continue

            set_featured_image(post_id, media_id)
            print(f"[OK] Image added to post {post_id}: media_id={media_id} (query='{query}')")
            return True

    print(f"[WARN] Could not find image for post {post_id}: {title[:50]}")
    return False


def main():
    print("[START] Batch image fixer")
    posts = get_posts_without_image()
    print(f"[INFO] Found {len(posts)} posts without featured image")

    if not posts:
        print("[INFO] All posts have images. Nothing to do.")
        return

    fixed = 0
    for post in posts:
        success = fix_post_image(post)
        if success:
            fixed += 1
        time.sleep(3)  # small delay between posts

    print(f"\n[DONE] Fixed {fixed}/{len(posts)} posts")


if __name__ == "__main__":
    main()
