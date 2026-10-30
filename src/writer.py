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
_GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-001:generateContent"

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


def _groq_call(prompt, max_tokens=700, temperature=0.92):
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
You are Priya Nair, a veteran foreign correspondent with 14 years at Reuters and BBC. You've covered wars, elections, and economic crises from the ground. Your writing is raw, direct, and unmistakably human — editors have never once flagged your copy as AI-generated.

Write a 1600-2000 word news article in HTML. Goal: 0% AI detection. Goal: Google indexes this within 48 hours.

ORIGINALITY — the #1 indexing signal:
- Do NOT just rewrite the source. Add something the source doesn't have.
- Add the INDIA ANGLE: how does this story affect Indian readers, Indian markets, Indian policy, or Indians abroad? Even if it's a global story, find the India connection. Write at least one full paragraph on this.
- Add CONTEXT the reader won't find in the original: historical background, comparison to a similar past event, what experts in this field typically say about situations like this.
- Write at least ONE original observation or implication that isn't in the source material.
- The article must be worth reading even if the reader already saw the original news. If it's not adding value, it won't be indexed.

BURSTINESS — the #1 human signal AI detectors check:
- Alternate violently between short and long sentences. Example: "The vote failed. Just like that — three years of negotiations, two collapsed governments, and one very public resignation later, the bill that was supposed to change everything died in a Tuesday afternoon session that barely made the evening news."
- Every paragraph must have at least one sentence under 8 words AND one sentence over 25 words.
- Never write 3 sentences of similar length in a row. Ever.

REAL HUMAN PATTERNS — non-negotiable:
- Start the article with a scene, a number, or a name. Never with "The" as the first word.
- Use dashes — like this — to interrupt your own thoughts mid-sentence at least twice.
- Drop one contraction every paragraph: it's, didn't, won't, they've, there's, can't, that's, we're.
- Add ONE throwaway observation only a reporter on the ground would notice.
- Write ONE sentence that starts with "And" or "But".
- Include a moment of mild editorial opinion disguised as observation: "That's a harder sell than it sounds." / "Nobody in the room looked convinced."
- Use a rhetorical question once — buried in a paragraph, never in a heading.
- Let ONE paragraph run long and breathless — 50+ words, multiple clauses.

VOCABULARY:
- Use ordinary words. "Said" not "stated". "Showed" not "demonstrated". "Tried" not "attempted".
- Use numbers as figures: 3, not three. $4.2 billion, not four-point-two billion dollars.
- When quoting: "told reporters" / "said in a statement" / "confirmed to journalists" — vary every time.

ABSOLUTE BANNED LIST — firing offence:
"In a significant development", "amid growing concerns", "shed light on", "in the wake of",
"Furthermore", "Moreover", "Additionally", "It is worth noting", "It is important to note",
"In conclusion", "has been reported", "stakeholders", "landscape", "going forward",
"delve into", "it is believed", "comprehensive", "robust", "seamlessly", "leverage",
"pivotal", "multifaceted", "underscores", "at the end of the day", "needless to say",
"make no mistake", "the fact of the matter", "crucial", "imperative", "it should be noted",
"plays a crucial role", "a wide range of", "in order to", "due to the fact that",
"with respect to", "it is essential", "one must consider", "this is not surprising"

GOOGLE E-E-A-T:
- Open with the single most newsworthy fact — no warm-up.
- Every figure exact: dates, amounts, names, official titles.
- Attribute every claim: "the ministry confirmed", "UN data shows", "officials told reporters".
- One forward-looking paragraph: what vote, deadline, or decision comes next.

STRUCTURE — follow exactly:
- H1: the article headline (only ONE h1)
- Lead paragraph (1-2 sentences — hardest fact first, no heading above it)
- 5-6 H2 sections with THIS story's specific angle as heading (never generic like "Background" or "Overview")
  - Every H2 section: EXACTLY 2 paragraphs
  - Each paragraph: 4-5 sentences
  - One of the H2 sections MUST be the India angle (e.g. "What This Means for India", "India's Response", "Impact on Indian Markets")
- 3-4 attributed quotes or paraphrased statements across sections
- One H2 "Frequently Asked Questions" with 4-5 H3 questions — write questions EXACTLY as people type them into Google search (e.g. "Why did X happen?", "What is Y?", "How does Z affect India?"), each followed by a 2-3 sentence answer
- Final line: <p><em>Source: {source_name}</em></p>

HEADING HIERARCHY RULES:
- H1: article title only, once
- H2: main section headings (5-6 total + FAQ)
- H3: only inside FAQ or genuine sub-sections under an H2
- Never use H4/H5/H6
- Never put a heading directly under another heading without a paragraph between them

OUTPUT: Only raw HTML. No markdown, no fences, no explanation. Start directly with <p>.
STOP as soon as the article and FAQ are complete. Do NOT add filler, repeated phrases, or any text after the closing </p> of the FAQ. Never write "The next is..." or similar padding. If you reach the word limit before finishing, cut a section short — never pad.

