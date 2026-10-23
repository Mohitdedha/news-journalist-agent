"""
Search engine discovery: IndexNow (Bing/Yandex), sitemap ping.
Does NOT assume Google Indexing API eligibility — uses standard sitemap pings.
"""
import os
import time
import hashlib
import requests
from config import INDEXNOW_KEY, WP_URL, WP_USER, WP_APP_PASSWORD


def ensure_indexnow_key_file():
    """Upload the IndexNow key verification file to WordPress if not already present."""
    if not INDEXNOW_KEY or not WP_USER or not WP_APP_PASSWORD:
        return
    key_url = f"https://indiabbcnews.com/{INDEXNOW_KEY}.txt"
    try:
        r = requests.get(key_url, timeout=8)
        if r.status_code == 200 and r.text.strip() == INDEXNOW_KEY:
            return  # already verified
    except Exception:
        pass
    # Upload via WordPress REST API as a plain-text file
    try:
        resp = requests.post(
            f"{WP_URL}/wp-json/wp/v2/media",
            headers={"Content-Disposition": f'attachment; filename="{INDEXNOW_KEY}.txt"',
                     "Content-Type": "text/plain"},
            data=INDEXNOW_KEY.encode(),
            auth=(WP_USER, WP_APP_PASSWORD),
            timeout=15,
        )
        if resp.status_code in (200, 201):
            print(f"[OK] IndexNow key file uploaded: {key_url}")
        else:
            print(f"[WARN] IndexNow key upload failed: {resp.status_code}")
    except Exception as e:
        print(f"[WARN] IndexNow key upload error: {e}")


def submit_indexnow(urls):
    """
    Submit URLs to IndexNow (Bing, Yandex, Seznam).
    Free, immediate, no quota issues.
    """
    if not INDEXNOW_KEY:
        print("[INFO] INDEXNOW_KEY not set — skipping IndexNow submission")
        return

    ensure_indexnow_key_file()

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


def submit_to_google_indexing(post_url):
    """
    Submit URL via Google Indexing API (free for news/job sites).
    Requires GOOGLE_INDEXING_KEY env var (service account JSON as string).
    Falls back gracefully if not configured.
    """
    import os, json
    key_json = os.environ.get("GOOGLE_INDEXING_KEY", "")
    if not key_json:
        return  # not configured, skip silently

    try:
        import google.oauth2.service_account as sa
        import google.auth.transport.requests as ga_req

        creds_info = json.loads(key_json)
        creds = sa.Credentials.from_service_account_info(
            creds_info,
            scopes=["https://www.googleapis.com/auth/indexing"]
        )
        creds.refresh(ga_req.Request())
        token = creds.token

        resp = requests.post(
            "https://indexing.googleapis.com/v3/urlNotifications:publish",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"url": post_url, "type": "URL_UPDATED"},
            timeout=15
        )
        if resp.status_code == 200:
            print(f"[OK] Google Indexing API: {post_url}")
        else:
            print(f"[WARN] Google Indexing API {resp.status_code}: {resp.text[:100]}")
    except ImportError:
        pass  # google-auth not installed
    except Exception as e:
        print(f"[WARN] Google Indexing API error: {e}")


def submit_to_aggregators(post_url, post_title):
    """
    Submit new article URL to free content aggregators & RSS readers.
    These index content fast and send referral traffic.
    """
    rss_url = f"{WP_URL}/feed/"
    endpoints = [
        # Flipboard RSS ping
        f"https://flipboard.com/api/rss/subscribe?rss_url={rss_url}",
        # Feedly cloud ping
        f"https://cloud.feedly.com/v3/feeds/feed%2F{rss_url}",
        # Superfeedr hub notify
        "https://pubsubhubbub.superfeedr.com/",
    ]
    ok = 0
    for ep in endpoints:
        try:
            if "superfeedr" in ep:
                r = requests.post(ep, data={
                    "hub.mode": "publish",
                    "hub.url": rss_url,
                }, timeout=8)
            else:
                r = requests.get(ep, timeout=8)
            if r.status_code in (200, 202, 204):
                ok += 1
        except Exception:
            pass
    print(f"[SEO] Aggregator submissions: {ok}/{len(endpoints)} accepted")


def generate_indexnow_key_file(key):
    """
    Print the content to upload as /{key}.txt to verify ownership.
    Only needs to be done once.
    """
    print(f"Upload this file to https://indiabbcnews.com/{key}.txt")
    print(f"File content: {key}")
