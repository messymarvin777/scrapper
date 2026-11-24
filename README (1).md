# TikTok Trend Scraper 🛍

Automatically scrapes TikTok for trending products, scores them by engagement velocity, and publishes a live HTML dashboard — updated every morning via GitHub Actions.

## Live Dashboard

> After setup, your dashboard will be at:  
> `https://YOUR-USERNAME.github.io/YOUR-REPO-NAME/tiktok_trends.html`

---

## How It Works

1. GitHub Actions runs the scraper every day at 8 AM Central
2. Pulls videos from product hashtags via Apify
3. Scores each video by **engagement velocity** (shares×5 + comments×3 + likes) ÷ age in hours
4. Generates `tiktok_trends.html` and commits it back to the repo
5. GitHub Pages serves the report at a public URL

---

## Setup

### 1. Fork or clone this repo

```bash
git clone https://github.com/YOUR-USERNAME/tiktok-trend-scraper.git
cd tiktok-trend-scraper
```

### 2. Get your Apify token

1. Go to [apify.com](https://apify.com) and create a free account
2. Navigate to **Settings → Integrations → API Tokens**
3. Copy your token

### 3. Add token as a GitHub Secret

1. In your GitHub repo → **Settings → Secrets and variables → Actions**
2. Click **New repository secret**
3. Name: `APIFY_TOKEN`
4. Value: paste your token
5. Click **Add secret**

### 4. Enable GitHub Pages

1. In your repo → **Settings → Pages**
2. Source: **Deploy from a branch**
3. Branch: `main` / folder: `/ (root)`
4. Click **Save**

### 5. Run it manually first

Go to **Actions → TikTok Trend Scraper → Run workflow** to trigger it immediately and confirm everything works before waiting for the daily schedule.

---

## Configuration

Edit the top of `scraper.py` to customize:

| Variable | Default | Description |
|---|---|---|
| `HASHTAGS` | 8 product tags | Hashtags to monitor |
| `VIDEOS_PER_HASHTAG` | 15 | Videos pulled per tag (keep ≤15 on free Apify tier) |
| `MIN_VIEWS` | 10,000 | Filter out low-reach videos |
| `RECENCY_WINDOW_HOURS` | 72 | Age window for scoring |

---

## Scoring Formula

```
score = log(1 + (likes + comments×3 + shares×5) / age_hours × recency_bonus)
```

- **Shares** weighted highest — someone sharing a product is a strong buy signal
- **Recency bonus** (1.5×) for videos under 24 hours old
- **Log scale** so one viral video doesn't bury everything else

---

## Cost

- GitHub Actions: **free** (2,000 minutes/month on free tier; this job uses ~2 min/day)
- Apify: **free tier** (~$5/month compute credit; this uses ~$0.10–0.30/run)
