"""
Duplicate image fixer — finds published posts that share the same featured_media_id
and assigns each a unique new image from Unsplash.

Run via: python src/fix_duplicate_images.py
"""
import sys
import os
import re
import time
from collections import defaultdict

sys.path.insert(0, os.path.dirname(__file__))

import requests
from config import WP_URL, WP_USER, WP_APP_PASSWORD, UNSPLASH_ACCESS_KEY
from images import search_unsplash, download_image, process_image, upload_to_wordpress, _used_photo_ids


def get_all_posts_with_media(per_page=50):
    """Fetch all published posts with their featured_media id."""
    posts = []
    page = 1
    while True:
        resp = requests.get(
            f"{WP_URL}/wp-json/wp/v2/posts",
            params={
                "per_page": per_page,
                "page": page,
                "status": "publish",
                "_fields": "id,title,featured_media"
            },
            timeout=20
        )
        if resp.status_code == 400:
            break
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        for p in batch:
            media_id = p.get("featured_media", 0)
            if media_id and media_id != 0:
                posts.append({
                    "id": p["id"],
                    "title": p.get("title", {}).get("rendered", ""),
                    "media_id": media_id
                })
        if len(batch) < per_page:
            break
        page += 1
    return posts


def set_featured_image(post_id, media_id):
    resp = requests.post(
        f"{WP_URL}/wp-json/wp/v2/posts/{post_id}",
        auth=(WP_USER, WP_APP_PASSWORD),
        json={"featured_media": media_id},
        timeout=15
    )
    resp.raise_for_status()


def build_queries(title):
    stop = {"the","a","an","of","in","on","at","to","for","is","are","was","were",
            "and","or","but","with","from","by","as","its","it","this","that","s",
            "pm","new","over","after","than","will","have","been","amid","say","says"}
    words = [w.strip("'\",.!?:()&#;") for w in re.split(r'[\s\-]+', title)
             if len(w.strip("'\",.!?:()&#;")) > 3
             and w.strip("'\",.!?:()&#;").lower() not in stop]
    queries = []
    if len(words) >= 2:
        queries.append(" ".join(words[:2]))
    if words:
        queries.append(words[0])
    queries.extend(["world news", "news", "politics", "city"])
    return queries


def assign_new_image(post):
    post_id = post["id"]
    title = post["title"]
    print(f"\n[FIX] Post {post_id}: {title[:60]}")

    queries = build_queries(title)
    for query in queries:
        photos = search_unsplash(query, per_page=20, randomize_page=(query in {"world news","news","politics","city"}))
        for photo in photos:
            photo_id = photo.get("id", "")
            photo_url = photo.get("url", "")
            if not photo_url or not photo_id or photo_id in _used_photo_ids:
                continue
            image_bytes = download_image(photo_url)
            if not image_bytes:
                continue
            processed = process_image(image_bytes)
            if not processed:
                continue
            _used_photo_ids.add(photo_id)
            slug = re.sub(r'[^a-z0-9\-]', '', title.lower()[:40].replace(" ", "-"))
            media_id, _ = upload_to_wordpress(processed, f"{slug}-uniq.jpg", title[:100], "")
            if not media_id:
                continue
            set_featured_image(post_id, media_id)
            print(f"[OK] New image set for post {post_id}: media_id={media_id} (query='{query}')")
            return True

    print(f"[WARN] Could not find unique image for post {post_id}")
    return False


def main():
    print("[START] Duplicate image fixer")
    all_posts = get_all_posts_with_media()
    print(f"[INFO] Total posts with images: {len(all_posts)}")

    # Group posts by media_id
    media_groups = defaultdict(list)
    for p in all_posts:
        media_groups[p["media_id"]].append(p)

    # Find groups with more than 1 post sharing same image
    duplicates = {mid: posts for mid, posts in media_groups.items() if len(posts) > 1}
    print(f"[INFO] Found {len(duplicates)} media IDs shared across multiple posts")

    if not duplicates:
        print("[INFO] No duplicate images found. All posts have unique images.")
        return

    fixed = 0
    total = 0
    for media_id, posts in duplicates.items():
        print(f"\n[GROUP] media_id={media_id} shared by {len(posts)} posts:")
        for p in posts:
            print(f"  - Post {p['id']}: {p['title'][:60]}")

        # Keep the first post's image, reassign the rest
        for post in posts[1:]:
            total += 1
            success = assign_new_image(post)
            if success:
                fixed += 1
            time.sleep(3)

    print(f"\n[DONE] Fixed {fixed}/{total} posts with duplicate images")


if __name__ == "__main__":
    main()
