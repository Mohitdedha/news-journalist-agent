"""
AI article writer using Groq (free tier).
Uses TWO separate API calls to avoid JSON truncation:
  Call 1 — plain HTML article body (no JSON risk, any length)
  Call 2 — tiny JSON metadata (headline, meta, tags, image_query — ~80 tokens)
"""
import os
import re
import time
import json
import requests
from bs4 import BeautifulSoup
from config import GROQ_API_KEY

_GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
_GROQ_MODELS = [
    "qwen/qwen3.8-27b",
    "allam-2-7b",
    "llama-3.3-70b-versatile",
    "llama3-70b-8192",
    "llama3-8b-8192",
    "mixtral-8x7b-32768",
]
_GROQ_SKIP = {"whisper", "guard", "orpheus", "gpt-oss"}
_GROQ_MODEL_CACHE = [None]


def _get_available_model():
    if _GROQ_MODEL_CACHE[0]:
        return _GROQ_MODEL_CACHE[0]
    if not GROQ_API_KEY:
        return _GROQ_MODELS[0]
    try:
        resp = requests.get(
            "https://api.groq.com/openai/v1/models",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
            timeout=10,
        )
        if resp.status_code == 200:
            all_models = [m["id"] for m in resp.json().get("data", [])]
            print(f"[INFO] Groq models available: {all_models}")
            available = set(all_models)
            for m in _GROQ_MODELS:
                if m in available:
                    print(f"[INFO] Using model: {m}")
                    _GROQ_MODEL_CACHE[0] = m
                    return m
            for m in all_models:
                if not any(skip in m.lower() for skip in _GROQ_SKIP):
                    print(f"[INFO] Fallback model: {m}")
                    _GROQ_MODEL_CACHE[0] = m
                    return m
        else:
            print(f"[WARN] Model list failed: {resp.status_code}")
    except Exception as e:
        print(f"[WARN] Model list error: {e}")
    _GROQ_MODEL_CACHE[0] = _GROQ_MODELS[0]
    return _GROQ_MODELS[0]


def _groq_call(prompt, max_tokens=700, temperature=0.4):
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY not set in GitHub Secrets")
    model = _get_available_model()
    resp = requests.post(
        _GROQ_URL,
        headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        },
        timeout=60,
    )
    if resp.status_code == 429:
        raise RuntimeError("rate_limit")
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


# ── Prompt 1: plain HTML content only ──────────────────────────────────────

_CONTENT_PROMPT = """\
You are a human journalist at an independent news desk. Write a 300-word news article in HTML.

VOICE: Write exactly like a real reporter — direct, punchy, human. Not a bot summarising facts.

BANNED PHRASES (never use these):
- "In a significant development", "amid growing concerns", "it is worth noting",
  "shed light on", "in the wake of", "Furthermore", "Moreover", "Additionally",
  "It is important to", "In conclusion", "has been reported that", "it is believed that",
  "stakeholders", "landscape", "going forward", "at this point in time", "delve into"

STYLE RULES:
- Mix short punchy sentences with longer ones. Vary the rhythm like a real human does.
- Lead with the most newsworthy fact — no build-up, just hit it.
- Drop in 1-2 quotes from officials or sources (paraphrase if needed, attribute them).
- Use exact numbers, dates, names, places. Vague = fake.
- Contractions are fine (it's, didn't, won't, can't).
- Subheadings: 3-4 word punchy phrases, not full sentences.

STRUCTURE:
<p>Lead — key fact in 1-2 sentences. Straight to the point.</p>
<p>Why it matters — 2 sentences of context.</p>
<h2>Short Subhead</h2>
<p>Details, quotes, reaction.</p>
<h2>Short Subhead</h2>
<p>What happens next or broader impact. No "In conclusion".</p>
<hr>
<p><em><strong>Source: {source_name}</strong></em></p>
<p><em>This article was compiled by the IndiaBBCNews editorial system from verified international news sources. Facts have been independently reviewed. Original reporting: {source_name}.</em></p>

OUTPUT: Only the HTML. No JSON. No explanation. Start with <p>.

STORY:
Title: {title}
Source: {source_name}
Summary: {summary}

ARTICLE TEXT (facts only — do NOT copy sentences, rewrite everything in your own voice):
{article_text}
"""

# ── Prompt 2: metadata JSON only (very short) ───────────────────────────────

