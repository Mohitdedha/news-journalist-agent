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
You are a senior journalist writing for a high-authority news website. Write a 700-800 word news article in HTML that ranks on Google's first page.

GOOGLE E-E-A-T RULES (Experience, Expertise, Authoritativeness, Trustworthiness):
- Use exact numbers, dates, names, places — never vague claims.
- Attribute every claim: "according to...", "officials said", "data shows".
- Cover WHO, WHAT, WHEN, WHERE, WHY and HOW.
- Include background/context so readers understand the full story.
- End with what happens next (forward-looking paragraph).

VOICE: Write like a real senior reporter — direct, authoritative, human. Not a bot.

BANNED PHRASES (never use):
"In a significant development", "amid growing concerns", "it is worth noting",
"shed light on", "in the wake of", "Furthermore", "Moreover", "Additionally",
"It is important to", "In conclusion", "has been reported that", "stakeholders",
"landscape", "going forward", "delve into", "it is believed that"

STYLE:
- Mix short punchy sentences with longer analytical ones.
- Lead with the single most important fact — no warm-up.
- Include 2-3 quotes from officials/experts (paraphrase if needed, always attribute).
- Contractions are fine (it's, didn't, won't).
- H2 subheadings: 3-5 words, punchy, not full sentences.
- H3 for sub-points within sections.

STRUCTURE (follow exactly):
<p>[Lead — single most newsworthy fact, 1-2 sentences]</p>
<p>[Context — why this matters, 2-3 sentences with numbers/names]</p>

<h2>[Background / What Led Here]</h2>
<p>[2-3 sentences of background. Quote or attributed claim.]</p>

<h2>[Key Details]</h2>
<p>[Main facts, figures, timeline. 3-4 sentences.]</p>
<p>[Reaction or second angle. Quote from official/expert.]</p>

<h2>[Impact / What It Means]</h2>
<p>[Who is affected and how. Specific numbers if available.]</p>
<p>[Broader regional or global implications.]</p>

<h2>[What Happens Next]</h2>
<p>[Upcoming dates, decisions, or events to watch. 2-3 sentences.]</p>

<h2>Frequently Asked Questions</h2>
<h3>[Question directly related to the story — phrased as a user would search it]</h3>
<p>[Clear 2-sentence answer.]</p>
<h3>[Second question users would ask about this topic]</h3>
<p>[Clear 2-sentence answer.]</p>

<p><em>Source: {source_name}</em></p>

OUTPUT: Only the HTML. No JSON, no markdown fences, no explanation. Start with <p>.

STORY:
Title: {title}
Source: {source_name}
Summary: {summary}

ARTICLE TEXT (use as facts only — rewrite everything in your own voice, do NOT copy sentences):
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


def _groq_call_with_retry(prompt, max_tokens, label, max_retries=4, base_wait=30):
    """Call Groq with its own retry loop — does NOT re-run a previous step on rate limit."""
    last_error = None
    for attempt in range(max_retries):
        try:
            return _groq_call(prompt, max_tokens=max_tokens)
        except RuntimeError as e:
            if "rate_limit" in str(e):
                wait = base_wait * (attempt + 1)  # 30s, 60s, 90s, 120s
                print(f"[WARN] {label} rate limited (attempt {attempt+1}), waiting {wait}s...")
                time.sleep(wait)
            else:
                raise
        except Exception as e:
            last_error = e
            print(f"[WARN] {label} error attempt {attempt+1}: {e}")
            if attempt < max_retries - 1:
                time.sleep(30)
            else:
                raise RuntimeError(f"{label} failed after {max_retries} attempts: {last_error}")
    raise RuntimeError(f"{label} rate-limited after {max_retries} attempts")


def write_article(story, max_retries=3):
    """
    Two-step generation:
      Step 1 — write HTML content (plain text output, no JSON risk)
      Step 2 — write metadata JSON (tiny ~80 token response)
    Each step has its own retry loop so a Step 2 rate limit doesn't re-run Step 1.
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

    # ── Step 1: Generate HTML content (own retry loop) ──────────────────
    print("[WRITE] Step 1: generating content...")
    content_html = _groq_call_with_retry(content_prompt, max_tokens=2500, label="Step1-content", base_wait=60)

    # Strip any accidental JSON/markdown wrapping
    content_html = re.sub(r'^```[a-z]*\s*', '', content_html, flags=re.MULTILINE)
    content_html = re.sub(r'```\s*$', '', content_html, flags=re.MULTILINE).strip()

    # Validate content
    if not content_html or len(content_html) < 200:
        raise ValueError(f"Content too short: {len(content_html)} chars")
    text_only = re.sub(r'<[^>]+>', '', content_html).strip().lower()
    if text_only in ("undefined", "null", "none", "") or len(text_only) < 150:
        raise ValueError(f"Content is placeholder/empty: '{text_only[:60]}'")
    if not content_html.startswith("<"):
        content_html = "<p>" + content_html.replace("\n\n", "</p><p>") + "</p>"

    print(f"[WRITE] Content OK: {len(content_html)} chars")

    # ── Wait between Step 1 and Step 2 so TPM window resets ────────────
    time.sleep(30)

    # ── Step 2: Generate metadata (own retry loop, shorter waits) ───────
    print("[WRITE] Step 2: generating metadata...")
    meta_raw = _groq_call_with_retry(meta_prompt, max_tokens=200, label="Step2-meta", base_wait=30)

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

    if not isinstance(meta["tags"], list):
        meta["tags"] = [str(meta["tags"])]

    return {
        "headline": str(meta["headline"])[:120],
        "meta_description": str(meta["meta_description"])[:160],
        "tags": [str(t) for t in meta["tags"][:8]],
        "image_query": str(meta["image_query"])[:80],
        "content_html": content_html,
    }