STORY:
Title: {title}
Source: {source_name}
Summary: {summary}

ARTICLE TEXT (facts only — rewrite entirely in your own voice, add India angle, add original context):
{article_text}
"""

# ── Prompt 2: metadata JSON only (very short) ───────────────────────────────

_META_PROMPT = """\
For this news story, return ONLY a JSON object. No explanation, no markdown fences.

Story title: {title}
Summary: {summary}
Category: {category}

JSON format — fill in real values:
{{"headline": "Short punchy headline max 10 words, not a sentence fragment", "meta_description": "One factual sentence 120-150 chars, include key names/numbers", "tags": ["tag1","tag2","tag3","tag4","tag5"], "image_query": "IMPORTANT rules for image_query: (1) For AUTO/CAR/BIKE stories: use 'car road driving highway', 'motorcycle bike rider', 'electric vehicle charging station', 'car showroom India', 'luxury car dealership' — pick the most specific option for the story. (2) For SPORTS: use the sport name + action e.g. 'cricket match stadium India', 'football player training'. (3) For POLITICS/INDIA: NEVER use politician names — use location instead: 'Indian parliament New Delhi', 'Delhi government building', 'India flag'. (4) For TECHNOLOGY: 'smartphone technology India', 'laptop computer coding'. (5) For BUSINESS: 'business meeting office', 'stock market trading'. Always pick a concrete visual scene, never a person's name."}}
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


def _fix_paragraphs(html):
    """
    Enforce paragraph size: each <p> must have 4-5 sentences.
    - Too long (>5 sentences): split into 4-5 sentence chunks
    - Too short (<4 sentences): merge with next <p> if possible
    Also fixes heading hierarchy: removes H4+ and ensures no heading follows
    another heading directly without a paragraph between them.
    """
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")

    # ── Step 1: split paragraphs that are too long (>5 sentences) ───────────
    for p in list(soup.find_all("p")):
        text = p.get_text(strip=True)
        if not text:
            continue
        sentences = re.split(r'(?<=[.!?])\s+(?=[A-Z"\'(])', text)
        if len(sentences) <= 5:
            continue
        # Split into 4-5 sentence chunks
        new_tags = []
        chunk = []
        for i, s in enumerate(sentences):
            chunk.append(s)
            if len(chunk) >= 4 or i == len(sentences) - 1:
                new_p = soup.new_tag("p")
                new_p.string = " ".join(chunk)
                new_tags.append(new_p)
                chunk = []
        if len(new_tags) > 1:
            p.replace_with(new_tags[0])
            prev = new_tags[0]
            for tag in new_tags[1:]:
                prev.insert_after(tag)
                prev = tag

    # ── Step 2: merge consecutive short paragraphs (<3 sentences) ───────────
    paragraphs = soup.find_all("p")
    i = 0
    while i < len(paragraphs) - 1:
        p = paragraphs[i]
        if not p.parent:
            i += 1
            continue
        text = p.get_text(strip=True)
        sentences = re.split(r'(?<=[.!?])\s+(?=[A-Z"\'(])', text)
        if len(sentences) < 3:
            nxt = paragraphs[i + 1]
            if nxt.parent:
                nxt_text = nxt.get_text(strip=True)
                nxt_sents = re.split(r'(?<=[.!?])\s+(?=[A-Z"\'(])', nxt_text)
                if len(sentences) + len(nxt_sents) <= 5:
                    merged = soup.new_tag("p")
                    merged.string = text + " " + nxt_text
                    p.replace_with(merged)
                    nxt.decompose()
                    paragraphs = soup.find_all("p")
                    continue
        i += 1

    # ── Step 3: fix heading hierarchy — remove H4+ ───────────────────────────
    for tag in soup.find_all(["h4", "h5", "h6"]):
        # Demote to h3
        tag.name = "h3"

    # ── Step 4: no heading directly after another heading ────────────────────
    headings = {"h1", "h2", "h3"}
    for tag in list(soup.find_all(["h2", "h3"])):
        prev = tag.find_previous_sibling()
        if prev and prev.name in headings:
            spacer = soup.new_tag("p")
            spacer.string = ""
            tag.insert_before(spacer)

    return str(soup)


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
    category = story.get("category", "global")

    content_prompt = _CONTENT_PROMPT.format(
        title=title, source_name=source_name,
        summary=summary,
        article_text=article_text or "(use title and summary only)"
    )
    meta_prompt = _META_PROMPT.format(title=title, summary=summary, category=category)

    # ── Step 1: Generate HTML content (own retry loop) ──────────────────
    print("[WRITE] Step 1: generating content...")
    content_html = _groq_call_with_retry(content_prompt, max_tokens=2800, label="Step1-content", base_wait=60)

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

    # Fix paragraph formatting — split large blocks into short paragraphs
    content_html = _fix_paragraphs(content_html)
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
        "meta_description": str(meta["meta_description"])[:150],
        "tags": [str(t) for t in meta["tags"][:8]],
        "image_query": str(meta["image_query"])[:80],
        "content_html": content_html,
    }
