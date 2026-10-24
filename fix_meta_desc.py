"""
Fix old WordPress posts missing meta description (_yoast_wpseo_metadesc).
Fetches posts page-by-page, checks if yoast meta is empty, generates a
description from the excerpt/content, then patches via REST API.
"""
import os, re, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
import requests
from config import WP_URL, WP_USER, WP_APP_PASSWORD as WP_PASS

WP_URL = WP_URL.rstrip("/")
AUTH = (WP_USER, WP_PASS)

if not all([WP_URL, WP_USER, WP_PASS]):
    sys.exit("ERROR: WP_URL / WP_USER / WP_APP_PASSWORD not set in config")

def strip_html(html):
    return re.sub(r"<[^>]+>", " ", html or "").strip()

def truncate(text, max_len=155):
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= max_len else text[:max_len-3].rsplit(" ", 1)[0] + "..."

fixed = skipped = 0
page = 1

print(f"Connecting to {WP_URL} ...")

while True:
    resp = requests.get(
        f"{WP_URL}/wp-json/wp/v2/posts",
        params={"per_page": 100, "page": page, "_fields": "id,title,excerpt,content,meta", "status": "publish"},
        auth=AUTH, timeout=30,
    )
    if resp.status_code == 400:
        break  # no more pages
    resp.raise_for_status()
    posts = resp.json()
    if not posts:
        break

    for p in posts:
        pid    = p["id"]
        meta   = p.get("meta", {}) or {}
        desc   = (meta.get("_yoast_wpseo_metadesc") or "").strip()
        if desc:
            skipped += 1
            continue

        # Build description from excerpt or content
        raw = strip_html(p.get("excerpt", {}).get("rendered", "")) \
              or strip_html(p.get("content", {}).get("rendered", ""))
        if not raw:
            skipped += 1
            continue

        new_desc = truncate(raw)

        patch = requests.post(
            f"{WP_URL}/wp-json/wp/v2/posts/{pid}",
            auth=AUTH,
            json={"meta": {"_yoast_wpseo_metadesc": new_desc}},
            timeout=20,
        )
        if patch.status_code in (200, 201):
            fixed += 1
            print(f"[OK] #{pid} — {p['title']['rendered'][:60]}")
        else:
            print(f"[FAIL] #{pid} status={patch.status_code}: {patch.text[:80]}")

    total_pages = int(resp.headers.get("X-WP-TotalPages", 1))
    if page >= total_pages:
        break
    page += 1

print(f"\nDone — fixed: {fixed}, already had desc: {skipped}")
