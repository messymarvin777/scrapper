"""
TikTok Trend Scraper for Dropshipping
--------------------------------------
Uses Apify's TikTok scraper to find trending products,
scores them by engagement velocity, and outputs an HTML report.

Requirements:
    pip install apify-client requests jinja2

Setup:
    1. Create a free account at https://apify.com
    2. Go to Settings > Integrations > API tokens
    3. Copy your token and paste it below (or set env var APIFY_TOKEN)
"""

import os
import json
import math
import time
import datetime
from collections import defaultdict
from apify_client import ApifyClient
from jinja2 import Template

# ─────────────────────────────────────────────
#  CONFIGURATION — edit these before running
# ─────────────────────────────────────────────

APIFY_TOKEN = os.environ.get("APIFY_TOKEN", "YOUR_APIFY_TOKEN_HERE")

# Hashtags to monitor — mix broad product tags + niche ones
HASHTAGS = [
    "KitchenTok",
    "KitchenGadgets", 
    "CookingHacks",
    "KitchenFinds",
    "CookingTok",
    "MealPrepTok",
    "KitchenTools",
    "CookingGadgets",
]

# How many videos to pull per hashtag (keep low on free tier — 100 total is safe)
VIDEOS_PER_HASHTAG = 15

# Minimum views to even consider a video (filters out tiny accounts)
MIN_VIEWS = 10_000
PRODUCT_KEYWORDS = [
    "link in bio", "get it", "buy", "shop", "amazon", "where to get",
    "gadget", "tool", "product", "game changer", "must have", "obsessed",
    "you need this", "find it", "grab it", "affordable", "under $"
]
# Only keep videos that mention product-related keywords
PRODUCT_KEYWORDS = [
    "link in bio", "get it", "buy", "shop", "amazon", "where to get",
    "gadget", "tool", "product", "game changer", "must have", "obsessed",
    "you need this", "find it", "grab it", "affordable", "under $"
]

# How many hours back to look (videos older than this get penalized in scoring)
RECENCY_WINDOW_HOURS = 72

# Output file
OUTPUT_FILE = "tiktok_trends.html"


# ─────────────────────────────────────────────
#  SCORING
# ─────────────────────────────────────────────

def engagement_velocity_score(video: dict) -> float:
    """
    Score = (likes + comments*3 + shares*5) / hours_since_posted

    Weights:
      - Shares matter most (someone sharing a product = strong signal)
      - Comments next (discussion = controversy or curiosity)
      - Likes are common but weaker signal

    Dividing by age gives velocity — a 10k engagement video posted
    2 hours ago beats a 50k video posted 3 days ago.
    """
    likes    = video.get("diggCount", 0) or 0
    comments = video.get("commentCount", 0) or 0
    shares   = video.get("shareCount", 0) or 0
    plays    = video.get("playCount", 0) or 0

    if plays < MIN_VIEWS:
        return 0.0

    weighted_engagement = likes + (comments * 3) + (shares * 5)

    # Age in hours
    create_time = video.get("createTime", 0)
    if create_time:
        posted_dt = datetime.datetime.fromtimestamp(create_time, tz=datetime.timezone.utc)
        now_dt    = datetime.datetime.now(tz=datetime.timezone.utc)
        age_hours = max((now_dt - posted_dt).total_seconds() / 3600, 1)
    else:
        age_hours = RECENCY_WINDOW_HOURS  # assume old if unknown

    # Recency bonus: videos under 24h old get a 1.5x multiplier
    recency_multiplier = 1.5 if age_hours < 24 else 1.0

    velocity = (weighted_engagement / age_hours) * recency_multiplier

    # Log-scale so a single viral video doesn't dwarf everything else
    return round(math.log1p(velocity), 4)


def extract_product_keywords(text: str) -> list[str]:
    """
    Very lightweight keyword extractor.
    Looks for product-ish nouns — things that could be dropshipped.
    Not ML-based; just pattern matching on common product indicators.
    """
    import re
    text = text.lower()

    # Strip URLs and mentions
    text = re.sub(r"http\S+|@\w+|#\w+", "", text)

    # Common product indicator phrases
    indicators = [
        "this ", "found this", "bought this", "love this",
        "need this", "get this", "best ", "perfect ", "amazing ",
        "game changer", "obsessed with", "trying this"
    ]

    keywords = []
    for phrase in indicators:
        idx = text.find(phrase)
        if idx != -1:
            # Grab the ~5 words after the indicator phrase
            snippet = text[idx + len(phrase):idx + len(phrase) + 60]
            words = snippet.split()[:5]
            if words:
                keywords.append(" ".join(words).strip(".,!?"))

    return list(set(keywords)) if keywords else ["(see video)"]


