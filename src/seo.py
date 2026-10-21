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
        f"https://www.google.com/ping?sitemap={sitemap_url}",
    ]
    for url in ping_urls:
        try:
            resp = requests.get(url, timeout=10)
            print(f"[OK] Sitemap ping: {url[:60]} → {resp.status_code}")
        except Exception as e:
            print(f"[WARN] Sitemap ping error: {e}")
        time.sleep(1)


def ping_rpc_services(post_title, post_url):
    """
    Ping blog-discovery RPC services (Ping-O-Matic, Twingly, etc.)
    Notifies aggregators & backlink crawlers about new content.
    """
    xml = f"""<?xml version="1.0"?>
<methodCall>
  <methodName>weblogUpdates.extendedPing</methodName>
  <params>
    <param><value><string>India BBC News</string></value></param>
    <param><value><string>https://indiabbcnews.com</string></value></param>
    <param><value><string>{post_url}</string></value></param>
    <param><value><string>https://indiabbcnews.com/sitemap_index.xml</string></value></param>
  </params>
</methodCall>"""

    endpoints = [
        "http://rpc.pingomatic.com/",
        "http://ping.blogs.com/weblogUpdates.extendedPing",
        "http://blogsearch.google.com/ping/RPC2",
        "http://rpc.twingly.com/",
        "http://api.feedster.com/ping",
    ]
    headers = {"Content-Type": "text/xml"}
    ok = 0
    for ep in endpoints:
        try:
            r = requests.post(ep, data=xml.encode("utf-8"), headers=headers, timeout=8)
            if r.status_code == 200:
                ok += 1
        except Exception:
            pass
    print(f"[SEO] RPC pings sent: {ok}/{len(endpoints)} services responded")


def generate_indexnow_key_file(key):
    """
    Print the content to upload as /{key}.txt to verify ownership.
    Only needs to be done once.
    """
    print(f"Upload this file to https://indiabbcnews.com/{key}.txt")
    print(f"File content: {key}")
