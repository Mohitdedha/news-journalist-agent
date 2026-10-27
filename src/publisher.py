"""
Publish articles to WordPress via REST API.
Uses Application Passwords (no plugin required).
Prevents duplicate posts by checking existing titles before publishing.
"""
import re
import time
import requests
from difflib import SequenceMatcher
from config import WP_URL, WP_USER, WP_APP_PASSWORD, load_history, save_history


def _auth():
    return (WP_USER, WP_APP_PASSWORD)


def _keyword_overlap(a, b):
    """Return ratio of shared meaningful words between two titles."""
    stop = {"the", "a", "an", "of", "in", "on", "at", "to", "for", "is", "are",
            "was", "were", "and", "or", "but", "with", "from", "by", "as", "its",
            "it", "this", "that", "has", "have", "had", "be", "been", "s"}
    words_a = set(w.strip("'\",.!?").lower() for w in a.split() if w.lower() not in stop and len(w) > 2)
    words_b = set(w.strip("'\",.!?").lower() for w in b.split() if w.lower() not in stop and len(w) > 2)
    if not words_a or not words_b:
        return 0.0
    overlap = len(words_a & words_b)
    return overlap / min(len(words_a), len(words_b))


def check_duplicate_in_wp(headline, threshold=0.72):
    """Search WordPress for posts with similar titles to avoid duplicates.

    Uses both string similarity AND keyword overlap to catch paraphrased titles
    about the same topic (e.g. 'Dancing Salaryman Goes Viral' vs 'Salaryman
    Takes Internet by Storm').
    """
    try:
        # Search by first significant words
        search_term = " ".join(headline.split()[:5])
        resp = requests.get(
            f"{WP_URL}/wp-json/wp/v2/posts",
            params={"search": search_term, "per_page": 10, "_fields": "id,title,link"},
            timeout=10
        )
        resp.raise_for_status()
        for post in resp.json():
            existing_title = post.get("title", {}).get("rendered", "")
            sim = SequenceMatcher(None, headline.lower(), existing_title.lower()).ratio()
            kw = _keyword_overlap(headline, existing_title)
            if sim >= threshold or kw >= 0.70:
                print(f"[INFO] Duplicate in WP: '{existing_title}' (sim={sim:.2f}, kw={kw:.2f})")
                return True
        return False
    except Exception as e:
        print(f"[WARN] WP duplicate check failed: {e}")
        return False  # assume no duplicate on error


def _fetch_recent_posts(limit=20):
    """Fetch recent published posts for internal linking."""
    try:
        resp = requests.get(
            f"{WP_URL}/wp-json/wp/v2/posts",
            params={"per_page": limit, "status": "publish", "_fields": "id,title,link,tags"},
            timeout=10
        )
        resp.raise_for_status()
        posts = []
        for p in resp.json():
            title = p.get("title", {}).get("rendered", "")
            link = p.get("link", "")
            if title and link:
                posts.append({"title": title, "link": link})
        return posts
    except Exception as e:
        print(f"[WARN] Could not fetch posts for internal links: {e}")
        return []


def _inject_internal_links(content, headline, recent_posts, max_links=2):
    """
    Find 2 related posts and inject <a href> links naturally into the content.
    Matches on shared keywords between current headline and recent post titles.
    """
    stop = {"the","a","an","of","in","on","at","to","for","is","are","was","were",
            "and","or","but","with","from","by","as","its","it","this","that","s",
            "pm","said","says","new","over","after","before","than","will","have"}

    def keywords(text):
        return set(w.strip("'\",.!?:()").lower() for w in text.split()
                   if len(w) > 3 and w.strip("'\",.!?:()").lower() not in stop)

    current_kw = keywords(headline)
    candidates = []
    for post in recent_posts:
        post_kw = keywords(post["title"])
        overlap = len(current_kw & post_kw)
        if overlap >= 1:
            candidates.append((overlap, post))

    candidates.sort(key=lambda x: -x[0])
    chosen = [p for _, p in candidates[:max_links]]

    if not chosen:
        return content

    # Inject links after first </p> occurrences (natural mid-article placement)
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(content, "html.parser")
    paragraphs = soup.find_all("p")
    link_idx = 0

    for i, para in enumerate(paragraphs):
        if link_idx >= len(chosen):
            break
        # Skip very short paragraphs and the last one (usually source/disclosure)
        if len(para.get_text()) < 80 or i == len(paragraphs) - 1:
            continue
        # Skip if paragraph already has a link
        if para.find("a"):
            continue

        post = chosen[link_idx]
        # Find a keyword from the related post title that appears in this paragraph
        para_text = para.get_text().lower()
        post_kw = keywords(post["title"])
        anchor_word = next((w for w in post_kw if w in para_text), None)

        if anchor_word:
            # Replace first occurrence of the word with a link
            old_html = str(para)
            # Case-insensitive replace of first occurrence
            pattern = re.compile(re.escape(anchor_word), re.IGNORECASE)
            def replace_with_link(m):
                return f'<a href="{post["link"]}" title="{post["title"]}">{m.group()}</a>'
            new_html = pattern.sub(replace_with_link, old_html, count=1)
            if new_html != old_html:
                para.replace_with(BeautifulSoup(new_html, "html.parser").find("p") or para)
                link_idx += 1

    result = str(soup)
    if link_idx > 0:
        print(f"[INFO] Injected {link_idx} internal link(s)")
    return result


_BAD_CONTENT_PATTERNS = re.compile(
    r'^\s*(undefined|null|none|nan|error|<p>\s*undefined\s*</p>|<p>\s*null\s*</p>)\s*$',
    re.IGNORECASE
)

