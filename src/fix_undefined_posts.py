"""
Find WordPress posts with 'undefined' content and regenerate them using AI.
Run via GitHub Actions: Fix Missing Content workflow.
"""
import os
import re
import sys
import time
import requests

sys.path.insert(0, os.path.dirname(__file__))
from config import WP_URL, WP_USER, WP_APP_PASSWORD
from writer import write_article

AUTH = (WP_USER, WP_APP_PASSWORD)
HEADERS = {"Content-Type": "application/json"}


def get_undefined_posts(max_check=50):
    """Fetch recent posts and return those with undefined/empty content."""
    bad = []
    page = 1
    checked = 0
    while checked < max_check:
        resp = requests.get(
            f"{WP_URL}/wp-json/wp/v2/posts",
            params={"per_page": 20, "page": page, "status": "publish",
                    "_fields": "id,title,content,link,date"},
            timeout=15,
        )
        if resp.status_code == 400:
            break
        resp.raise_for_status()
        posts = resp.json()
        if not posts:
            break
        for post in posts:
            raw = re.sub(r'<[^>]+>', '', post["content"]["rendered"]).strip()
            if raw.lower().startswith("undefined") or len(raw) < 200:
                bad.append(post)
                print(f"[FOUND] ID={post['id']} — {post['title']['rendered'][:60]}")
            checked += 1
        page += 1
    return bad


def fix_post(post):
    """Regenerate article content for a post and update WordPress."""
    title = post["title"]["rendered"]
    post_id = post["id"]
    print(f"\n[FIX] Post {post_id}: {title[:70]}")

    # Build a minimal story dict for the writer
    story = {
        "title": title,
        "url": post["link"],
        "source_name": "International News Sources",
        "summary": title,
    }

    try:
        article = write_article(story)
    except Exception as e:
        print(f"[ERROR] Writer failed: {e}")
        return False

    content = article.get("content_html", "")
    meta_desc = article.get("meta_description", "")
    if not content or len(content) < 300:
        print(f"[SKIP] Generated content too short")
        return False

    # Update the post
    resp = requests.post(
        f"{WP_URL}/wp-json/wp/v2/posts/{post_id}",
        auth=AUTH,
        json={
            "content": content,
            "meta": {"_yoast_wpseo_metadesc": meta_desc},
        },
        timeout=30,
    )
    if resp.ok:
        print(f"[OK] Post {post_id} updated — {post['link']}")
        return True
    else:
        print(f"[WARN] Update failed: {resp.status_code} {resp.text[:200]}")
        return False


if __name__ == "__main__":
    print("[START] Scanning for undefined posts...")
    bad_posts = get_undefined_posts(max_check=100)
    print(f"\n[INFO] Found {len(bad_posts)} posts to fix")

    fixed = 0
    for post in bad_posts:
        ok = fix_post(post)
        if ok:
            fixed += 1
        time.sleep(35)  # respect Groq rate limits between AI calls

    print(f"\n[DONE] Fixed {fixed}/{len(bad_posts)} posts")
