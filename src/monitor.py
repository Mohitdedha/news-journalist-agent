"""
Health monitoring, error classification, and email alerts.
Sends sanitized alerts (never includes secrets).
"""
import os
import smtplib
import traceback
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone
from config import ALERT_EMAIL, SMTP_USER, SMTP_PASS, SMTP_HOST, SMTP_PORT


def send_alert(subject, body_lines, error_type="ERROR"):
    """Send alert email via SMTP. Never includes secrets."""
    if not ALERT_EMAIL or not SMTP_USER or not SMTP_PASS:
        print(f"[ALERT-UNSENT] {subject}")
        for line in body_lines:
            print(f"  {line}")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[News Journalist Agent] {error_type}: {subject}"
    msg["From"] = SMTP_USER
    msg["To"] = ALERT_EMAIL

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    text_body = f"""IndiaBBCNews Automated Newsroom Alert
Time: {timestamp}
Type: {error_type}
Subject: {subject}

Details:
{chr(10).join(f'  {line}' for line in body_lines)}

---
This alert was sent by the News Journalist Agent.
To silence alerts, check GitHub Actions secrets and SMTP configuration.
"""

    html_body = f"""<html><body>
<h2 style="color:#cc0000;">IndiaBBCNews Newsroom Alert</h2>
<table cellpadding="6" style="border-collapse:collapse;font-family:monospace">
  <tr><td><b>Time</b></td><td>{timestamp}</td></tr>
  <tr><td><b>Type</b></td><td style="color:#cc0000;">{error_type}</td></tr>
  <tr><td><b>Subject</b></td><td>{subject}</td></tr>
</table>
<h3>Details</h3>
<ul>{''.join(f'<li>{line}</li>' for line in body_lines)}</ul>
<hr>
<small>IndiaBBCNews automated newsroom system</small>
</body></html>"""

    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_USER, ALERT_EMAIL, msg.as_string())
        print(f"[OK] Alert sent: {subject}")
    except Exception as e:
        print(f"[WARN] Alert email failed: {e}")


def log_run_summary(stories_processed, stories_published, stories_skipped, errors):
    """Print a compact run summary to GitHub Actions log."""
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"\n{'='*60}")
    print(f"NEWSROOM RUN SUMMARY — {timestamp}")
    print(f"  Processed : {stories_processed}")
    print(f"  Published : {stories_published}")
    print(f"  Skipped   : {stories_skipped}")
    print(f"  Errors    : {len(errors)}")
    if errors:
        print("  Error list:")
        for err in errors[:5]:
            print(f"    - {err}")
    print(f"{'='*60}\n")

    if errors and len(errors) >= 3:
        send_alert(
            subject=f"{len(errors)} errors in newsroom run",
            body_lines=[
                f"Run time: {timestamp}",
                f"Stories processed: {stories_processed}",
                f"Stories published: {stories_published}",
                "Errors encountered:",
            ] + [f"  • {e}" for e in errors[:10]],
            error_type="WARNING"
        )


def alert_wordpress_down(error_detail):
    send_alert(
        subject="WordPress API unreachable",
        body_lines=[
            "The WordPress REST API is not responding.",
            f"Error: {str(error_detail)[:200]}",
            "Action: Check indiabbcnews.com, Hostinger status, and WP credentials.",
            "No articles were published during this run.",
        ],
        error_type="CRITICAL"
    )


def alert_ai_quota(error_detail):
    send_alert(
        subject="AI API quota exceeded or error",
        body_lines=[
            "The Gemini AI API returned an error or quota limit.",
            f"Error: {str(error_detail)[:200]}",
            "Action: Check Google AI Studio quota at aistudio.google.com.",
            "Consider reducing max_stories_per_run in data/sources.json.",
        ],
        error_type="WARNING"
    )
