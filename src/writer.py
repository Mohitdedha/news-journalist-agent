"""
AI article writer using Google Gemini (free tier).
Produces original, SEO-friendly news articles in English.
"""
import os
import re
import time
import json
import requests
from bs4 import BeautifulSoup
from config import GEMINI_API_KEY, GEMINI_MODEL

_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
_GEMINI_URL = _GEMINI_BASE + "/models/{}/generateContent"

# Preferred model order — first available one wins
_PREFERRED_MODELS = [
    "gemini-flash-latest",
    "gemini-pro-latest",
    "gemini-3.5-flash",
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
    "gemini-3.8-flash",
]


def _validate_api_key():
    """Check API key format and warn if it looks wrong."""
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY secret is not set in GitHub Secrets.")
    if not GEMINI_API_KEY.startswith("AIza"):
        print(f"[WARN] GEMINI_API_KEY does not start with 'AIza' (got '{GEMINI_API_KEY[:6]}...'). "
              "This may not be a valid Google AI Studio API key. "
              "Generate a fresh key at https://aistudio.google.com/apikey and update the GitHub Secret.")


def _list_models():
    """Return model names that support generateContent."""
    _validate_api_key()
    try:
        resp = requests.get(
            f"{_GEMINI_BASE}/models",
            params={"key": GEMINI_API_KEY},
            timeout=15,
        )
        resp.raise_for_status()
        models = resp.json().get("models", [])
        names = []
        for m in models:
            methods = m.get("supportedGenerationMethods", [])
            if "generateContent" in methods:
                names.append(m["name"].replace("models/", ""))
        return names
    except Exception as e:
        print(f"[WARN] Could not list Gemini models: {e}")
        return []


def _pick_model():
    """Pick the best available Gemini model."""
    available = set(_list_models())
    print(f"[INFO] Available Gemini models: {sorted(available)}")
    for m in _PREFERRED_MODELS:
        if m in available:
            print(f"[INFO] Selected Gemini model: {m}")
            return m
    # Fallback: use the first available flash model
    for m in sorted(available):
        if "flash" in m:
            print(f"[INFO] Fallback Gemini model: {m}")
            return m
    if available:
        fallback = sorted(available)[0]
        print(f"[INFO] Last-resort Gemini model: {fallback}")
        return fallback
    raise RuntimeError("No Gemini models available for this API key")


_ACTIVE_MODEL = None


def _get_model():
    global _ACTIVE_MODEL
    if _ACTIVE_MODEL is None:
        _ACTIVE_MODEL = _pick_model()
    return _ACTIVE_MODEL


def _gemini_post(url, payload):
    """Try multiple auth methods; return successful response or raise last error."""
    attempts = [
        # 1. Standard query param API key
        lambda: requests.post(url, params={"key": GEMINI_API_KEY}, json=payload, timeout=60),
        # 2. x-goog-api-key header
        lambda: requests.post(url, headers={"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"}, json=payload, timeout=60),
        # 3. Bearer token (for OAuth access tokens)
        lambda: requests.post(url, headers={"Authorization": f"Bearer {GEMINI_API_KEY}", "Content-Type": "application/json"}, json=payload, timeout=60),
    ]
    last_resp = None
    for i, attempt in enumerate(attempts):
        resp = attempt()
        if resp.status_code == 200:
            return resp
        print(f"[WARN] Auth method {i+1} → {resp.status_code}: {resp.text[:200]}")
        last_resp = resp
    last_resp.raise_for_status()


def _gemini_generate(prompt, model, temperature=0.4, max_tokens=2048):
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
    }
    # Try v1beta first, then v1
    for api_ver in ("v1beta", "v1"):
        url = f"https://generativelanguage.googleapis.com/{api_ver}/models/{model}/generateContent"
        try:
            resp = _gemini_post(url, payload)
            return resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        except requests.HTTPError as e:
            print(f"[WARN] {api_ver} failed for {model}: {e}")
    raise RuntimeError(f"All endpoints failed for model {model}")


def fetch_article_text(url, timeout=15):
    """Fetch and extract main text from an article URL."""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; IndiaBBCNewsBot/1.0)"}
        resp = requests.get(url, headers=headers, timeout=timeout)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        for tag in soup(["script", "style", "nav", "footer", "aside", "iframe", "noscript"]):
            tag.decompose()

        article = soup.find("article") or soup.find(id="content") or soup.find(class_=re.compile(r'article|content|story|body', re.I))
        text = (article or soup.find("body") or soup).get_text(separator=" ", strip=True)
        text = re.sub(r'\s+', ' ', text).strip()
        return text[:8000]
    except Exception as e:
        print(f"[WARN] Could not fetch article text: {e}")
        return ""


WRITE_PROMPT = """You are a professional international news journalist writing for IndiaBBCNews.com, an English-language news website for a global audience with particular interest in India and world affairs.

Write an original, factual, reader-focused news article based on the source material below.

RULES:
- Write in clear, formal but accessible English
- Do NOT copy sentences verbatim from the source — rephrase and synthesize
- Cite the original source at the bottom (e.g., "Source: BBC News")
- Structure: headline, introduction paragraph, 3-5 body paragraphs with subheadings, brief conclusion
- Include relevant context and background
- Distinguish confirmed facts from allegations with words like "allegedly," "reportedly"
- Word count: 450–800 words
- NO keyword stuffing, NO AI-sounding filler phrases like "In today's fast-paced world"
- End with a factual, informative closing paragraph

OUTPUT FORMAT (return valid JSON only):
{{
  "headline": "...",
  "meta_description": "One sentence, 120-155 characters, factual summary",
  "tags": ["tag1", "tag2", "tag3", "tag4", "tag5"],
  "content_html": "<p>...</p><h2>...</h2><p>...</p>...",
  "image_query": "Specific 5-8 word search query for a relevant photograph"
}}

SOURCE STORY:
Title: {title}
Source: {source_name}
URL: {url}
Summary: {summary}

FULL ARTICLE TEXT (use for accuracy, do not copy):
{article_text}
"""


def write_article(story, max_retries=3):
    """Generate article for a story. Returns dict or raises."""
    article_text = fetch_article_text(story["url"])

    prompt = WRITE_PROMPT.format(
        title=story["title"],
        source_name=story["source_name"],
        url=story["url"],
        summary=story["summary"],
        article_text=article_text or "(Article text unavailable — use title and summary only)"
    )

    for attempt in range(max_retries):
        try:
            raw = _gemini_generate(prompt, _get_model()).strip()

            raw = re.sub(r'^```json\s*', '', raw, flags=re.MULTILINE)
            raw = re.sub(r'```\s*$', '', raw, flags=re.MULTILINE)

            data = json.loads(raw)

            required = ["headline", "meta_description", "tags", "content_html", "image_query"]
            for field in required:
                if field not in data:
                    raise ValueError(f"Missing field: {field}")

            if len(data.get("content_html", "")) < 200:
                raise ValueError("Content too short")

            return data

        except json.JSONDecodeError as e:
            print(f"[WARN] JSON parse error attempt {attempt+1}: {e}")
        except Exception as e:
            print(f"[WARN] Writer error attempt {attempt+1}: {e}")

        if attempt < max_retries - 1:
            time.sleep(10 * (attempt + 1))

    raise RuntimeError(f"Failed to write article after {max_retries} attempts: {story['title']}")
