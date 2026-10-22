"""
AI article writer — Groq primary, Gemini Flash fallback.
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

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
_GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"

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


def _groq_call(prompt, max_tokens=700, temperature=0.75):
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


def _gemini_call(prompt, max_tokens=700):
    """Gemini Flash fallback — free tier, high TPM limit."""
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY not set")
    resp = requests.post(
        f"{_GEMINI_URL}?key={GEMINI_API_KEY}",
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.4},
        },
        timeout=60,
    )
    if resp.status_code == 429:
        raise RuntimeError("rate_limit")
    resp.raise_for_status()
    candidates = resp.json().get("candidates", [])
    if not candidates:
        raise RuntimeError("Gemini returned no candidates")
    return candidates[0]["content"]["parts"][0]["text"].strip()


def _ai_call(prompt, max_tokens=700, label=""):
    """Try Groq first, fall back to Gemini on rate limit."""
    try:
        result = _groq_call(prompt, max_tokens=max_tokens)
        return result, "groq"
    except RuntimeError as e:
        if "rate_limit" in str(e) and GEMINI_API_KEY:
            print(f"[WARN] {label} Groq rate limited — switching to Gemini...")
            result = _gemini_call(prompt, max_tokens=max_tokens)
            return result, "gemini"
        raise


# ── Prompt 1: plain HTML content only ──────────────────────────────────────

_CONTENT_PROMPT = """\
You are a senior correspondent at a high-authority international news outlet. Your writing is unmistakably human — you vary rhythm, mix short punches with longer analysis, and never write the same way twice.

Write a 750-900 word news article in HTML. It must pass AI-content detectors and rank on Google page 1.

GOOGLE E-E-A-T (Experience, Expertise, Authoritativeness, Trustworthiness):
- Open with the single most newsworthy fact — no warm-up, no throat-clearing.
- Every figure must be exact: dates, amounts, names, official titles.
- Attribute every claim: "the ministry confirmed", "UN data shows", "officials told reporters".
- Include one forward-looking paragraph: what decision, vote, or deadline comes next.

HUMAN WRITING RULES — critical:
- Vary paragraph openings: start some with a number, some with a name, some with a short question, some with a quote, some with a subordinate clause. Never start two consecutive paragraphs the same way.
- Mix sentence lengths aggressively: some 6-word punches, some 30-word analytical sentences with sub-clauses.
- Use contractions freely: it's, didn't, won't, they've, there's, can't.
- Include one specific, unexpected detail that proves you reported this — not summarized it.
- Choose H2 headings that fit THIS story's angle. Do NOT use generic labels like "What Led Here", "Key Details", "What Happens Next" every time.

BANNED PHRASES — never use, not even once:
"In a significant development", "amid growing concerns", "shed light on", "in the wake of",
"Furthermore", "Moreover", "Additionally", "It is worth noting", "It is important to",
"In conclusion", "has been reported that", "stakeholders", "landscape", "going forward",
"delve into", "it is believed that", "a recent study", "comprehensive", "robust",
"seamlessly", "leverage", "pivotal", "multifaceted", "underscores", "at the end of the day",
"needless to say", "make no mistake", "the fact of the matter", "crucial", "imperative"

STRUCTURE:
- Lead paragraph (1-2 sentences — most newsworthy fact)
- Context paragraph (why it matters — numbers, names)
- 3-5 H2 sections with story-specific headings
- 2-3 attributed quotes or paraphrased statements throughout
- One H2 "Frequently Asked Questions" with 2 H3 questions users would actually Google
- Final line: <p><em>Source: {source_name}</em></p>

OUTPUT: Only raw HTML. No JSON, no markdown fences, no explanation. Start directly with <p>.

STORY:
Title: {title}
Source: {source_name}
Summary: {summary}

ARTICLE TEXT (facts only — rewrite entirely in your own voice, copy nothing):
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


def _groq_call_with_retry(prompt, max_tokens, label, max_retries=3, base_wait=30):
    """
    Call AI with retry loop — Groq primary, Gemini fallback on rate limit.
    Does NOT re-run a previous step on rate limit.
    """
    last_error = None
    for attempt in range(max_retries):
        try:
            result, provider = _ai_call(prompt, max_tokens=max_tokens, label=label)
            if provider == "gemini":
                print(f"[INFO] {label} served by Gemini fallback")
            return result
        except RuntimeError as e:
            if "rate_limit" in str(e):
                # Both Groq and Gemini rate limited — wait and retry
                wait = base_wait * (attempt + 1)
                print(f"[WARN] {label} all providers rate limited (attempt {attempt+1}), waiting {wait}s...")
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
