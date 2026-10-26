"""
Main newsroom orchestrator.
Called by GitHub Actions on a cron schedule.
"""
import re
import sys
import os
import time
import traceback

# Add src dir to path
sys.path.insert(0, os.path.dirname(__file__))

from config import load_sources, load_history, save_history
from discover import discover_stories
from writer import write_article
from images import find_and_process_image, upload_to_wordpress, init_used_photos, save_used_photos
from publisher import create_post, check_duplicate_in_wp, test_connection
from seo import submit_indexnow, ping_sitemap, ping_rpc_services, submit_to_aggregators, submit_to_google_indexing
from monitor import log_run_summary, alert_wordpress_down, alert_ai_quota
from social import post_to_all
from linker import add_internal_links

PUBLISH_STATUS = os.environ.get("PUBLISH_STATUS", "draft")  # override per run
MAX_STORIES = int(os.environ.get("MAX_STORIES", "2"))

# Keyword → wp_category_id mapping (checked against headline + content)
_CATEGORY_KEYWORDS = [
    ({"ipl", "cricket", "virat", "rohit", "dhoni", "bcci", "test match", "odi", "t20", "world cup cricket",
      "sachin", "kohli", "bumrah", "shami", "icc", "cricinfo", "cricbuzz"}, 29),           # Cricket
    ({"football", "fifa", "premier league", "la liga", "champions league", "nfl", "nba",
      "olympics", "commonwealth games", "asian games", "hockey", "badminton", "tennis",
      "formula 1", "f1", "wrestling", "boxing", "athletics", "chess olympiad"}, 34),       # Sports
    ({"modi", "bjp", "congress", "rahul gandhi", "parliament", "lok sabha", "rajya sabha",
      "election", "cm ", "chief minister", "governor", "india government", "indian politics",
      "delhi", "mumbai", "kashmir", "gujarat", "maharashtra", "rajasthan", "uttar pradesh",
      "bihar", "bengal", "tamil", "kerala", "telangana", "andhra", "karnataka", "punjab",
      "aap ", "trinamool", "shiv sena", "nda ", "upa ", "cbi", "ed ", "supreme court india",
      "high court india", "india flood", "india earthquake", "india fire"}, 211),           # India
    ({"ai ", "artificial intelligence", "chatgpt", "openai", "google gemini", "meta llama",
      "iphone", "android", "samsung", "apple ", "microsoft", "tesla", "spacex", "elon musk",
      "startup", "app ", "software", "cybersecurity", "hack", "data breach", "5g", "semiconductor",
      "chip", "nvidia", "amazon aws", "cloud computing", "robot", "automation", "tech "}, 33),  # Technology
    ({"gdp", "inflation", "rbi", "reserve bank", "interest rate", "stock market", "sensex",
      "nifty", "rupee", "dollar", "budget", "tax", "gst", "imf", "world bank", "recession",
      "economic", "economy", "finance minister", "sebi", "ipo ", "mutual fund"}, 12),      # Economy
    ({"uk ", "britain", "london", "scotland", "wales", "ireland", "eu ", "europe", "france",
      "germany", "italy", "spain", "nato", "european union", "brexit"}, 31),               # Europe-UK
    ({"bollywood", "hollywood", "actor", "actress", "film", "movie", "series", "ott",
      "netflix", "amazon prime", "disney", "celebrity", "award", "oscar", "filmfare",
      "music", "album", "singer", "concert", "fashion", "model"}, 189),                    # Entertainment
    ({"nasa", "space", "mars", "moon", "asteroid", "climate change", "global warming",
      "vaccine", "virus", "cancer", "research", "discovery", "scientist", "biology",
      "physics", "chemistry", "environment", "pollution", "solar"}, 35),                   # Science
    ({"school", "college", "university", "student", "exam", "board exam", "neet", "jee",
      "upsc", "ssc", "scholarship", "education policy", "cbse", "icse"}, 14),              # Education
    ({"health", "hospital", "doctor", "medicine", "diet", "fitness", "yoga", "mental health",
      "disease", "treatment", "surgery", "nutrition", "wellness"}, 18),                    # Lifestyle
    ({"business", "company", "corporate", "merger", "acquisition", "startup funding",
      "revenue", "profit", "loss", "ceo", "chairman", "board of directors"}, 193),        # Business
]

