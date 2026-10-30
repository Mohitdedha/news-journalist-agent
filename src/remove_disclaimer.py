"""
Removes the AI disclaimer line from all published WordPress posts.
Safe operation — only removes the specific disclaimer string, no content rewrite.
Run via GitHub Actions: python src/remove_disclaimer.py
"""
import sys
import os
import re
import time
import requests

sys.path.insert(0, os.path.dirname(__file__))
from config import WP_URL, WP_USER, WP_APP_PASSWORD

# The disclaimer patterns to remove (all variations)
DISCLAIMER_PATTERNS = [
    r'<p><em>This article was compiled by the IndiaBBCNews editorial system from verified international news sources\. Facts have been independently reviewed\. Original reporting:.*?</em></p>',
    r'<p><em>This article was compiled by the IndiaBBCNews editorial system from verified international news sources\. Facts have been independently reviewed\.</em></p>',
    r'<p><em>This article was compiled by the IndiaBBCNews editorial system from verified international news sources\.</em></p>',
]


def remove_disclaimer(content):
    """Remove all disclaimer variants from HTML content."""
    original = content
    for pattern in DISCLAIMER_PATTERNS:
        content = re.sub(pattern, '', content, flags=re.IGNORECASE | re.DOTALL)
    return content, content != original


def get_all_posts(per_page=100):
    posts = []
    page = 1
    while True:
        resp = requests.get(
            f"{WP_URL}/wp-json/wp/v2/posts",
            params={"per_page": per_page, "page": page, "status": "publish",
                    "_fields": "id,title,content"},
            auth=(WP_USER, WP_APP_PASSWORD),
            timeout=30
        )
        if resp.status_code == 400:
            break
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        posts.extend(batch)
        total_pages = int(resp.headers.get("X-WP-TotalPages", 1))
        print(f"  [INFO] Fetched page {page}/{total_pages} — {len(posts)} posts so far")
        if page >= total_pages:
            break
        page += 1
        time.sleep(1)
    return posts


def main():
    print("[START] Disclaimer remover")
    print("[INFO] Fetching all published posts...")
    posts = get_all_posts()
    print(f"[INFO] Total posts: {len(posts)}")

    fixed = 0
    skipped = 0

    for i, post in enumerate(posts):
        post_id = post["id"]
        title = post.get("title", {}).get("rendered", "")[:60]
        content = post.get("content", {}).get("rendered", "") or ""

        new_content, changed = remove_disclaimer(content)

        if not changed:
            skipped += 1
            continue

        try:
            resp = requests.post(
                f"{WP_URL}/wp-json/wp/v2/posts/{post_id}",
                auth=(WP_USER, WP_APP_PASSWORD),
                json={"content": new_content},
                timeout=20
            )
            resp.raise_for_status()
            fixed += 1
            print(f"  [OK] {post_id}: {title}")
        except Exception as e:
            print(f"  [ERROR] {post_id}: {e}")

        # Small delay to avoid hammering WordPress
        if i % 10 == 9:
            time.sleep(2)

    print(f"\n[DONE] Removed disclaimer from {fixed} posts | Skipped (no disclaimer): {skipped}")


if __name__ == "__main__":
    main()
