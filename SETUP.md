# IndiaBBCNews Automated Newsroom — Setup Guide

## Architecture

```
GitHub Actions (free, cron hourly)
    ↓
src/discover.py   ← RSS feeds from 20+ sources
    ↓
src/writer.py     ← Gemini 2.0 Flash AI writing (free tier)
    ↓
src/images.py     ← Pexels API + Gemini vision verification + Pillow processing
    ↓
src/publisher.py  ← WordPress REST API (Application Password auth)
    ↓
src/seo.py        ← IndexNow (Bing) + sitemap ping
    ↓
src/monitor.py    ← Email alerts on failure
```

Zero additional cost. Uses only free tiers and existing infrastructure.

---

## Step 1: Create GitHub Repository

1. Go to https://github.com/new
2. Repository name: `indiabbcnews-newsroom`
3. Set to **Public** (required for unlimited free Actions minutes)
4. Do NOT initialize with README (you'll push this code)
5. Click **Create repository**

Then push this project:
```bash
cd indiabbcnews-newsroom
git init
git add .
git commit -m "Initial newsroom setup"
git remote add origin https://github.com/YOUR_USERNAME/indiabbcnews-newsroom.git
git push -u origin main
```

---

## Step 2: Get Free API Keys

### A. Google Gemini API (AI writing + image verification)
1. Go to: https://aistudio.google.com/app/apikey
2. Click **Create API Key** → **Create API key in new project**
3. Copy the key — this is your `GEMINI_API_KEY`
4. **Free tier limits**: 15 requests/minute, 1,500 requests/day, 1M tokens/day
   - At 5 articles/hour × 24h = 120 articles/day — well within limits

### B. Pexels API (free royalty-free images)
1. Go to: https://www.pexels.com/api/
2. Click **Get Started** → create a free account
3. Go to https://www.pexels.com/api/new/ and request access
4. Copy your API key — this is your `PEXELS_API_KEY`
5. **Free tier limits**: 200 requests/hour — more than enough

### C. WordPress Application Password
1. Log into WordPress admin: https://indiabbcnews.com/wp-admin
2. Go to **Users → Profile**
3. Scroll to **Application Passwords** section
4. Enter name: `newsroom-bot`
5. Click **Add New Application Password**
6. **COPY THE PASSWORD SHOWN** (shown only once)
7. Your `WP_USER` is your WordPress username (e.g., `admin`)
8. Your `WP_APP_PASSWORD` is the generated password

### D. IndexNow Key (Bing search discovery)
1. Generate a random key: go to https://www.uuidgenerator.net/ and generate a UUID
2. Remove hyphens to get a 32-character key (e.g., `a1b2c3d4e5f6...`)
3. Create a file at your website: upload `{key}.txt` (containing just the key) to the root of indiabbcnews.com via Hostinger File Manager
4. Verify it works: https://indiabbcnews.com/YOUR_KEY.txt should show the key
5. This is your `INDEXNOW_KEY`

### E. Gmail App Password (alert emails)
1. Enable 2FA on your Google account if not already enabled
2. Go to: https://myaccount.google.com/apppasswords
3. App name: `IndiaBBCNews Newsroom`
4. Copy the 16-character password — this is your `SMTP_PASS`
5. Your `SMTP_USER` is your Gmail address (e.g., `yourname@gmail.com`)
6. Your `ALERT_EMAIL` is where you want alerts sent (can be same Gmail)

---

## Step 3: Add GitHub Secrets

1. Go to your GitHub repo → **Settings → Secrets and variables → Actions**
2. Click **New repository secret** for each of these:

| Secret Name | Value |
|---|---|
| `WP_URL` | `https://indiabbcnews.com` |
| `WP_USER` | Your WordPress username |
| `WP_APP_PASSWORD` | The Application Password from Step 2C |
| `GEMINI_API_KEY` | From Step 2A |
| `PEXELS_API_KEY` | From Step 2B |
| `INDEXNOW_KEY` | From Step 2D |
| `ALERT_EMAIL` | Your email for alerts |
| `SMTP_USER` | Your Gmail address |
| `SMTP_PASS` | Gmail App Password from Step 2E |

---

## Step 4: Test in Draft Mode (Phase E)

1. Go to GitHub repo → **Actions** tab
2. Click **IndiaBBCNews Automated Newsroom**
3. Click **Run workflow**
4. Set `publish_status` = **draft**, `max_stories` = **2**
5. Click **Run workflow**
6. Watch the logs — should take 3-5 minutes
7. Check WordPress admin → **Posts → Drafts** — you should see 2 new draft articles

### What to verify:
- [ ] Articles have correct headline and body (>400 words)
- [ ] Featured image is set and actually relevant
- [ ] Categories and tags are assigned
- [ ] Meta description is set (check Yoast SEO box below each post)
- [ ] No duplicate articles on repeated runs

---

## Step 5: Enable Live Publishing (Phase F — requires your approval)

Once drafts look good:

1. In the workflow manual run, change `publish_status` to **publish**
2. OR edit `.github/workflows/newsroom.yml` line:
   ```yaml
   PUBLISH_STATUS: ${{ inputs.publish_status || 'draft' }}
   ```
   Change `'draft'` to `'publish'`
3. Commit and push — the scheduled cron will now publish automatically

**DO NOT enable live publishing until you have reviewed at least 5 drafts and are satisfied with quality.**

---

## Step 6: Configure Categories

Edit `data/sources.json` to adjust `wp_category_id` values to match your WordPress category IDs. Current mapping (from your site):

| Category | WordPress ID |
|---|---|
| Global | 206 |
| Business | 193 |
| Technology | 33 |
| Entertainment | 189 |
| Economy | 12 |
| India Abroad | 211 |
| Europe & UK | 31 |
| Cricket | 29 |
| Sports | 34 |

---

## Emergency Shutdown

To immediately stop all publishing:
1. Go to GitHub repo → **Actions**
2. Click **IndiaBBCNews Automated Newsroom**
3. Click the three dots (**...**) → **Disable workflow**

This stops all scheduled runs immediately. No articles will be published until you re-enable.

---

## Costs

| Service | Free Tier | Usage |
|---|---|---|
| GitHub Actions | Unlimited (public repo) | ~5 min/run × 24 runs/day |
| Google Gemini | 1,500 req/day, 1M tokens/day | ~5-10 req/run |
| Pexels API | 200 req/hour | ~5 req/run |
| IndexNow | Unlimited | ~5 URL/run |
| Gmail SMTP | Unlimited | Only on errors |
| WordPress | Already yours | — |

**Total additional cost: ₹0**

---

## Troubleshooting

| Problem | Solution |
|---|---|
| `WordPress auth failed` | Regenerate Application Password in WP admin |
| `Gemini quota exceeded` | Reduce `max_stories` in sources.json or wait till next day |
| `No new stories` | All feeds checked and filtered — this is normal on quiet news days |
| `Image not found` | Pexels returned no results — article publishes without image |
| Duplicate articles | History cache working — check GitHub Actions cache |
| No email alerts | Verify Gmail App Password and 2FA setup |

---

## Backup & Restore

The `data/history.json` file tracks all published article URLs and titles.
GitHub Actions caches it between runs.

To export history: Download from GitHub Actions artifacts (kept 7 days).

To reset history (start fresh): Delete the GitHub Actions cache named `article-history-*` from the repo settings.
