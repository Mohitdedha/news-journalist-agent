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
IG_SESSION           = os.environ.get("IG_SESSION", "")
TWITTER_API_KEY      = os.environ.get("TWITTER_API_KEY", "")
TWITTER_API_SECRET   = os.environ.get("TWITTER_API_SECRET", "")
TWITTER_ACCESS_TOKEN = os.environ.get("TWITTER_ACCESS_TOKEN", "")
TWITTER_ACCESS_SECRET= os.environ.get("TWITTER_ACCESS_SECRET", "")
TELEGRAM_BOT_TOKEN   = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHANNEL_ID  = os.environ.get("TELEGRAM_CHANNEL_ID", "")

GRAPH_API = "https://graph.facebook.com/v19.0"

REDDIT_CLIENT_ID     = os.environ.get("REDDIT_CLIENT_ID", "")
REDDIT_CLIENT_SECRET = os.environ.get("REDDIT_CLIENT_SECRET", "")
REDDIT_USERNAME      = os.environ.get("REDDIT_USERNAME", "")
REDDIT_PASSWORD      = os.environ.get("REDDIT_PASSWORD", "")

MEDIUM_TOKEN         = os.environ.get("MEDIUM_TOKEN", "")
MASTODON_TOKEN       = os.environ.get("MASTODON_TOKEN", "")
MASTODON_INSTANCE    = os.environ.get("MASTODON_INSTANCE", "mastodon.social")

# Map article tags/categories → subreddits (post to first matching one)
_TAG_SUBREDDIT_MAP = [
    ({"india", "indian", "modi", "delhi", "mumbai", "bjp", "congress"}, "india"),
    ({"technology", "tech", "ai", "artificial intelligence", "elon musk", "tesla", "spacex", "openai", "google", "apple", "microsoft"}, "technology"),
    ({"crypto", "bitcoin", "ethereum", "blockchain"}, "CryptoCurrency"),
    ({"economy", "gdp", "inflation", "imf", "world bank", "trade"}, "Economics"),
    ({"science", "climate", "health", "medicine", "nasa", "space"}, "science"),
    ({"politics", "election", "president", "prime minister", "parliament", "congress", "senate"}, "worldnews"),
    ({"war", "military", "ukraine", "russia", "israel", "conflict", "attack"}, "worldnews"),
    ({"sports", "cricket", "football", "ipl", "fifa", "olympics"}, "sports"),
]
_DEFAULT_SUBREDDIT = "worldnews"


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


# ── Instagram image branding ─────────────────────────────────────────────────

