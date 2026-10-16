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
from google import genai
from google.genai import types
from config import GEMINI_API_KEY, GEMINI_MODEL

_client = genai.Client(api_key=GEMINI_API_KEY)


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
            response = _client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.4,
                    max_output_tokens=2048,
                )
            )
            raw = response.text.strip()

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