# ─────────────────────────────────────────────
#  APIFY SCRAPING
# ─────────────────────────────────────────────

def scrape_hashtag(client: ApifyClient, hashtag: str) -> list[dict]:
    """Run Apify's TikTok Hashtag Scraper for one hashtag."""
    print(f"  Scraping #{hashtag}...")
    # Try multiple known actor IDs for TikTok hashtag scraping
    actor_ids = [
        "clockworks/tiktok-hashtag-scraper",
        "clockworks/tiktok-scraper",
        "novi/tiktok-scraper",
    ]
    for actor_id in actor_ids:
        try:
            run = client.actor(actor_id).call(
                run_input={
                    "hashtags": [hashtag],
                    "resultsPerPage": VIDEOS_PER_HASHTAG,
                    "shouldDownloadVideos": False,
                    "shouldDownloadCovers": False,
                },
                
            )
            items = list(client.dataset(run.default_dataset_id).iterate_items())
            print(f"    → {len(items)} videos pulled (via {actor_id})")
            return items
        except Exception as e:
            print(f"    ✗ {actor_id} failed: {e}")
            continue
    return []


def collect_all_videos(client: ApifyClient) -> list[dict]:
    all_videos = []
    seen_ids = set()

    for hashtag in HASHTAGS:
        videos = scrape_hashtag(client, hashtag)
        for v in videos:
            vid_id = v.get("id") or v.get("videoId")
            if vid_id and vid_id not in seen_ids:
                seen_ids.add(vid_id)
                v["_source_hashtag"] = hashtag
                all_videos.append(v)
        time.sleep(1)  # be polite to the API

    print(f"\nTotal unique videos collected: {len(all_videos)}")
    return all_videos


# ─────────────────────────────────────────────
#  ANALYSIS
# ─────────────────────────────────────────────

def analyze_videos(videos: list[dict]) -> list[dict]:
    results = []

    for v in videos:
        score = engagement_velocity_score(v)
        if score == 0:
            continue

        desc = v.get("text", "") or v.get("desc", "") or ""
        if not any(kw in desc.lower() for kw in PRODUCT_KEYWORDS):
            continue
        author = v.get("authorMeta", {}) or {}

        create_time = v.get("createTime", 0)
        if create_time:
            posted = datetime.datetime.fromtimestamp(
                create_time, tz=datetime.timezone.utc
            ).strftime("%Y-%m-%d %H:%M UTC")
        else:
            posted = "Unknown"

        results.append({
            "score":        score,
            "title":        desc[:120] + ("..." if len(desc) > 120 else ""),
            "full_desc":    desc,
            "plays":        v.get("playCount", 0) or 0,
            "likes":        v.get("diggCount", 0) or 0,
            "comments":     v.get("commentCount", 0) or 0,
            "shares":       v.get("shareCount", 0) or 0,
            "author":       author.get("name") or author.get("uniqueId") or "unknown",
            "followers":    author.get("fans", 0) or 0,
            "hashtag":      v.get("_source_hashtag", ""),
            "posted":       posted,
            "url":          v.get("webVideoUrl") or v.get("videoUrl") or "#",
            "keywords":     extract_product_keywords(desc),
        })

    # Sort by score descending
    results.sort(key=lambda x: x["score"], reverse=True)
    return results


def cluster_by_keyword(results: list[dict]) -> dict[str, list]:
    """
    Group top results by shared keywords to surface product themes,
    not just individual viral videos.
    """
    clusters = defaultdict(list)
    for r in results[:50]:  # top 50 only
        for kw in r["keywords"]:
            clusters[kw].append(r)
    # Sort clusters by combined score
    return dict(
        sorted(clusters.items(), key=lambda x: sum(i["score"] for i in x[1]), reverse=True)
    )