def _make_instagram_image(image_bytes, headline):
    """
    Takes raw image bytes and returns Instagram-ready branded image bytes.
    - Square crop 1080x1080
    - Dark gradient overlay at bottom
    - White headline text (truncated)
    - Red accent bar + indiabbcnews.com watermark
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
        import io

        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")

        # Center-crop to square
        w, h = img.size
        side = min(w, h)
        left = (w - side) // 2
        top = (h - side) // 2
        img = img.crop((left, top, left + side, top + side))
        img = img.resize((1080, 1080), Image.LANCZOS)

        # Dark gradient overlay (bottom 35%) using RGBA compositing
        overlay_h = int(1080 * 0.35)
        overlay_top = 1080 - overlay_h
        overlay = Image.new("RGBA", (1080, 1080), (0, 0, 0, 0))
        grad_draw = ImageDraw.Draw(overlay)
        for y in range(overlay_top, 1080):
            alpha = int(200 * (y - overlay_top) / overlay_h)
            grad_draw.line([(0, y), (1080, y)], fill=(0, 0, 0, alpha))
        img = img.convert("RGBA")
        img = Image.alpha_composite(img, overlay)
        img = img.convert("RGB")

        draw = ImageDraw.Draw(img)

        # Red accent bar at very bottom
        draw.rectangle([(0, 1040), (1080, 1080)], fill=(204, 0, 0))

        # Try to load a system font (Ubuntu runner has DejaVu)
        try:
            font_bold = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 36)
            font_url = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 28)
            font_hl = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 32)
        except Exception:
            font_bold = ImageFont.load_default()
            font_url = font_bold
            font_hl = font_bold

        # Website URL on red bar
        draw.text((540, 1060), "indiabbcnews.com", fill="white", font=font_url, anchor="mm")

        # Headline text (truncated, 2 lines max)
        hl = headline[:80] + ("…" if len(headline) > 80 else "")
        words = hl.split()
        lines = []
        current = ""
        for word in words:
            test = (current + " " + word).strip()
            if len(test) <= 38:
                current = test
            else:
                if current:
                    lines.append(current)
                current = word
            if len(lines) == 2:
                current = ""
                break
        if current:
            lines.append(current)
        lines = lines[:2]

        y_text = 970 - (len(lines) * 42)
        for line in lines:
            draw.text((40, y_text), line, fill="white", font=font_hl)
            y_text += 42

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=88)
        return buf.getvalue()
    except Exception as e:
        print(f"[WARN] Instagram image branding failed: {e} — using original")
        return image_bytes


# ── Instagram (via instagrapi — no Facebook token needed) ────────────────────

def post_instagram(headline, meta_description, post_url, image_url, tags):
    if not IG_USERNAME or (not IG_PASSWORD and not IG_SESSION):
        print("[SOCIAL] Instagram: credentials not set — skipping")
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

        # Brand the image for Instagram (square + overlay + URL)
        branded = _make_instagram_image(img_resp.content, headline)

        # Save to temp file (instagrapi needs a file path)
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            tmp.write(branded)
            tmp_path = tmp.name

        # Login using saved session (preferred) or username/password
        cl = Client()
        if IG_SESSION:
            import json as _json
            cl.set_settings(_json.loads(IG_SESSION))
            cl.login(IG_USERNAME, IG_PASSWORD)
        else:
            cl.set_settings({
                "app_version": "269.0.0.18.75",
                "android_release": "11",
                "android_version": 30,
            })
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


# ── Medium ───────────────────────────────────────────────────────────────────

def post_medium(headline, content_html, post_url, tags):
    """Cross-post article to Medium with canonical URL pointing back to site."""
    if not MEDIUM_TOKEN:
        print("[SOCIAL] Medium: token not set — skipping")
        return False
    try:
        # Get Medium user ID
        me = requests.get(
            "https://api.medium.com/v1/me",
            headers={"Authorization": f"Bearer {MEDIUM_TOKEN}"},
            timeout=10,
        )
        me.raise_for_status()
        user_id = me.json()["data"]["id"]

        payload = {
            "title": headline,
            "contentFormat": "html",
            "content": content_html,
            "canonicalUrl": post_url,
            "tags": [t[:25] for t in (tags or [])[:5]],
            "publishStatus": "public",
        }
        resp = requests.post(
            f"https://api.medium.com/v1/users/{user_id}/posts",
            headers={"Authorization": f"Bearer {MEDIUM_TOKEN}", "Content-Type": "application/json"},
            json=payload,
            timeout=20,
        )
        resp.raise_for_status()
        med_url = resp.json().get("data", {}).get("url", "?")
        print(f"[SOCIAL] Medium posted: {med_url}")
        return True
    except Exception as e:
        print(f"[WARN] Medium post failed: {e}")
        return False


# ── Mastodon ─────────────────────────────────────────────────────────────────

def post_mastodon(headline, post_url, tags):
    """Post to Mastodon — free decentralised Twitter alternative."""
    if not MASTODON_TOKEN:
        print("[SOCIAL] Mastodon: token not set — skipping")
        return False
    try:
        hashtags = " ".join(f"#{t.replace(' ','')}" for t in (tags or [])[:4])
        status = f"{headline}\n\n{post_url}\n\n{hashtags}"[:500]
        resp = requests.post(
            f"https://{MASTODON_INSTANCE}/api/v1/statuses",
            headers={"Authorization": f"Bearer {MASTODON_TOKEN}"},
            data={"status": status},
            timeout=15,
        )
        resp.raise_for_status()
        toot_url = resp.json().get("url", "?")
        print(f"[SOCIAL] Mastodon posted: {toot_url}")
        return True
    except Exception as e:
        print(f"[WARN] Mastodon post failed: {e}")
        return False


# ── Reddit ───────────────────────────────────────────────────────────────────

def _pick_subreddit(tags):
    """Return the best subreddit for the given tag list."""
    tag_set = {t.lower() for t in (tags or [])}
    for keywords, subreddit in _TAG_SUBREDDIT_MAP:
        if keywords & tag_set:
            return subreddit
    return _DEFAULT_SUBREDDIT


def post_reddit(headline, meta_description, post_url, tags):
    if not all([REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USERNAME, REDDIT_PASSWORD]):
        print("[SOCIAL] Reddit: credentials not set — skipping")
        return False
    try:
        import praw
        reddit = praw.Reddit(
            client_id=REDDIT_CLIENT_ID,
            client_secret=REDDIT_CLIENT_SECRET,
            username=REDDIT_USERNAME,
            password=REDDIT_PASSWORD,
            user_agent=f"IndiaBBCNews:v1.0 (by u/{REDDIT_USERNAME})",
        )
        subreddit_name = _pick_subreddit(tags)
        subreddit = reddit.subreddit(subreddit_name)
        submission = subreddit.submit(
            title=headline[:300],
            url=post_url,
            resubmit=False,
            nsfw=False,
        )
        print(f"[SOCIAL] Reddit posted: r/{subreddit_name} → {submission.shortlink}")
        return True
    except ImportError:
        print("[WARN] Reddit: praw not installed — skipping")
        return False
    except Exception as e:
        err = str(e).lower()
        if "already been submitted" in err or "duplicate" in err:
            print(f"[SOCIAL] Reddit: duplicate URL, skipping")
            return False
        print(f"[WARN] Reddit post failed: {e}")
        return False


# ── Main entry point ─────────────────────────────────────────────────────────

def post_to_all(article, post_url, image_url=None):
    """
    Post article to all configured social platforms.
    Called after WordPress publish. Skips any platform missing credentials.
    """
    headline     = article.get("headline", "")
    meta_desc    = article.get("meta_description", "")
    content_html = article.get("content_html", f"<p>{meta_desc}</p>")
    tags         = article.get("tags", [])

    results = {}
    results["facebook"]  = post_facebook(headline, meta_desc, post_url, image_url, tags)
    results["instagram"] = post_instagram(headline, meta_desc, post_url, image_url, tags)
    results["twitter"]   = post_twitter(headline, meta_desc, post_url, image_url, tags)
    results["telegram"]  = post_telegram(headline, meta_desc, post_url, image_url, tags)
    results["reddit"]    = post_reddit(headline, meta_desc, post_url, tags)
    results["medium"]    = post_medium(headline, content_html, post_url, tags)
    results["mastodon"]  = post_mastodon(headline, post_url, tags)

    ok  = [p for p, v in results.items() if v]
    skipped = [p for p, v in results.items() if not v]
    if ok:
        print(f"[SOCIAL] Posted to: {', '.join(ok)}")
    if skipped:
        print(f"[SOCIAL] Skipped (no credentials or error): {', '.join(skipped)}")
    return results
