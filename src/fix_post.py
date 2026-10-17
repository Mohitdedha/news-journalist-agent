"""
One-shot script to regenerate and update a specific WordPress post.
Run via: python src/fix_post.py <post_id> <headline> <summary>
"""
import sys
import os
import requests
import time

sys.path.insert(0, os.path.dirname(__file__))
from config import WP_URL, WP_USER, WP_APP_PASSWORD, GROQ_API_KEY
from writer import _groq_call, _CONTENT_PROMPT, _META_PROMPT
from publisher import resolve_tags


def fix_post(post_id, title, source_name, summary):
    print(f"[FIX] Regenerating content for post {post_id}: {title[:60]}")

    content_prompt = _CONTENT_PROMPT.format(
        title=title, source_name=source_name,
        summary=summary, article_text="(use title and summary only)"
    )
    meta_prompt = _META_PROMPT.format(title=title, summary=summary)

    import re, json

    # Generate content
    content_html = _groq_call(content_prompt, max_tokens=700)
    content_html = re.sub(r'^```[a-z]*\s*', '', content_html, flags=re.MULTILINE)
    content_html = re.sub(r'```\s*$', '', content_html, flags=re.MULTILINE).strip()
    if not content_html.startswith("<"):
        content_html = "<p>" + content_html.replace("\n\n", "</p><p>") + "</p>"

    print(f"[FIX] Content: {len(content_html)} chars")
    time.sleep(5)

    # Generate metadata
    meta_raw = _groq_call(meta_prompt, max_tokens=200)
    meta_raw = re.sub(r'^```[a-z]*\s*', '', meta_raw, flags=re.MULTILINE)
    meta_raw = re.sub(r'```\s*$', '', meta_raw, flags=re.MULTILINE).strip()
    m = re.search(r'\{.*\}', meta_raw, re.DOTALL)
    meta = json.loads(m.group()) if m else {}

    headline = meta.get("headline", title)
    meta_desc = meta.get("meta_description", "")
    tags = [str(t) for t in meta.get("tags", [])[:8]]

    disclosure = (
        '<p><em>This article was compiled by the IndiaBBCNews editorial system from '
        f'verified international news sources. Original reporting: {source_name}.</em></p>'
    )
    full_content = content_html + disclosure

    tag_ids = resolve_tags(tags)

    auth = (WP_USER, WP_APP_PASSWORD)
    payload = {
        "title": headline,
        "content": full_content,
        "meta": {"_yoast_wpseo_metadesc": meta_desc},
        "tags": tag_ids,
    }
    resp = requests.post(
        f"{WP_URL}/wp-json/wp/v2/posts/{post_id}",
        auth=auth, json=payload, timeout=30
    )
    resp.raise_for_status()
    post = resp.json()
    print(f"[FIX] Updated post {post_id}: {post.get('link', '')}")
    return post.get("link", "")


if __name__ == "__main__":
    # Post 10082: Sudan RSF
    fix_post(
        post_id=10082,
        title="Sudan Civil War: RSF Captures Khartoum Airport, Cuts Off Capital",
        source_name="Reuters",
        summary="Sudan's Rapid Support Forces (RSF) have captured Khartoum's international airport, cutting off the capital from resupply as the civil war intensifies. The military government has denied the claim."
    )
    time.sleep(65)
    # Post 10081: UK PM Starmer defence
    fix_post(
        post_id=10081,
        title="UK PM Starmer Announces £15 Billion Emergency Defence Budget Boost",
        source_name="BBC",
        summary="UK Prime Minister Keir Starmer has announced a £15 billion increase to the defence budget as part of an emergency spending review, amid growing concerns over European security and pressure from NATO allies."
    )
    print("[DONE] Both posts updated.")