def _validate_content(headline, content):
    """Last-resort content guard before publishing to WordPress. Raises on bad content."""
    if not content or not content.strip():
        raise ValueError("Content is empty")
    text_only = re.sub(r'<[^>]+>', '', content).strip()
    if len(text_only) < 400:
        raise ValueError(f"Content too short after stripping HTML: {len(text_only)} chars")
    # Check for AI failure tokens anywhere in the text
    lower = text_only.lower()
    for bad in ("undefined", "null\n", "[object object]", "lorem ipsum", "insert content here"):
        if lower.strip() == bad or lower.startswith(bad + "\n"):
            raise ValueError(f"Content is placeholder: starts with '{bad}'")
    if not headline or len(headline.strip()) < 5:
        raise ValueError(f"Headline too short: '{headline}'")


def create_post(article, wp_category_id, featured_media_id=None, publish_status="draft",
                category_name=""):
    """
    Create a WordPress post. Returns (post_id, post_url).
    publish_status: 'draft' for testing, 'publish' for live
    """
    headline = article["headline"]
    content = article["content_html"]
    meta_desc = article["meta_description"]
    tags_list = article.get("tags", [])

    # Ensure category exists on WordPress
    if category_name:
        wp_category_id = resolve_category(category_name, wp_category_id)

    # Hard guard — never publish garbage regardless of what writer returned
    _validate_content(headline, content)

    # Internal linking — fetch recent posts and inject 2 links
    recent_posts = _fetch_recent_posts(limit=20)
    content = _inject_internal_links(content, headline, recent_posts, max_links=3)

    # Add disclosure paragraph at end
    disclosure = (
        '<p><em>This article was compiled by the IndiaBBCNews editorial system from '
        'verified international news sources. Facts have been independently reviewed. '
        f'Original reporting: {article.get("source_name", "International sources")}.</em></p>'
    )
    content = content + disclosure

    # Resolve or create tag IDs
    tag_ids = resolve_tags(tags_list)

    payload = {
        "title": headline,
        "content": content,
        "status": publish_status,
        "categories": [wp_category_id],
        "tags": tag_ids,
        "meta": {
            "_yoast_wpseo_title": headline + " - India BBC News",
            "_yoast_wpseo_metadesc": meta_desc,
        },
    }
    if featured_media_id:
        payload["featured_media"] = featured_media_id

    try:
        resp = requests.post(
            f"{WP_URL}/wp-json/wp/v2/posts",
            auth=_auth(),
            json=payload,
            timeout=30
        )
        resp.raise_for_status()
        post = resp.json()
        post_id = post["id"]
        post_link = post.get("link", "")
        print(f"[OK] Post created: ID={post_id} status={publish_status} url={post_link}")
        return post_id, post_link
    except requests.HTTPError as e:
        body = e.response.text[:300] if e.response else ""
        raise RuntimeError(f"WordPress post creation failed: {e} — {body}")


def resolve_category(category_name, category_id):
    """Ensure WP category exists; if not found by ID, find/create by name. Returns actual ID."""
    try:
        resp = requests.get(
            f"{WP_URL}/wp-json/wp/v2/categories/{category_id}",
            auth=_auth(), timeout=10
        )
        if resp.status_code == 200:
            return category_id
        # Category ID doesn't exist — find or create by name
        search = requests.get(
            f"{WP_URL}/wp-json/wp/v2/categories",
            params={"search": category_name, "per_page": 5},
            auth=_auth(), timeout=10
        )
        search.raise_for_status()
        for cat in search.json():
            if cat.get("name","").lower() == category_name.lower():
                print(f"[INFO] Found existing category '{category_name}' id={cat['id']}")
                return cat["id"]
        # Create it
        create = requests.post(
            f"{WP_URL}/wp-json/wp/v2/categories",
            auth=_auth(), json={"name": category_name.title()}, timeout=10
        )
        create.raise_for_status()
        new_id = create.json()["id"]
        print(f"[INFO] Created category '{category_name}' id={new_id}")
        return new_id
    except Exception as e:
        print(f"[WARN] Category resolve error: {e}, using id={category_id}")
        return category_id


def resolve_tags(tag_names):
    """Get or create tag IDs for given tag names."""
    ids = []
    for name in tag_names[:8]:  # cap at 8 tags
        try:
            # Search for existing tag
            resp = requests.get(
                f"{WP_URL}/wp-json/wp/v2/tags",
                params={"search": name, "per_page": 1},
                timeout=10
            )
            resp.raise_for_status()
            results = resp.json()
            if results:
                ids.append(results[0]["id"])
            else:
                # Create new tag
                resp2 = requests.post(
                    f"{WP_URL}/wp-json/wp/v2/tags",
                    auth=_auth(),
                    json={"name": name},
                    timeout=10
                )
                resp2.raise_for_status()
                ids.append(resp2.json()["id"])
        except Exception as e:
            print(f"[WARN] Tag '{name}' error: {e}")
    return ids


def test_connection():
    """Verify WordPress credentials before any publishing."""
    try:
        resp = requests.get(
            f"{WP_URL}/wp-json/wp/v2/users/me",
            auth=_auth(),
            timeout=10
        )
        resp.raise_for_status()
        user = resp.json()
        print(f"[OK] WordPress auth OK — user: {user.get('name')} capabilities: {list(user.get('capabilities', {}).keys())[:5]}")
        return True
    except Exception as e:
        print(f"[ERROR] WordPress auth failed: {e}")
        return False
