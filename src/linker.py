"""
Internal linking: fetches recent WordPress posts and injects
relevant anchor links into new article HTML.
"""
import re
import requests
from config import WP_URL, WP_USER, WP_APP_PASSWORD

_STOP = {"the","a","an","of","in","on","at","to","for","is","are","was","were",
         "and","or","but","with","from","by","as","its","it","this","that","s",
         "new","over","after","than","will","have","been","amid","say","says",
         "i","we","he","she","they","who","what","when","where","how","which"}


def _keywords(text):
    words = re.findall(r"[a-zA-Z]{4,}", text.lower())
    return {w for w in words if w not in _STOP}


def _fetch_recent_posts(limit=30):
    """Return list of {title, link, keywords} for recent published posts."""
    try:
        resp = requests.get(
            f"{WP_URL}/wp-json/wp/v2/posts",
            params={"per_page": limit, "status": "publish",
                    "_fields": "id,title,link"},
            auth=(WP_USER, WP_APP_PASSWORD),
            timeout=10,
        )
        resp.raise_for_status()
        posts = []
        for p in resp.json():
            title = p.get("title", {}).get("rendered", "")
            link  = p.get("link", "")
            if title and link:
                posts.append({"title": title, "link": link,
                               "keywords": _keywords(title)})
        return posts
    except Exception as e:
        print(f"[WARN] Internal linking: could not fetch posts: {e}")
        return []


def add_internal_links(content_html, current_headline, max_links=3):
    """
    Scan content_html for phrases that match recent post titles and wrap
    them in <a href="..."> tags.  Adds at most max_links links.
    Skips the current article (matched by headline).
    """
    if not WP_USER or not WP_APP_PASSWORD:
        return content_html

    recent = _fetch_recent_posts(limit=40)
    current_kw = _keywords(current_headline)

    # Score each post by keyword overlap with current article content
    content_kw = _keywords(re.sub(r'<[^>]+>', ' ', content_html))
    candidates = []
    for post in recent:
        # Skip if same article
        if post["keywords"] & current_kw and len(post["keywords"] & current_kw) > 3:
            continue
        overlap = len(post["keywords"] & content_kw)
        if overlap >= 2:
            candidates.append((overlap, post))

    # Sort by overlap descending, take top max_links
    candidates.sort(key=lambda x: -x[0])
    linked = 0

    for _, post in candidates:
        if linked >= max_links:
            break
        title = post["title"]
        link  = post["link"]

        # Find a multi-word phrase from the post title inside content (case-insensitive)
        words = [w for w in re.findall(r"[a-zA-Z]{4,}", title) if w.lower() not in _STOP]
        if len(words) < 2:
            continue

        # Try longest matching phrase first (up to 4 words)
        for n in range(min(4, len(words)), 1, -1):
            phrase = r"\s+".join(re.escape(w) for w in words[:n])
            pattern = re.compile(rf'(?<!["\'])\b({phrase})\b(?!["\'])', re.IGNORECASE)
            # Only replace FIRST occurrence and only inside <p> text (not in existing <a> tags)
            # Avoid replacing inside existing anchor tags
            def replace_outside_anchors(html, pat, replacement_fn):
                parts = re.split(r'(<a\b[^>]*>.*?</a>)', html, flags=re.IGNORECASE | re.DOTALL)
                result = []
                for part in parts:
                    if part.lower().startswith('<a'):
                        result.append(part)
                    else:
                        replaced, count = pat.subn(replacement_fn, part, count=1)
                        result.append(replaced)
                        if count:
                            return "".join(result), True
                return "".join(result), False

            new_html, found = replace_outside_anchors(
                content_html,
                pattern,
                lambda m: f'<a href="{link}" title="{title}">{m.group(0)}</a>'
            )
            if found:
                content_html = new_html
                linked += 1
                print(f"[LINK] Added internal link → {title[:50]}")
                break

    if linked:
        print(f"[LINK] {linked} internal link(s) added")
    return content_html
