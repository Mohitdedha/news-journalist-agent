"""
Social media auto-posting for IndiaBBCNews.
Posts to Facebook Page, Instagram (via instagrapi), Twitter/X, and Telegram.

Secrets needed in GitHub (all optional — skipped if not set):
  FB_PAGE_ID               — Facebook Page numeric ID
  FB_PAGE_ACCESS_TOKEN     — Long-lived Page Access Token
  IG_USERNAME              — Instagram username (e.g. indiabbcnews2026)
  IG_PASSWORD              — Instagram password
  TWITTER_API_KEY          — Twitter API Key
  TWITTER_API_SECRET       — Twitter API Secret
  TWITTER_ACCESS_TOKEN     — Twitter Access Token
  TWITTER_ACCESS_SECRET    — Twitter Access Token Secret
  TELEGRAM_BOT_TOKEN       — Telegram Bot Token (from @BotFather)
  TELEGRAM_CHANNEL_ID      — Telegram Channel username e.g. @indiabbcnews or -100xxx
"""
import os
import time
import requests

# ── Credentials (from environment / GitHub Secrets) ─────────────────────────
FB_PAGE_ID           = os.environ.get("FB_PAGE_ID", "")
FB_PAGE_ACCESS_TOKEN = os.environ.get("FB_PAGE_ACCESS_TOKEN", "")
IG_USERNAME          = os.environ.get("IG_USERNAME", "")
IG_PASSWORD          = os.environ.get("IG_PASSWORD", "")
TWITTER_API_KEY      = os.environ.get("TWITTER_API_KEY", "")
TWITTER_API_SECRET   = os.environ.get("TWITTER_API_SECRET", "")
TWITTER_ACCESS_TOKEN = os.environ.get("TWITTER_ACCESS_TOKEN", "")
TWITTER_ACCESS_SECRET= os.environ.get("TWITTER_ACCESS_SECRET", "")
TELEGRAM_BOT_TOKEN   = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHANNEL_ID  = os.environ.get("TELEGRAM_CHANNEL_ID", "")

GRAPH_API = "https://graph.facebook.com/v19.0"


# ── Helpers ──────────────────────────────────────────────────────────────────

def _truncate(text, max_len):
    return text if len(text) <= max_len else text[:max_len - 3] + "..."


def _make_caption(headline, meta_description, post_url, tags, platform="generic"):
    """Build platform-appropriate caption."""
    hashtags = " ".join(f"#{t.replace(' ','')}" for t in (tags or [])[:5])
    if platform == "twitter":
        # Twitter: 280 chars max
        base = f"{headline}\n\n{post_url}"
        if len(base) + len(hashtags) + 2 <= 280:
            return f"{base}\n\n{hashtags}"
        return _truncate(base, 280)
    elif platform == "telegram":
        return (
            f"<b>{headline}</b>\n\n"
            f"{meta_description}\n\n"
            f'<a href="{post_url}">Read full article →</a>\n\n'
            f"{hashtags}"
        )
    else:
        # Facebook / Instagram / LinkedIn
        return (
            f"{headline}\n\n"
            f"{meta_description}\n\n"
            f"Read more: {post_url}\n\n"
            f"{hashtags}"
        )


# ── Facebook Page ────────────────────────────────────────────────────────────

def post_facebook(headline, meta_description, post_url, image_url, tags):
    if not FB_PAGE_ID or not FB_PAGE_ACCESS_TOKEN:
        print("[SOCIAL] Facebook: credentials not set — skipping")
        return False
    try:
        caption = _make_caption(headline, meta_description, post_url, tags, "facebook")
        # If we have an image URL, post as photo (more reach than link post)
        if image_url:
            resp = requests.post(
                f"{GRAPH_API}/{FB_PAGE_ID}/photos",
                data={
                    "url": image_url,
                    "message": caption,
                    "access_token": FB_PAGE_ACCESS_TOKEN,
                },
                timeout=20
            )
        else:
            resp = requests.post(
                f"{GRAPH_API}/{FB_PAGE_ID}/feed",
                data={
                    "message": caption,
                    "link": post_url,
                    "access_token": FB_PAGE_ACCESS_TOKEN,
                },
                timeout=20
            )
        resp.raise_for_status()
        post_id = resp.json().get("id", "?")
        print(f"[SOCIAL] Facebook posted: {post_id}")
        return True
    except Exception as e:
        print(f"[WARN] Facebook post failed: {e}")
        return False


# ── Instagram (via instagrapi — no Facebook token needed) ────────────────────