# ─────────────────────────────────────────────
#  HTML REPORT
# ─────────────────────────────────────────────

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>TikTok Trend Report — {{ generated_at }}</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background: #0f0f0f; color: #f0f0f0; padding: 24px; }
  h1 { font-size: 1.6rem; color: #fe2c55; margin-bottom: 4px; }
  .meta { color: #888; font-size: 0.85rem; margin-bottom: 32px; }
  h2 { font-size: 1.1rem; color: #69c9d0; margin: 32px 0 12px; border-bottom: 1px solid #222; padding-bottom: 6px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 16px; }
  .card { background: #1a1a1a; border: 1px solid #2a2a2a; border-radius: 12px;
          padding: 16px; transition: border-color .2s; }
  .card:hover { border-color: #fe2c55; }
  .rank { font-size: 0.75rem; color: #888; margin-bottom: 6px; }
  .score { font-size: 1.3rem; font-weight: 700; color: #fe2c55; }
  .score span { font-size: 0.75rem; color: #888; font-weight: 400; }
  .desc { font-size: 0.85rem; color: #ccc; margin: 10px 0; line-height: 1.4; }
  .stats { display: flex; gap: 12px; font-size: 0.8rem; color: #888; flex-wrap: wrap; margin: 10px 0; }
  .stats b { color: #f0f0f0; }
  .tags { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
  .tag { background: #2a2a2a; border-radius: 20px; padding: 3px 10px;
         font-size: 0.75rem; color: #69c9d0; }
  .hashtag { color: #888; font-size: 0.75rem; margin-top: 6px; }
  a { color: #fe2c55; text-decoration: none; font-size: 0.8rem; }
  a:hover { text-decoration: underline; }
  .summary { background: #1a1a1a; border-radius: 12px; padding: 20px;
             margin-bottom: 24px; border: 1px solid #2a2a2a; }
  .summary-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 16px; margin-top: 12px; }
  .stat-box { text-align: center; }
  .stat-box .num { font-size: 1.8rem; font-weight: 700; color: #69c9d0; }
  .stat-box .label { font-size: 0.75rem; color: #888; }
  .cluster-name { font-weight: 600; color: #f0f0f0; margin-bottom: 4px; }
  .cluster-score { font-size: 0.8rem; color: #888; }
</style>
</head>
<body>

<h1>🛍 TikTok Product Trend Report</h1>
<p class="meta">Generated {{ generated_at }} &nbsp;·&nbsp; {{ total_videos }} videos analyzed &nbsp;·&nbsp; Hashtags: {{ hashtags }}</p>

<div class="summary">
  <h2 style="margin-top:0; border:none; padding:0;">📊 Summary</h2>
  <div class="summary-grid">
    <div class="stat-box"><div class="num">{{ total_videos }}</div><div class="label">Videos Analyzed</div></div>
    <div class="stat-box"><div class="num">{{ scored_videos }}</div><div class="label">Above Threshold</div></div>
    <div class="stat-box"><div class="num">{{ top_score }}</div><div class="label">Top Score</div></div>
    <div class="stat-box"><div class="num">{{ total_plays }}</div><div class="label">Total Views</div></div>
  </div>
</div>

<h2>🔥 Top Trending Product Videos</h2>
<div class="grid">
{% for r in top_results %}
<div class="card">
  <div class="rank">#{{ loop.index }} &nbsp;·&nbsp; via #{{ r.hashtag }}</div>
  <div class="score">{{ r.score }} <span>velocity score</span></div>
  <p class="desc">{{ r.title }}</p>
  <div class="stats">
    <span>👁 <b>{{ "{:,}".format(r.plays) }}</b></span>
    <span>❤️ <b>{{ "{:,}".format(r.likes) }}</b></span>
    <span>💬 <b>{{ "{:,}".format(r.comments) }}</b></span>
    <span>🔁 <b>{{ "{:,}".format(r.shares) }}</b></span>
  </div>
  <div class="stats">
    <span>@{{ r.author }} &nbsp;·&nbsp; {{ "{:,}".format(r.followers) }} followers</span>
  </div>
  <div class="stats"><span>🕐 {{ r.posted }}</span></div>
  <div class="tags">
    {% for kw in r.keywords[:4] %}<span class="tag">{{ kw }}</span>{% endfor %}
  </div>
  <div style="margin-top:10px"><a href="{{ r.url }}" target="_blank">▶ Watch on TikTok →</a></div>
</div>
{% endfor %}
</div>

<h2>🧠 Product Themes (Clustered)</h2>
<div class="grid">
{% for kw, items in clusters.items() %}
{% if loop.index <= 12 %}
<div class="card">
  <div class="cluster-name">{{ kw }}</div>
  <div class="cluster-score">{{ items|length }} video(s) &nbsp;·&nbsp; combined score {{ "%.2f"|format(items|sum(attribute='score')) }}</div>
  <div style="margin-top:10px">
    {% for item in items[:3] %}
    <div style="font-size:0.8rem; color:#aaa; margin-top:6px; border-top:1px solid #2a2a2a; padding-top:6px;">
      <a href="{{ item.url }}" target="_blank">{{ item.title[:80] }}…</a>
      <span style="color:#fe2c55"> ({{ item.score }})</span>
    </div>
    {% endfor %}
  </div>
</div>
{% endif %}
{% endfor %}
</div>

<p style="color:#444; font-size:0.75rem; margin-top:40px; text-align:center;">
  Scores are engagement velocity = (likes + comments×3 + shares×5) / age_in_hours × recency_bonus, log-scaled.
  Higher = trending faster right now.
</p>

</body>
</html>
"""

def generate_report(results: list[dict], all_videos: list[dict]) -> str:
    clusters = cluster_by_keyword(results)
    total_plays = sum(r["plays"] for r in results)

    template = Template(HTML_TEMPLATE)
    html = template.render(
        generated_at   = datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        total_videos   = len(all_videos),
        scored_videos  = len(results),
        top_score      = results[0]["score"] if results else 0,
        total_plays    = f"{total_plays:,}",
        hashtags       = ", ".join(f"#{h}" for h in HASHTAGS),
        top_results    = results[:20],
        clusters       = clusters,
    )
    return html


# ─────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────

def main():
    if APIFY_TOKEN == "YOUR_APIFY_TOKEN_HERE":
        print("⚠️  Set your Apify token first!")
        print("   Either edit APIFY_TOKEN in scraper.py")
        print("   Or run:  export APIFY_TOKEN=your_token_here")
        return

    print("🚀 TikTok Trend Scraper Starting...")
    print(f"   Hashtags: {', '.join('#' + h for h in HASHTAGS)}")
    print(f"   Videos per hashtag: {VIDEOS_PER_HASHTAG}\n")

    client = ApifyClient(APIFY_TOKEN)

    print("📡 Collecting videos from TikTok...")
    all_videos = collect_all_videos(client)

    print("\n🧮 Scoring by engagement velocity...")
    results = analyze_videos(all_videos)
    print(f"   {len(results)} videos scored above threshold")

    if not results:
        print("⚠️  No results above threshold — generating empty report anyway.")
        # Generate a report with a helpful message so the file always exists
        html = """<!DOCTYPE html><html><head><title>TikTok Trend Report</title>
        <style>body{font-family:sans-serif;background:#0f0f0f;color:#f0f0f0;
        padding:40px;text-align:center;}</style></head>
        <body><h1 style="color:#fe2c55">No results yet</h1>
        <p>The scraper ran but found no videos above the minimum view threshold.<br>
        This usually means the Apify actor returned limited data on the first run.<br>
        Try running again tomorrow — it improves once the actor warms up.</p>
        <p style="color:#888">Generated: """ + datetime.datetime.now().strftime("%Y-%m-%d %H:%M") + """</p>
        </body></html>"""
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"✅ Empty report saved to {OUTPUT_FILE}")
        return

    print(f"\n📄 Generating HTML report → {OUTPUT_FILE}")
    html = generate_report(results, all_videos)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\n✅ Done! Open {OUTPUT_FILE} in your browser.")
    print(f"\n🏆 Top 5 trending products right now:")
    for i, r in enumerate(results[:5], 1):
        print(f"   {i}. Score {r['score']:>6} | {r['plays']:>10,} views | {r['title'][:60]}")


if __name__ == "__main__":
    main()