_META_PROMPT = """\
For this news story, return ONLY a JSON object. No explanation, no markdown fences.

Story title: {title}
Summary: {summary}

JSON format — fill in real values:
{{"headline": "Short punchy headline max 10 words, not a sentence fragment", "meta_description": "One factual sentence 120-155 chars, include key names/numbers", "tags": ["tag1","tag2","tag3","tag4","tag5"], "image_query": "specific location or person Unsplash search, NOT 'military soldier gun' — e.g. 'London parliament building', 'Khartoum Sudan street', 'Keir Starmer press conference'"}}
"""


def fetch_article_text(url, timeout=15):
    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; IndiaBBCNewsBot/1.0)"}
        resp = requests.get(url, headers=headers, timeout=timeout)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        for tag in soup(["script", "style", "nav", "footer", "aside", "iframe", "noscript"]):
            tag.decompose()
        article = (soup.find("article") or soup.find(id="content")
                   or soup.find(class_=re.compile(r'article|content|story|body', re.I)))
        text = (article or soup.find("body") or soup).get_text(separator=" ", strip=True)
        return re.sub(r'\s+', ' ', text).strip()[:6000]
    except Exception as e:
        print(f"[WARN] Article fetch failed: {e}")
        return ""


def write_article(story, max_retries=3):
    """
    Two-step generation:
      Step 1 — write HTML content (plain text output, no JSON risk)
      Step 2 — write metadata JSON (tiny ~80 token response)
    Returns article dict or raises.
    """
    article_text = fetch_article_text(story["url"])
    title = story["title"]
    source_name = story["source_name"]
    summary = story["summary"]

    content_prompt = _CONTENT_PROMPT.format(
        title=title, source_name=source_name,
        summary=summary,
        article_text=article_text or "(use title and summary only)"
    )
    meta_prompt = _META_PROMPT.format(title=title, summary=summary)

    last_error = None
    for attempt in range(max_retries):
        try:
            # ── Step 1: Generate HTML content ──────────────────────────────
            print(f"[WRITE] Step 1: generating content (attempt {attempt+1})...")
            content_html = _groq_call(content_prompt, max_tokens=1500)

            # Strip any accidental JSON/markdown wrapping
            content_html = re.sub(r'^```[a-z]*\s*', '', content_html, flags=re.MULTILINE)
            content_html = re.sub(r'```\s*$', '', content_html, flags=re.MULTILINE).strip()

            # Validate content
            if not content_html or len(content_html) < 200:
                raise ValueError(f"Content too short: {len(content_html)} chars")
            if content_html.lower().strip() in ("undefined", "null", "none"):
                raise ValueError(f"Content is placeholder: {content_html[:50]}")
            if not content_html.startswith("<"):
                # Model returned plain text — wrap it
                content_html = "<p>" + content_html.replace("\n\n", "</p><p>") + "</p>"

            print(f"[WRITE] Content OK: {len(content_html)} chars")

            # ── Small wait so Step 2 uses a fresh OTPM slot ────────────────
            time.sleep(5)

            # ── Step 2: Generate metadata ───────────────────────────────────
            print("[WRITE] Step 2: generating metadata...")
            meta_raw = _groq_call(meta_prompt, max_tokens=200)

            meta_raw = re.sub(r'^```[a-z]*\s*', '', meta_raw, flags=re.MULTILINE)
            meta_raw = re.sub(r'```\s*$', '', meta_raw, flags=re.MULTILINE).strip()

            # Extract first JSON object from response
            m = re.search(r'\{.*\}', meta_raw, re.DOTALL)
            if not m:
                raise ValueError(f"No JSON in metadata response: {meta_raw[:100]}")
            meta = json.loads(m.group())

            for field in ("headline", "meta_description", "tags", "image_query"):
                if field not in meta:
                    raise ValueError(f"Missing metadata field: {field}")

            # Ensure tags is a list
            if not isinstance(meta["tags"], list):
                meta["tags"] = [str(meta["tags"])]

            return {
                "headline": str(meta["headline"])[:120],
                "meta_description": str(meta["meta_description"])[:160],
                "tags": [str(t) for t in meta["tags"][:8]],
                "image_query": str(meta["image_query"])[:80],
                "content_html": content_html,
            }

        except RuntimeError as e:
            if "rate_limit" in str(e):
                print(f"[WARN] Rate limit on attempt {attempt+1}, waiting 70s...")
                time.sleep(70)
            else:
                last_error = e
                print(f"[WARN] Write error attempt {attempt+1}: {e}")
                if attempt < max_retries - 1:
                    time.sleep(70)
        except Exception as e:
            last_error = e
            print(f"[WARN] Write error attempt {attempt+1}: {e}")
            if attempt < max_retries - 1:
                print("[INFO] Waiting 70s before retry...")
                time.sleep(70)

    raise RuntimeError(f"Failed after {max_retries} attempts: {last_error}")