_WP_CAT_NAMES = {
    29: "Cricket", 34: "Sports", 211: "India", 33: "Technology",
    12: "Economy", 31: "Europe-UK", 189: "Entertainment", 35: "Science",
    14: "Education", 18: "Lifestyle", 193: "Business", 206: "Global"
}


def detect_category(headline, content_text="", fallback_id=206):
    """
    Scan headline + first 500 chars of content for keywords.
    Returns the best-matching wp_category_id, or fallback_id if no match.
    Priority: whichever category gets the most keyword hits wins.
    """
    text = (headline + " " + content_text[:500]).lower()
    scores = {}
    for keywords, cat_id in _CATEGORY_KEYWORDS:
        hits = sum(1 for kw in keywords if kw in text)
        if hits:
            scores[cat_id] = scores.get(cat_id, 0) + hits
    if scores:
        best = max(scores, key=scores.get)
        return best
    return fallback_id


def run():
    print("[START] News Journalist Agent")

    # 1. Verify WordPress connection
    if not test_connection():
        alert_wordpress_down("Could not authenticate with WordPress REST API")
        sys.exit(1)

    # 2. Discover stories
    print(f"\n[DISCOVER] Fetching stories (max={MAX_STORIES})...")
    stories = discover_stories(max_per_run=MAX_STORIES)
    print(f"[DISCOVER] Found {len(stories)} candidate stories")

    if not stories:
        print("[INFO] No new stories to process. Exiting.")
        log_run_summary(0, 0, 0, [])
        return

    history = load_history()
    init_used_photos(history)  # load used photo IDs from previous runs
    published_count = 0
    skipped_count = 0
    errors = []
    new_post_urls = []

    from difflib import SequenceMatcher

    def _title_seen_in_history(title, published_titles):
        """Check if a similar title was already published in a previous run."""
        stop = {"the","a","an","of","in","on","at","to","for","is","are","was","were",
                "and","or","but","with","from","by","as","its","it","this","that","s"}
        words_new = set(w.strip("'\",.!?").lower() for w in title.split()
                        if w.lower() not in stop and len(w) > 2)
        for past in published_titles[-200:]:  # only check recent 200
            sim = SequenceMatcher(None, title.lower(), past.lower()).ratio()
            words_past = set(w.strip("'\",.!?").lower() for w in past.split()
                             if w.lower() not in stop and len(w) > 2)
            kw = len(words_new & words_past) / min(len(words_new), len(words_past)) if words_new and words_past else 0
            if sim >= 0.72 or kw >= 0.70:
                print(f"[SKIP] Duplicate in history: '{past[:60]}' (sim={sim:.2f}, kw={kw:.2f})")
                return True
        return False

    for i, story in enumerate(stories):
        print(f"\n[STORY {i+1}/{len(stories)}] {story['title'][:80]}")

        try:
            # 3a. Check history (previous runs)
            if _title_seen_in_history(story["title"], history.get("published_titles", [])):
                print(f"[SKIP] Duplicate topic in history: {story['title'][:60]}")
                history["skipped_urls"].append(story["norm_url"])
                history["skipped_urls"] = history["skipped_urls"][-2000:]
                skipped_count += 1
                continue

            # 3b. Final duplicate check against live WordPress
            if check_duplicate_in_wp(story["title"]):
                print(f"[SKIP] Duplicate in WordPress: {story['title'][:60]}")
                history["skipped_urls"].append(story["norm_url"])
                history["skipped_urls"] = history["skipped_urls"][-2000:]
                skipped_count += 1
                continue

            # 4. Write article with AI
            print("[WRITE] Generating article with Groq...")
            try:
                article = write_article(story)
                article["source_name"] = story["source_name"]
            except Exception as e:
                err = f"Writer failed for '{story['title'][:50]}': {e}"
                print(f"[ERROR] {err}")
                errors.append(err)
                if "quota" in str(e).lower():
                    alert_ai_quota(e)
                    break  # hard quota exceeded — stop
                if "rate" in str(e).lower():
                    print("[WAIT] Rate limit hit — waiting 90s before next story...")
                    time.sleep(90)
                continue

            # 4a. Guard: skip blank/too-short content (check TEXT not HTML)
            raw_text = re.sub(r'<[^>]+>', '', article.get("content_html", "")).strip()
            content_len = len(raw_text)
            if content_len < 600:
                print(f"[SKIP] Content text too short ({content_len} chars) — not publishing")
                skipped_count += 1
                continue
            # Catch "undefined" even when surrounded by HTML wrappers
            if raw_text.lower().startswith("undefined") or raw_text.strip().lower() == "undefined":
                print(f"[SKIP] Content is 'undefined' placeholder — not publishing")
                skipped_count += 1
                continue

            # 4b. Add internal links to related articles
            print("[LINK] Adding internal links...")
            article["content_html"] = add_internal_links(
                article["content_html"], article["headline"], max_links=3
            )

            # 5. Find and process image
            print("[IMAGE] Searching for relevant image...")
            img_bytes, alt_text, caption = find_and_process_image(
                image_query=article.get("image_query", story["title"]),
                headline=article["headline"],
                context=article.get("meta_description", ""),
                history=history,
                category=story.get("category", "global"),
            )

            # Guard: no fresh unique image → skip rather than post with bad/repeated image
            if not img_bytes:
                print(f"[SKIP] No fresh unique image found — skipping story to avoid blank/repeat image")
                skipped_count += 1
                continue

            slug = story["title"].lower()[:40].replace(" ", "-")
            slug = "".join(c for c in slug if c.isalnum() or c == "-")
            filename = f"{slug}.jpg"
            featured_media_id, featured_media_url = upload_to_wordpress(
                img_bytes, filename, alt_text or article["headline"], caption or ""
            )
            if not featured_media_id:
                print(f"[SKIP] Image upload failed — skipping story")
                skipped_count += 1
                continue
            print(f"[OK] Image uploaded: media_id={featured_media_id}")

            # 6. Publish to WordPress
            # Detect category from article content (overrides RSS source category)
            content_plain = re.sub(r'<[^>]+>', ' ', article.get("content_html", ""))
            detected_cat_id = detect_category(
                article["headline"],
                content_text=content_plain,
                fallback_id=story["wp_category_id"],
            )
            print(f"[CATEGORY] {_WP_CAT_NAMES.get(detected_cat_id, detected_cat_id)} (id={detected_cat_id})")
            print(f"[PUBLISH] Creating post as '{PUBLISH_STATUS}'...")
            post_id, post_url = create_post(
                article=article,
                wp_category_id=detected_cat_id,
                featured_media_id=featured_media_id,
                publish_status=PUBLISH_STATUS
            )

            # 7. Record in history
            history["published_urls"].append(story["norm_url"])
            history["published_urls"] = history["published_urls"][-5000:]
            history["published_titles"].append(article["headline"])
            history["published_titles"] = history["published_titles"][-1000:]
            save_used_photos(history)  # persist used photo IDs
            save_history(history)

            # 8. Social media posting + RPC backlink pings
            if PUBLISH_STATUS == "publish" and post_url:
                print("[SOCIAL] Posting to social media...")
                # Every 4th published article gets a video post (Reel/FB video)
                # Also video for breaking/trending stories
                _tags_lower = {t.lower() for t in article.get("tags", [])}
                _is_trending = bool(_tags_lower & {"breaking", "viral", "exclusive", "urgent", "crisis"})
                _post_video = (published_count % 4 == 0) or _is_trending
                if _post_video:
                    print("[SOCIAL] Video post selected for this article")
                post_to_all(article, post_url, image_url=featured_media_url, post_video=_post_video)
                ping_rpc_services(article["headline"], post_url)
                submit_to_aggregators(post_url, article["headline"])
                submit_to_google_indexing(post_url)

            # 9. SEO discovery
            if PUBLISH_STATUS == "publish" and post_url:
                new_post_urls.append(post_url)

            published_count += 1

        except Exception as e:
            err = f"Story {i+1} failed: {str(e)[:150]}"
            print(f"[ERROR] {err}")
            traceback.print_exc()
            errors.append(err)

        # Gap between stories to let Groq TPM window recover
        if i < len(stories) - 1:
            time.sleep(30)

    # 9. Batch SEO submission
    if new_post_urls:
        print(f"\n[SEO] Submitting {len(new_post_urls)} URLs to IndexNow...")
        submit_indexnow(new_post_urls)
        ping_sitemap()

    # 10. Summary
    log_run_summary(
        stories_processed=len(stories),
        stories_published=published_count,
        stories_skipped=skipped_count,
        errors=errors
    )

    if errors:
        sys.exit(1)


if __name__ == "__main__":
    run()