def post_instagram(headline, meta_description, post_url, image_url, tags):
    if not IG_USERNAME or not IG_PASSWORD:
        print("[SOCIAL] Instagram: IG_USERNAME/IG_PASSWORD not set — skipping")
        return False
    if not image_url:
        print("[SOCIAL] Instagram: no image URL — skipping (image required)")
        return False
    try:
        from instagrapi import Client
        import io
        import tempfile

        caption = _make_caption(headline, meta_description, post_url, tags, "instagram")

        # Download the image
        img_resp = requests.get(image_url, timeout=15)
        img_resp.raise_for_status()

        # Save to temp file (instagrapi needs a file path)
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            tmp.write(img_resp.content)
            tmp_path = tmp.name

        # Login and post
        cl = Client()
        cl.login(IG_USERNAME, IG_PASSWORD)
        media = cl.photo_upload(tmp_path, caption=caption)
        print(f"[SOCIAL] Instagram posted: {media.pk}")

        # Cleanup
        import os as _os
        _os.unlink(tmp_path)
        return True

    except ImportError:
        print("[WARN] Instagram: instagrapi not installed — skipping")
        return False
    except Exception as e:
        print(f"[WARN] Instagram post failed: {e}")
        return False


# ── Twitter / X ──────────────────────────────────────────────────────────────

def post_twitter(headline, meta_description, post_url, image_url, tags):
    if not all([TWITTER_API_KEY, TWITTER_API_SECRET, TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_SECRET]):
        print("[SOCIAL] Twitter: credentials not set — skipping")
        return False
    try:
        from requests_oauthlib import OAuth1
        auth = OAuth1(TWITTER_API_KEY, TWITTER_API_SECRET,
                      TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_SECRET)

        media_id = None
        # Upload image if available
        if image_url:
            try:
                img_resp = requests.get(image_url, timeout=15)
                img_resp.raise_for_status()
                upload = requests.post(
                    "https://upload.twitter.com/1.1/media/upload.json",
                    auth=auth,
                    files={"media": img_resp.content},
                    timeout=30
                )
                upload.raise_for_status()
                media_id = upload.json().get("media_id_string")
            except Exception as e:
                print(f"[WARN] Twitter image upload failed: {e}")

        tweet_text = _make_caption(headline, meta_description, post_url, tags, "twitter")
        payload = {"text": tweet_text}
        if media_id:
            payload["media"] = {"media_ids": [media_id]}

        resp = requests.post(
            "https://api.twitter.com/2/tweets",
            auth=auth,
            json=payload,
            timeout=20
        )
        resp.raise_for_status()
        tweet_id = resp.json().get("data", {}).get("id", "?")
        print(f"[SOCIAL] Twitter posted: {tweet_id}")
        return True
    except ImportError:
        print("[WARN] Twitter: requests_oauthlib not installed")
        return False
    except Exception as e:
        print(f"[WARN] Twitter post failed: {e}")
        return False


# ── Telegram ─────────────────────────────────────────────────────────────────

def post_telegram(headline, meta_description, post_url, image_url, tags):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHANNEL_ID:
        print("[SOCIAL] Telegram: credentials not set — skipping")
        return False
    try:
        caption = _make_caption(headline, meta_description, post_url, tags, "telegram")
        if image_url:
            resp = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto",
                data={
                    "chat_id": TELEGRAM_CHANNEL_ID,
                    "photo": image_url,
                    "caption": caption,
                    "parse_mode": "HTML",
                },
                timeout=20
            )
        else:
            resp = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                data={
                    "chat_id": TELEGRAM_CHANNEL_ID,
                    "text": caption,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": False,
                },
                timeout=20
            )
        resp.raise_for_status()
        print(f"[SOCIAL] Telegram posted: message_id={resp.json().get('result',{}).get('message_id','?')}")
        return True
    except Exception as e:
        print(f"[WARN] Telegram post failed: {e}")
        return False


# ── Main entry point ─────────────────────────────────────────────────────────

def post_to_all(article, post_url, image_url=None):
    """
    Post article to all configured social platforms.
    Called after WordPress publish. Skips any platform missing credentials.
    """
    headline    = article.get("headline", "")
    meta_desc   = article.get("meta_description", "")
    tags        = article.get("tags", [])

    results = {}
    results["facebook"]  = post_facebook(headline, meta_desc, post_url, image_url, tags)
    results["instagram"] = post_instagram(headline, meta_desc, post_url, image_url, tags)
    results["twitter"]   = post_twitter(headline, meta_desc, post_url, image_url, tags)
    results["telegram"]  = post_telegram(headline, meta_desc, post_url, image_url, tags)

    ok  = [p for p, v in results.items() if v]
    skipped = [p for p, v in results.items() if not v]
    if ok:
        print(f"[SOCIAL] Posted to: {', '.join(ok)}")
    if skipped:
        print(f"[SOCIAL] Skipped (no credentials or error): {', '.join(skipped)}")
    return results
