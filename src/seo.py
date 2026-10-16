"""
Search engine discovery: IndexNow (Bing/Yandex), sitemap ping.
Does NOT assume Google Indexing API eligibility — uses standard sitemap pings.
"""
import time
import hashlib
import requests
from config import INDEXNOW_KEY, WP_URL


def submit_indexnow(urls):
    """
    Submit URLs to IndexNow (Bing, Yandex, Seznam).
    Free, immediate, no quota issues.
    """
    if not INDEXNOW_KEY:
        print("[INFO] INDEXNOW_KEY not set — skipping IndexNow submission")
        return

    if isinstance(urls, str):
        urls = [urls]

    payload = {
        "host": "indiabbcnews.com",
        "key": INDEXNOW_KEY,
        "keyLocation": f"https://indiabbcnews.com/{INDEXNOW_KEY}.txt",
        "urlList": urls
    }

    try:
        resp = requests.post(
            "https://api.indexnow.org/indexnow",
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=15
        )
        if resp.status_code in (200, 202):
            print(f"[OK] IndexNow submitted {len(urls)} URL(s)")
        else:
            print(f"[WARN] IndexNow response: {resp.status_code} {resp.text[:100]}")
    except Exception as e:
        print(f"[WARN] IndexNow error: {e}")


def ping_sitemap():
    """Ping search engines about sitemap update."""
    sitemap_url = f"{WP_URL}/sitemap_index.xml"
    ping_urls = [
        f"https://www.bing.com/ping?sitemap={sitemap_url}",
    ]
    for url in ping_urls:
        try:
            resp = requests.get(url, timeout=10)
            print(f"[OK] Sitemap ping: {url[:60]} → {resp.status_code}")
        except Exception as e:
            print(f"[WARN] Sitemap ping error: {e}")
        time.sleep(1)


def generate_indexnow_key_file(key):
    """
    Print the content to upload as /{key}.txt to verify ownership.
    Only needs to be done once.
    """
    print(f"Upload this file to https://indiabbcnews.com/{key}.txt")
    print(f"File content: {key}")
