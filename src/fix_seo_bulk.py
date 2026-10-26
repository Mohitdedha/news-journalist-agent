"""
Bulk SEO fix: update Yoast title, meta description, and focus keyphrase
for all published WordPress posts using rule-based generation (no AI needed).
"""
import sys, os, time, re, requests
sys.path.insert(0, os.path.dirname(__file__))
from config import WP_URL, WP_USER, WP_APP_PASSWORD

AUTH = (WP_USER, WP_APP_PASSWORD)

STOP = {"the","a","an","of","in","on","at","to","for","is","are","was","were",
        "and","or","but","with","from","by","as","its","it","this","that","s",
        "after","before","over","under","about","into","than","will","has","have",
        "new","says","say","amid","who","what","why","how","when","where"}


def make_seo_title(headline):
    """Headline + ' - India BBC News', max 65 chars."""
    suffix = " - India BBC News"
    max_hl = 65 - len(suffix)
    if len(headline) > max_hl:
        headline = headline[:max_hl-3].rsplit(" ", 1)[0] + "..."
    return headline + suffix


def make_meta_desc(headline, content_text):
    """First clean sentence from content, 120-150 chars."""
    # Try to get first real sentence from content
    sentences = re.split(r'(?<=[.!?])\s+', content_text.strip())
    for s in sentences:
        s = s.strip()
        if 80 <= len(s) <= 150:
            return s[:150]
        if len(s) > 150:
            return s[:147] + "..."
    # Fallback: use headline padded
    desc = headline
    if len(desc) < 80:
        desc = desc + ". Read the full story on India BBC News for details and analysis."
    return desc[:150]


def make_keyphrase(headline):
    """Extract 2-4 key words from headline."""
    words = [w.strip("'\",.!?:()") for w in headline.split()
             if len(w.strip("'\",.!?:()")) > 3
             and w.strip("'\",.!?:()").lower() not in STOP]
    return " ".join(words[:3])[:50] if words else headline.split()[0]


def get_all_posts():
    posts = []
    page = 1
    while True:
        r = requests.get(
            f"{WP_URL}/wp-json/wp/v2/posts",
            params={"per_page": 100, "page": page, "status": "publish",
                    "_fields": "id,title,content,meta"},
            auth=AUTH, timeout=30
        )
        if r.status_code == 400:
            break
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        posts.extend(batch)
        print(f"  Page {page}: {len(batch)} posts (total: {len(posts)})")
        page += 1
        time.sleep(0.3)
    return posts


def update_post_seo(post_id, seo_title, meta_desc, keyphrase):
    r = requests.post(
        f"{WP_URL}/wp-json/wp/v2/posts/{post_id}",
        auth=AUTH,
        json={"meta": {
            "_yoast_wpseo_title": seo_title,
            "_yoast_wpseo_metadesc": meta_desc,
            "_yoast_wpseo_focuskw": keyphrase,
        }},
        timeout=15
    )
    r.raise_for_status()


def main():
    print("[START] Fetching all posts...")
    posts = get_all_posts()
    print(f"[INFO] Total posts: {len(posts)}")

    updated = 0
    skipped = 0
    errors = 0

    for i, post in enumerate(posts):
        pid = post["id"]
        title_raw = post.get("title", {}).get("rendered", "")
        headline = re.sub(r'<[^>]+>', '', title_raw).strip()
        headline = headline.replace("&#8217;", "'").replace("&amp;", "&").replace("&#8211;", "-")

        meta = post.get("meta", {})
        existing_title = (meta.get("_yoast_wpseo_title") or "").strip()
        existing_desc = (meta.get("_yoast_wpseo_metadesc") or "").strip()
        existing_kw = (meta.get("_yoast_wpseo_focuskw") or "").strip()

        if existing_title and existing_desc and existing_kw:
            skipped += 1
            if skipped % 50 == 0:
                print(f"  Skipped {skipped} already-complete posts...")
            continue

        content_html = post.get("content", {}).get("rendered", "")
        content_text = re.sub(r'<[^>]+>', ' ', content_html)
        content_text = re.sub(r'\s+', ' ', content_text).strip()

        seo_title  = existing_title  or make_seo_title(headline)
        meta_desc  = existing_desc   or make_meta_desc(headline, content_text)
        keyphrase  = existing_kw     or make_keyphrase(headline)

        try:
            update_post_seo(pid, seo_title, meta_desc, keyphrase)
            updated += 1
            print(f"[{i+1}/{len(posts)}] OK: {headline[:55].encode('ascii','replace').decode()}")
            time.sleep(0.5)
        except Exception as e:
            errors += 1
            print(f"[{i+1}/{len(posts)}] ERROR pid={pid}: {str(e)[:80]}")
            time.sleep(1)

    print(f"\n[DONE] Updated: {updated} | Skipped (already OK): {skipped} | Errors: {errors}")


if __name__ == "__main__":
    main()
