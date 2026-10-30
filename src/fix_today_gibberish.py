"""
Detects and removes gibberish/repetitive padding from today's articles.
Looks for patterns like "The next is next. The next is here." etc.
Does NOT rewrite — just strips the gibberish tail from content.
"""
import sys
import os
import re
import time
import requests
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))
from config import WP_URL, WP_USER, WP_APP_PASSWORD

# Gibberish detection: 3+ repetitions of "The next is" or similar
GIBBERISH_PATTERNS = [
    r'(The next is \w+\.?\s*){3,}',
    r'(The next is \w+ \w+\.?\s*){2,}',
    r'(\bThe next\b.{0,30}\n?){4,}',
]

# Cut point: where gibberish starts
GIBBERISH_MARKERS = [
    'The next is next.',
    'The next is here.',
    'The next is us.',
    'The next is you.',
    'The next is me.',
    'The next is everyone.',
    'The next is all of us.',
]


def find_gibberish_start(text):
    """Return index where gibberish starts, or -1 if not found."""
    for marker in GIBBERISH_MARKERS:
        idx = text.find(marker)
        if idx != -1:
            # Walk back to find the paragraph start
            para_start = text.rfind('<p>', 0, idx)
            if para_start != -1:
                return para_start
            return idx
    return -1


def fix_content(content):
    """Strip gibberish tail from HTML content."""
    # Work on raw HTML
    idx = find_gibberish_start(content)
    if idx == -1:
        return content, False

    # Keep everything before the gibberish paragraph
    clean = content[:idx].rstrip()

    # Make sure it ends with a closing tag
    if not clean.endswith('>'):
        last_close = max(clean.rfind('</p>'), clean.rfind('</h2>'), clean.rfind('</h3>'))
        if last_close != -1:
            clean = clean[:last_close + len('</p>')]

    return clean, True


def get_today_posts():
    """Fetch posts published today."""
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    posts = []
    page = 1
    while True:
        resp = requests.get(
            f"{WP_URL}/wp-json/wp/v2/posts",
            params={
                "per_page": 100, "page": page,
                "status": "publish",
                "after": f"{today}T00:00:00Z",
                "_fields": "id,title,content,date"
            },
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
        if len(batch) < 100:
            break
        page += 1
    return posts


def main():
    print("[START] Gibberish fixer for today's articles")
    posts = get_today_posts()
    print(f"[INFO] Today's posts: {len(posts)}")

    fixed = 0
    clean = 0

    for post in posts:
        post_id = post["id"]
        title = post.get("title", {}).get("rendered", "")[:60]
        content = post.get("content", {}).get("rendered", "") or ""

        new_content, changed = fix_content(content)

        if not changed:
            clean += 1
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
            print(f"  [FIXED] {post_id}: {title}")
        except Exception as e:
            print(f"  [ERROR] {post_id}: {e}")

        time.sleep(0.5)

    print(f"\n[DONE] Fixed: {fixed} | Already clean: {clean}")


if __name__ == "__main__":
    main()
