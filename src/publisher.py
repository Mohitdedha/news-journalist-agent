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


def check_duplicate_in_wp(headline, threshold=0.80):
    """Search WordPress for posts with similar titles to avoid duplicates."""
    try:
        # Search by first significant words
        search_term = " ".join(headline.split()[:5])
        resp = requests.get(
            f"{WP_URL}/wp-json/wp/v2/posts",
            params={"search": search_term, "per_page": 5, "_fields": "id,title,link"},
            timeout=10
        )
        resp.raise_for_status()
        for post in resp.json():
            existing_title = post.get("title", {}).get("rendered", "")
            sim = SequenceMatcher(None, headline.lower(), existing_title.lower()).ratio()
            if sim >= threshold:
                print(f"[INFO] Duplicate found in WP: '{existing_title}' (sim={sim:.2f})")
                return True
        return False
    except Exception as e:
        print(f"[WARN] WP duplicate check failed: {e}")
        return False  # assume no duplicate on error


def create_post(article, wp_category_id, featured_media_id=None, publish_status="draft"):
    """
    Create a WordPress post. Returns post ID or None.
    publish_status: 'draft' for testing, 'publish' for live
    """
    headline = article["headline"]
    content = article["content_html"]
    meta_desc = article["meta_description"]
    tags_list = article.get("tags", [])

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
