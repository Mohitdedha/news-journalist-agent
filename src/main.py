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
from seo import submit_indexnow, ping_sitemap, ping_rpc_services, submit_to_aggregators
from monitor import log_run_summary, alert_wordpress_down, alert_ai_quota
from social import post_to_all
from linker import add_internal_links

PUBLISH_STATUS = os.environ.get("PUBLISH_STATUS", "draft")  # override per run
MAX_STORIES = int(os.environ.get("MAX_STORIES", "2"))


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

            # 4a. Guard: skip blank/too-short content
            content_len = len(re.sub(r'<[^>]+>', '', article.get("content_html", "")))
            if content_len < 500:
                print(f"[SKIP] Content too short ({content_len} chars) — not publishing blank post")
                skipped_count += 1
                continue

            # 4b. Add internal links to related articles
            print("[LINK] Adding internal links...")
            article["content_html"] = add_internal_links(
                article["content_html"], article["headline"]
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
            print(f"[PUBLISH] Creating post as '{PUBLISH_STATUS}'...")
            post_id, post_url = create_post(
                article=article,
                wp_category_id=story["wp_category_id"],
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
                post_to_all(article, post_url, image_url=featured_media_url)
                ping_rpc_services(article["headline"], post_url)
                submit_to_aggregators(post_url, article["headline"])

            # 9. SEO discovery
            if PUBLISH_STATUS == "publish" and post_url:
                new_post_urls.append(post_url)

            published_count += 1

        except Exception as e:
            err = f"Story {i+1} failed: {str(e)[:150]}"
            print(f"[ERROR] {err}")
            traceback.print_exc()
            errors.append(err)

        # Small gap between stories to avoid Groq burst limit
        if i < len(stories) - 1:
            time.sleep(10)

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
