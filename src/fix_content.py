"""
Batch content fixer — finds posts with very short or missing content and rewrites them using AI.
Run via: python src/fix_content.py
"""
import sys
import os
import re
import time
import requests

sys.path.insert(0, os.path.dirname(__file__))

from config import WP_URL, WP_USER, WP_APP_PASSWORD
from writer import _groq_call, _CONTENT_PROMPT, fetch_article_text

MIN_CONTENT_LENGTH = 400  # posts shorter than this get rewritten


def get_posts_with_short_content(per_page=50):
    posts = []
    page = 1
    while True:
        resp = requests.get(
            f"{WP_URL}/wp-json/wp/v2/posts",
            params={
                "per_page": per_page,
                "page": page,
                "status": "publish",
                "_fields": "id,title,content,link,excerpt"
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
        for p in batch:
            content = p.get("content", {}).get("rendered", "") or ""
            # Strip HTML to check actual text length
            text_only = re.sub(r'<[^>]+>', '', content).strip()
            title = p.get("title", {}).get("rendered", "")
            if len(text_only) < MIN_CONTENT_LENGTH:
                posts.append({
                    "id": p["id"],
                    "title": title,
                    "link": p.get("link", ""),
                    "content_length": len(text_only),
                    "excerpt": p.get("excerpt", {}).get("rendered", "")
                })
                print(f"  [SHORT] Post {p['id']}: {len(text_only)} chars — {title[:60]}")
        if len(batch) < per_page:
            break
        page += 1
    return posts


def rewrite_post_content(post):
    post_id = post["id"]
    title = post["title"]
    link = post["link"]
    print(f"\n[FIX] Post {post_id}: {title[:70]}")

    # Try to fetch original article text from the post URL
    article_text = fetch_article_text(link) if link else ""
    summary = post.get("excerpt", "") or title

    # Strip HTML from summary
    summary = re.sub(r'<[^>]+>', '', summary).strip()[:300]

    prompt = _CONTENT_PROMPT.format(
        title=title,
        source_name="IndiaBBCNews",
        summary=summary or title,
        article_text=article_text or "(use title only, write a complete news article)"
    )

    try:
        content_html = _groq_call(prompt, max_tokens=1500)
        content_html = re.sub(r'^```[a-z]*\s*', '', content_html, flags=re.MULTILINE)
        content_html = re.sub(r'```\s*$', '', content_html, flags=re.MULTILINE).strip()

        if not content_html or len(content_html) < 200:
            print(f"  [WARN] Generated content too short: {len(content_html)} chars")
            return False
        if not content_html.startswith("<"):
            content_html = "<p>" + content_html.replace("\n\n", "</p><p>") + "</p>"

        full_content = content_html

        # Update the post
        resp = requests.post(
            f"{WP_URL}/wp-json/wp/v2/posts/{post_id}",
            auth=(WP_USER, WP_APP_PASSWORD),
            json={"content": full_content},
            timeout=20
        )
        resp.raise_for_status()
        print(f"  [OK] Updated post {post_id}: {len(full_content)} chars")
        return True

    except Exception as e:
        print(f"  [ERROR] Failed post {post_id}: {e}")
        return False


def main():
    print("[START] Content fixer")
    print(f"[INFO] Finding posts with less than {MIN_CONTENT_LENGTH} chars of content...")
    posts = get_posts_with_short_content()
    print(f"\n[INFO] Found {len(posts)} posts needing content fix")

    if not posts:
        print("[INFO] All posts have sufficient content. Nothing to do.")
        return

    fixed = 0
    for i, post in enumerate(posts):
        success = rewrite_post_content(post)
        if success:
            fixed += 1
        # Rate limit delay between posts
        if i < len(posts) - 1:
            print(f"  [WAIT] 70s rate limit delay...")
            time.sleep(70)

    print(f"\n[DONE] Fixed {fixed}/{len(posts)} posts")


if __name__ == "__main__":
    main()
