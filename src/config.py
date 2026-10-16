"""Central configuration — reads from environment variables (GitHub Secrets in CI)."""
import os
import json

# WordPress
WP_URL = os.environ.get("WP_URL", "https://indiabbcnews.com")
WP_USER = os.environ.get("WP_USER", "")
WP_APP_PASSWORD = os.environ.get("WP_APP_PASSWORD", "")  # WordPress Application Password

# AI — Groq (free tier)
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")

# Images — Unsplash (free, 50 req/hour on demo, 5000/hour after approval)
UNSPLASH_ACCESS_KEY = os.environ.get("UNSPLASH_ACCESS_KEY", "")

# IndexNow (Bing search discovery)
INDEXNOW_KEY = os.environ.get("INDEXNOW_KEY", "")

# Alerts
ALERT_EMAIL = os.environ.get("ALERT_EMAIL", "")
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))

# Paths
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
HISTORY_FILE = os.path.join(DATA_DIR, "history.json")
SOURCES_FILE = os.path.join(DATA_DIR, "sources.json")

def load_sources():
    with open(SOURCES_FILE, "r") as f:
        return json.load(f)

def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r") as f:
            return json.load(f)
    return {"published_urls": [], "published_titles": [], "skipped_urls": []}

def save_history(history):
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)
