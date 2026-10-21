"""
Run this ONCE on your home computer to generate an Instagram session.
The session lets GitHub Actions post without triggering Instagram's block.

Steps:
1. Run: python generate_ig_session.py
2. Enter your Instagram username and password when prompted
3. Copy the printed JSON
4. Go to: https://github.com/Mohitdedha/news-journalist-agent/settings/secrets/actions
5. Add secret: Name = IG_SESSION, Value = (paste the JSON)
"""
import json
import getpass

try:
    from instagrapi import Client
except ImportError:
    print("Installing instagrapi...")
    import subprocess, sys
    subprocess.check_call([sys.executable, "-m", "pip", "install", "instagrapi"])
    from instagrapi import Client

username = input("Instagram username: ").strip()
password = getpass.getpass("Instagram password: ")

print("\nLogging in (may ask for verification code)...")

cl = Client()
# Use instagrapi's default device profile — has the correct bloks_versioning_id
try:
    cl.login(username, password)
except Exception as e:
    if "challenge" in str(e).lower() or "verification" in str(e).lower():
        code = input("Enter the verification code sent to your email/phone: ").strip()
        cl.challenge_resolve(cl.last_json)
        cl.verification_code = code
        cl.login(username, password)
    else:
        raise

session = cl.get_settings()
session_json = json.dumps(session)

print("\n" + "="*60)
print("SUCCESS! Copy the text below and add as GitHub Secret 'IG_SESSION':")
print("="*60)
print(session_json)
print("="*60)
print("\nGitHub Secrets URL:")
print("https://github.com/Mohitdedha/news-journalist-agent/settings/secrets/actions/new")
