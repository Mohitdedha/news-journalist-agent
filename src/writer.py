"""
AI article writer using Groq (free tier — llama-3.3-70b).
Produces original, SEO-friendly news articles in English.
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
    "qwen/qwen3.8-27b",            # best general-purpose on this account
    "allam-2-7b",                   # fallback
    "llama-3.3-70b-versatile",
    "llama3-70b-8192",
    "llama3-8b-8192",
    "mixtral-8x7b-32768",
]

# Models that don't do text generation (skip them)
_GROQ_SKIP = {"whisper", "guard", "orpheus", "gpt-oss"}


_GROQ_MODEL_CACHE = [None]


def _get_available_model():
    """Pick the best available Groq model (cached after first call)."""
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
            print(f"[INFO] Groq available models: {all_models}")
            available = set(all_models)
            # Try preferred models first
            for m in _GROQ_MODELS:
                if m in available:
                    print(f"[INFO] Using Groq model: {m}")
                    _GROQ_MODEL_CACHE[0] = m
                    return m
            # Fall back: skip non-text models
            for m in all_models:
                if not any(skip in m.lower() for skip in _GROQ_SKIP):
                    print(f"[INFO] Falling back to Groq model: {m}")
                    _GROQ_MODEL_CACHE[0] = m
                    return m
        else:
            print(f"[WARN] Could not list Groq models: {resp.status_code} {resp.text[:200]}")
    except Exception as e:
        print(f"[WARN] Could not list Groq models: {e}")
    _GROQ_MODEL_CACHE[0] = _GROQ_MODELS[0]
    return _GROQ_MODELS[0]


def _groq_generate(prompt, temperature=0.4, max_tokens=900):
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY secret is not set in GitHub Secrets. "
                           "Get a free key at https://console.groq.com")
    model = _get_available_model()
    resp = requests.post(
        _GROQ_URL,
        headers={
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        },
        timeout=60,
    )
    if resp.status_code != 200:
        print(f"[WARN] Groq API error {resp.status_code}: {resp.text[:300]}")
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


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


WRITE_PROMPT = """You are a veteran news reporter. Write a short, punchy news article for IndiaBBCNews.com.

STYLE: Active voice. Varied sentence length. Specific facts, names, numbers. No AI filler phrases like "Furthermore", "Moreover", "It is worth noting". Write like a human, not a bot.

STRUCTURE: Opening fact → context → 2-3 body paragraphs with <h2> subheadings → brief closing. Keep it tight.

RULES:
- 300-400 words ONLY (very important — stay under 400 words)
- Use "reportedly" or "according to [source]" for unconfirmed claims
- End content with: <p><em>Source: {source_name}</em></p>

OUTPUT: Return ONLY a valid JSON object. No markdown fences. No text before or after the JSON.
The JSON must be complete and properly closed. Keep content_html short to fit in the response.

{{"headline": "Punchy headline under 12 words", "meta_description": "One factual sentence 120-155 characters", "tags": ["tag1","tag2","tag3","tag4","tag5"], "content_html": "<p>Lead paragraph.</p><h2>Subhead</h2><p>Body.</p><p><em>Source: {source_name}</em></p>", "image_query": "5-8 word photo search query"}}

SOURCE STORY:
Title: {title}
Source: {source_name}
URL: {url}
Summary: {summary}

ARTICLE TEXT (use only for facts, do not copy):
{article_text}
"""


def _repair_truncated_json(raw):
    """Attempt to repair JSON truncated mid-string by closing open structures."""
    raw = raw.strip()
    # Count open braces/brackets
    depth_brace = raw.count('{') - raw.count('}')
    depth_bracket = raw.count('[') - raw.count(']')
    # If last char is mid-string, close it
    if raw and raw[-1] not in ('}', ']', '"'):
        # Close any open string
        raw += '"'
    # Close open arrays then objects
    raw += ']' * max(0, depth_bracket)
    raw += '}' * max(0, depth_brace)
    return raw


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
            raw = _groq_generate(prompt).strip()

            raw = re.sub(r'^```json\s*', '', raw, flags=re.MULTILINE)
            raw = re.sub(r'```\s*$', '', raw, flags=re.MULTILINE)
            raw = raw.strip()

            # Try direct parse first
            try:
                data = json.loads(raw)
            except json.JSONDecodeError as je:
                print(f"[WARN] JSON truncated, attempting repair: {je}")
                repaired = _repair_truncated_json(raw)
                data = json.loads(repaired)
                print("[INFO] JSON repaired successfully")

            required = ["headline", "meta_description", "tags", "content_html", "image_query"]
            for field in required:
                if field not in data:
                    raise ValueError(f"Missing field: {field}")

            content = data.get("content_html", "") or ""
            if not isinstance(content, str):
                raise ValueError(f"content_html is not a string: {type(content)}")
            if content.strip().lower() in ("undefined", "null", "none", ""):
                raise ValueError(f"content_html has placeholder value: {content[:50]}")
            if len(content) < 200:
                raise ValueError(f"Content too short: {len(content)} chars")

            return data

        except json.JSONDecodeError as e:
            print(f"[WARN] JSON parse error attempt {attempt+1} (repair failed): {e}")
        except Exception as e:
            print(f"[WARN] Writer error attempt {attempt+1}: {e}")

        if attempt < max_retries - 1:
            print(f"[INFO] Waiting 70s before retry (rate limit window reset)...")
            time.sleep(70)

    raise RuntimeError(f"Failed to write article after {max_retries} attempts: {story['title']}")
