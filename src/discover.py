"""
Discover fresh news stories from RSS feeds.
Returns stories not seen in history, sorted by recency.
"""
import feedparser
import hashlib
import re
import time
from datetime import datetime, timezone, timedelta
from difflib import SequenceMatcher
from urllib.parse import urlparse
import requests
from config import load_sources, load_history

MAX_AGE_HOURS = 24


def normalize_url(url):
    """Canonical form for duplicate-URL checking."""
    parsed = urlparse(url)
    return f"{parsed.netloc}{parsed.path}".lower().rstrip("/")


def title_similarity(a, b):
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def content_fingerprint(text):
    clean = re.sub(r'\s+', ' ', text or "").strip().lower()
    return hashlib.md5(clean[:500].encode()).hexdigest()


def parse_date(entry):
    """Return aware datetime or None."""
    for attr in ("published_parsed", "updated_parsed"):
        t = getattr(entry, attr, None)
        if t:
            try:
                return datetime(*t[:6], tzinfo=timezone.utc)
            except Exception:
                pass
    return None


def is_fresh(entry, max_age_hours=MAX_AGE_HOURS):
    dt = parse_date(entry)
    if dt is None:
        return True  # accept if date unknown
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    return dt >= cutoff


def fetch_feed(source):
    """Fetch one RSS feed with timeout and UA."""
    try:
        feed = feedparser.parse(
            source["url"],
            agent="IndiaBBCNews/1.0 (newsroom bot; +https://indiabbcnews.com)",
            request_headers={"Accept": "application/rss+xml, application/xml, text/xml"}
        )
        return feed.entries
    except Exception as e:
        print(f"[WARN] Feed error {source['name']}: {e}")
        return []


def fetch_google_trends_stories(geo="IN", max_stories=5):
    """
    Fetch trending topics from Google Trends daily RSS.
    Returns story candidates from trending searches.
    """
    url = f"https://trends.google.com/trends/trendingsearches/daily/rss?geo={geo}"
    stories = []
    try:
        feed = feedparser.parse(
            url,
            agent="IndiaBBCNews/1.0 (newsroom bot; +https://indiabbcnews.com)",
        )
        for entry in feed.entries[:max_stories]:
            title = getattr(entry, "title", "").strip()
            if not title or len(title) < 5:
                continue
            # Google Trends entries have news articles in description
            summary = getattr(entry, "summary", "") or ""
            summary = re.sub(r'<[^>]+>', '', summary).strip()
            link = getattr(entry, "link", "") or f"https://www.google.com/search?q={title.replace(' ', '+')}&tbm=nws"

            stories.append({
                "url": link,
                "norm_url": normalize_url(link) + f"_trends_{hashlib.md5(title.encode()).hexdigest()[:8]}",
                "title": f"Breaking: {title}",
                "summary": summary[:500] or f"Trending topic in India: {title}. Latest news and updates.",
                "source_name": "Google Trends India",
                "source_category": "global",
                "wp_category_id": 1,
                "published": datetime.now(timezone.utc).isoformat(),
                "fingerprint": content_fingerprint(title),
                "image_query": title,
            })
        print(f"[TRENDS] Found {len(stories)} trending topics from Google Trends ({geo})")
    except Exception as e:
        print(f"[WARN] Google Trends fetch error: {e}")
    return stories


def discover_stories(max_per_run=10):
    """Return fresh, non-duplicate candidate stories."""
    sources_cfg = load_sources()
    history = load_history()

    seen_urls = set(history.get("published_urls", []) + history.get("skipped_urls", []))
    seen_titles = list(history.get("published_titles", []))

    candidates = []

    # Add Google Trends stories from India + US + UK
    for geo, label in [("IN", "India"), ("US", "US"), ("GB", "UK")]:
        trend_stories = fetch_google_trends_stories(geo=geo, max_stories=2)
        for ts in trend_stories:
            ts["summary"] = ts["summary"].replace(f"Trending topic in India: ", f"Trending in {label}: ")
            ts["source_name"] = f"Google Trends {label}"
            norm = ts["norm_url"]
            too_similar = any(title_similarity(ts["title"], t) > 0.65 for t in seen_titles[-200:])
            if norm not in seen_urls and not too_similar:
                candidates.append(ts)

    for source in sources_cfg["rss_feeds"]:
        entries = fetch_feed(source)
        for entry in entries:
            url = getattr(entry, "link", None)
            if not url:
                continue

            norm_url = normalize_url(url)
            if norm_url in seen_urls:
                continue

            if not is_fresh(entry):
                continue

            title = getattr(entry, "title", "").strip()
            if not title or len(title) < 10:
                continue

            # Title similarity check against recent published titles
            too_similar = any(
                title_similarity(title, t) > 0.72 for t in seen_titles[-200:]
            )
            if too_similar:
                continue

            summary = getattr(entry, "summary", "") or getattr(entry, "description", "") or ""
            # Strip HTML tags from summary
            summary = re.sub(r'<[^>]+>', '', summary).strip()

            candidates.append({
                "url": url,
                "norm_url": norm_url,
                "title": title,
                "summary": summary[:500],
                "source_name": source["name"],
                "source_category": source["category"],
                "wp_category_id": source["wp_category_id"],
                "published": parse_date(entry).isoformat() if parse_date(entry) else None,
                "fingerprint": content_fingerprint(summary),
            })

        time.sleep(0.5)  # polite delay between feeds

    # Dedupe within batch by fingerprint
    seen_fp = set()
    unique = []
    for c in candidates:
        if c["fingerprint"] not in seen_fp:
            seen_fp.add(c["fingerprint"])
            unique.append(c)

    # Sort by date (newest first) and cap
    unique.sort(key=lambda x: x.get("published") or "", reverse=True)
    return unique[:max_per_run]
