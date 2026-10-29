"""
TrendScore Engine — The core algorithm for InvestFlow Auto Trader Pro
=====================================================================

This engine scores stocks based on their "online footprint":
- WHO mentioned it (weight by source credibility)
- HOW MANY times (raw volume)
- SENTIMENT (positive vs negative)
- SPIKE VELOCITY (is buzz growing fast?)

The final TrendScore ranks stocks from 0-100.
Higher score = more worth investing in.

SETUP (run these in terminal):
    pip install pytrends praw requests textblob

Then set your API keys in the config below.
"""

import time
import json
from datetime import datetime, timedelta
from collections import defaultdict

# ============================================================
# CONFIGURATION — Set your API keys here
# ============================================================

CONFIG = {
    # Reddit — Free. Create an app at https://www.reddit.com/prefs/apps
    # Click "create app", pick "script", use http://localhost as redirect
    "reddit_client_id": "YOUR_REDDIT_CLIENT_ID",
    "reddit_client_secret": "YOUR_REDDIT_CLIENT_SECRET",
    "reddit_user_agent": "TrendScore/1.0",

    # NewsAPI — Free tier: 500 requests/day. Get key at https://newsapi.org
    "newsapi_key": "YOUR_NEWSAPI_KEY",

    # Google Trends — No API key needed, uses pytrends library

    # Stocks to track (top 10 S&P 500)
    "symbols": ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "BRK.B", "TSLA", "AVGO", "JPM"],

    # Full company names for searching (used in social/news queries)
    "company_names": {
        "AAPL": "Apple",
        "MSFT": "Microsoft",
        "NVDA": "NVIDIA",
        "AMZN": "Amazon",
        "GOOGL": "Google",
        "META": "Meta",
        "BRK.B": "Berkshire Hathaway",
        "TSLA": "Tesla",
        "AVGO": "Broadcom",
        "JPM": "JPMorgan",
    },
}


# ============================================================
# SOURCE TIER WEIGHTS — This is your secret sauce
# ============================================================
# A mention from Bloomberg is worth WAY more than a random Reddit post.
# These weights define how much each source type counts.

SOURCE_TIERS = {
    # TIER 1: Major financial outlets & verified analysts (10x weight)
    "tier1": {
        "weight": 10,
        "sources": [
            "bloomberg", "reuters", "cnbc", "wsj", "wall street journal",
            "financial times", "ft.com", "barrons", "marketwatch",
            "seeking alpha", "motley fool", "morningstar",
        ]
    },
    # TIER 2: Popular finance communities & influencers (3x weight)
    "tier2": {
        "weight": 3,
        "sources": [
            "r/wallstreetbets", "r/stocks", "r/investing", "r/options",
            "r/stockmarket", "r/cryptocurrency", "r/finance",
        ]
    },
    # TIER 3: General social media (1x weight)
    "tier3": {
        "weight": 1,
        "sources": [
            "reddit_other", "twitter", "general_news", "other",
        ]
    },
}


# ============================================================
# TRENDSCORE CALCULATION
# ============================================================

class TrendScore:
    """
    Calculates a 0-100 score for each stock based on online footprint.

    The score is made up of 4 components:
    - Volume Score (30%) — how many mentions total
    - Source Quality Score (30%) — WHO mentioned it (tier weighting)
    - Sentiment Score (20%) — positive vs negative buzz
    - Spike Score (20%) — is attention growing fast?
    """

    # How much each component matters in the final score
    WEIGHTS = {
        "volume": 0.30,      # 30% — raw mention count
        "source_quality": 0.30,  # 30% — who said it
        "sentiment": 0.20,   # 20% — positive or negative
        "spike": 0.20,       # 20% — speed of buzz increase
    }

    def __init__(self):
        # Stores mention data per stock
        # Format: { "AAPL": [{"source": "bloomberg", "text": "...", "sentiment": 0.5, "time": ...}, ...] }
        self.mentions = defaultdict(list)
        # Historical mention counts for spike detection
        # Format: { "AAPL": [count_day1, count_day2, count_day3, ...] }
        self.history = defaultdict(list)

    def add_mention(self, symbol, source, text, sentiment_score=None):
        """
        Add a mention of a stock from any source.

        Args:
            symbol: Stock ticker, e.g. "AAPL"
            source: Where it came from, e.g. "bloomberg", "r/wallstreetbets"
            text: The actual text of the mention
            sentiment_score: -1.0 (very negative) to +1.0 (very positive), or None to auto-detect
        """
        if sentiment_score is None:
            sentiment_score = self._analyze_sentiment(text)

        tier = self._get_tier(source)

        self.mentions[symbol].append({
            "source": source,
            "tier": tier,
            "text": text,
            "sentiment": sentiment_score,
            "time": datetime.now(),
        })

    def calculate_score(self, symbol):
        """
        Calculate the TrendScore (0-100) for a stock.
        Returns a dict with the total score and breakdown.
        """
        mentions = self.mentions.get(symbol, [])

        if not mentions:
            return {
                "symbol": symbol,
                "total_score": 0,
                "volume_score": 0,
                "source_quality_score": 0,
                "sentiment_score": 0,
                "spike_score": 0,
                "mention_count": 0,
                "avg_sentiment": 0,
            }

        # --- VOLUME SCORE ---
        # More mentions = higher score, with diminishing returns
        count = len(mentions)
        # Normalize: 100+ mentions = max score, using log scale
        import math
        volume_raw = min(100, (math.log(count + 1) / math.log(101)) * 100)

        # --- SOURCE QUALITY SCORE ---
        # Weight each mention by its tier
        total_weighted = sum(
            SOURCE_TIERS.get(m["tier"], {}).get("weight", 1)
            for m in mentions
        )
        # Compare to what all-tier-3 would give
        max_possible = count * SOURCE_TIERS["tier1"]["weight"]
        source_raw = min(100, (total_weighted / max(max_possible, 1)) * 100) if count > 0 else 0

        # --- SENTIMENT SCORE ---
        # Average sentiment, mapped from [-1, 1] to [0, 100]
        avg_sentiment = sum(m["sentiment"] for m in mentions) / count
        sentiment_raw = (avg_sentiment + 1) / 2 * 100  # Map -1..1 to 0..100

        # --- SPIKE SCORE ---
        # Compare current mention count to historical average
        hist = self.history.get(symbol, [])
        if len(hist) >= 2:
            avg_historical = sum(hist[-7:]) / len(hist[-7:])  # Last 7 periods
            if avg_historical > 0:
                spike_ratio = count / avg_historical
                spike_raw = min(100, (spike_ratio - 1) * 50)  # 3x normal = 100
                spike_raw = max(0, spike_raw)
            else:
                spike_raw = 50 if count > 0 else 0
        else:
            spike_raw = 50  # Not enough history, default to neutral

        # --- FINAL SCORE ---
        total = (
            volume_raw * self.WEIGHTS["volume"] +
            source_raw * self.WEIGHTS["source_quality"] +
            sentiment_raw * self.WEIGHTS["sentiment"] +
            spike_raw * self.WEIGHTS["spike"]
        )

        return {
            "symbol": symbol,
            "total_score": round(total, 1),
            "volume_score": round(volume_raw, 1),
            "source_quality_score": round(source_raw, 1),
            "sentiment_score": round(sentiment_raw, 1),
            "spike_score": round(spike_raw, 1),
            "mention_count": count,
            "avg_sentiment": round(avg_sentiment, 3),
        }

    def rank_all(self, symbols=None):
        """
        Rank all tracked stocks by TrendScore.
        Returns a sorted list, highest score first.
        """
        symbols = symbols or list(self.mentions.keys())
        scores = [self.calculate_score(sym) for sym in symbols]
        scores.sort(key=lambda x: x["total_score"], reverse=True)
        return scores

    def snapshot_history(self):
        """
        Save current mention counts to history (call this once per day/hour).
        Used for spike detection.
        """
        for sym in self.mentions:
            self.history[sym].append(len(self.mentions[sym]))
            # Keep last 30 periods
            if len(self.history[sym]) > 30:
                self.history[sym] = self.history[sym][-30:]

    def clear_mentions(self):
        """Clear current mentions (call before each new data collection cycle)."""
        self.mentions = defaultdict(list)

    def _get_tier(self, source):
        """Determine which tier a source belongs to."""
        source_lower = source.lower()
        for tier_name, tier_data in SOURCE_TIERS.items():
            if any(s in source_lower for s in tier_data["sources"]):
                return tier_name
        return "tier3"

    def _analyze_sentiment(self, text):
        """
        Basic sentiment analysis. Returns -1.0 to +1.0.
        Uses TextBlob for now — can be upgraded to a better model later.
        """
        try:
            from textblob import TextBlob
            blob = TextBlob(text)
            return round(blob.sentiment.polarity, 3)
        except ImportError:
            # Fallback: simple keyword-based sentiment
            positive = ["buy", "bull", "up", "grow", "profit", "beat", "surge", "rally", "strong", "record", "gain"]
            negative = ["sell", "bear", "down", "crash", "loss", "miss", "drop", "fall", "weak", "decline", "risk"]
            text_lower = text.lower()
            pos_count = sum(1 for w in positive if w in text_lower)
            neg_count = sum(1 for w in negative if w in text_lower)
            total = pos_count + neg_count
            if total == 0:
                return 0.0
            return round((pos_count - neg_count) / total, 3)


# ============================================================
# DATA COLLECTORS — Pull real data from APIs
# ============================================================

class RedditCollector:
    """Collect stock mentions from Reddit finance subreddits."""

    SUBREDDITS = ["wallstreetbets", "stocks", "investing", "stockmarket", "options"]

    def __init__(self, client_id, client_secret, user_agent):
        self.client_id = client_id
        self.client_secret = client_secret
        self.user_agent = user_agent
        self.reddit = None

    def connect(self):
        """Initialize Reddit API connection."""
        try:
            import praw
            self.reddit = praw.Reddit(
                client_id=self.client_id,
                client_secret=self.client_secret,
                user_agent=self.user_agent,
            )
            print("[Reddit] Connected successfully")
            return True
        except Exception as e:
            print(f"[Reddit] Connection failed: {e}")
            return False

    def collect(self, symbols, company_names, limit=50):
        """
        Collect mentions of stocks from Reddit.
        Returns list of (symbol, source, text) tuples.
        """
        if not self.reddit:
            print("[Reddit] Not connected. Call connect() first.")
            return []

        mentions = []
        for sub_name in self.SUBREDDITS:
            try:
                subreddit = self.reddit.subreddit(sub_name)
                for post in subreddit.hot(limit=limit):
                    text = f"{post.title} {post.selftext}"
                    for sym, name in company_names.items():
                        if sym in symbols and (sym in text.upper() or name.lower() in text.lower()):
                            mentions.append((sym, f"r/{sub_name}", text[:500]))
                print(f"[Reddit] Collected from r/{sub_name}")
            except Exception as e:
                print(f"[Reddit] Error on r/{sub_name}: {e}")

        return mentions


class NewsCollector:
    """Collect stock mentions from financial news via NewsAPI."""

    def __init__(self, api_key):
        self.api_key = api_key

    def collect(self, symbols, company_names):
        """
        Collect news articles mentioning each stock.
        Returns list of (symbol, source, text) tuples.
        """
        import requests

        mentions = []
        for sym, name in company_names.items():
            if sym not in symbols:
                continue
            try:
                url = "https://newsapi.org/v2/everything"
                params = {
                    "q": f'"{name}" OR "{sym}" stock',
                    "language": "en",
                    "sortBy": "publishedAt",
                    "pageSize": 20,
                    "apiKey": self.api_key,
                }
                resp = requests.get(url, params=params, timeout=10)
                data = resp.json()

                if data.get("status") == "ok":
                    for article in data.get("articles", []):
                        source_name = article.get("source", {}).get("name", "unknown")
                        text = f"{article.get('title', '')} {article.get('description', '')}"
                        mentions.append((sym, source_name, text[:500]))

                print(f"[News] Collected {len(data.get('articles', []))} articles for {sym}")
            except Exception as e:
                print(f"[News] Error for {sym}: {e}")

        return mentions


class GoogleTrendsCollector:
    """Collect trending data from Google Trends."""

    def collect(self, symbols, company_names):
        """
        Get Google Trends interest scores for each stock.
        Returns dict: { "AAPL": 85, "TSLA": 92, ... } (0-100 scale)
        """
        try:
            from pytrends.request import TrendReq
            pytrends = TrendReq(hl='en-US', tz=360)

            # Google Trends allows max 5 keywords at a time
            results = {}
            sym_list = [s for s in symbols if s in company_names]

            for i in range(0, len(sym_list), 5):
                batch = sym_list[i:i+5]
                keywords = [company_names[s] for s in batch]
                pytrends.build_payload(keywords, timeframe='now 7-d')
                data = pytrends.interest_over_time()

                if not data.empty:
                    for sym, name in zip(batch, keywords):
                        if name in data.columns:
                            results[sym] = int(data[name].iloc[-1])

                print(f"[Trends] Collected batch: {batch}")
                time.sleep(1)  # Be nice to Google

            return results
        except Exception as e:
            print(f"[Trends] Error: {e}")
            return {}


# ============================================================
# MAIN RUNNER — Ties everything together
# ============================================================

def run_trendscore(config=None):
    """
    Run one full cycle of TrendScore data collection and scoring.

    This is the main function you'd call on a schedule (e.g., every hour).
    """
    config = config or CONFIG

    engine = TrendScore()
    symbols = config["symbols"]
    names = config["company_names"]

    print("\n" + "=" * 60)
    print(f"  TrendScore Run — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # --- Collect from Reddit ---
    if config["reddit_client_id"] != "YOUR_REDDIT_CLIENT_ID":
        reddit = RedditCollector(
            config["reddit_client_id"],
            config["reddit_client_secret"],
            config["reddit_user_agent"],
        )
        if reddit.connect():
            for sym, source, text in reddit.collect(symbols, names):
                engine.add_mention(sym, source, text)
    else:
        print("[Reddit] Skipped — no API key set")

    # --- Collect from News ---
    if config["newsapi_key"] != "YOUR_NEWSAPI_KEY":
        news = NewsCollector(config["newsapi_key"])
        for sym, source, text in news.collect(symbols, names):
            engine.add_mention(sym, source, text)
    else:
        print("[News] Skipped — no API key set")

    # --- Collect from Google Trends ---
    try:
        trends = GoogleTrendsCollector()
        trend_scores = trends.collect(symbols, names)
        # Convert trend interest into "mentions" with neutral sentiment
        for sym, interest in trend_scores.items():
            # More Google interest = more synthetic mentions
            for _ in range(interest // 10):
                engine.add_mention(sym, "google_trends", f"{names.get(sym, sym)} trending on Google", 0.1)
    except:
        print("[Trends] Skipped — pytrends not installed")

    # --- Calculate and display scores ---
    print("\n" + "-" * 60)
    print("  TRENDSCORE RANKINGS")
    print("-" * 60)

    rankings = engine.rank_all(symbols)

    for i, score in enumerate(rankings):
        bar = "█" * int(score["total_score"] / 5) + "░" * (20 - int(score["total_score"] / 5))
        sentiment_emoji = "🟢" if score["avg_sentiment"] > 0.1 else ("🔴" if score["avg_sentiment"] < -0.1 else "⚪")
        print(f"\n  #{i+1}  {score['symbol']:6s}  Score: {score['total_score']:5.1f}/100  {bar}")
        print(f"       Mentions: {score['mention_count']:3d}  |  Sentiment: {sentiment_emoji} {score['avg_sentiment']:+.3f}  |  Spike: {score['spike_score']:.0f}")
        print(f"       Volume: {score['volume_score']:.0f}  |  Source Quality: {score['source_quality_score']:.0f}")

    # Save to file
    engine.snapshot_history()
    output = {
        "timestamp": datetime.now().isoformat(),
        "rankings": rankings,
    }
    with open("trendscore_latest.json", "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\n  Saved to trendscore_latest.json")

    return rankings


# ============================================================
# DEMO MODE — Run with fake data to test the engine
# ============================================================

def run_demo():
    """
    Run TrendScore with simulated data so you can see how the
    scoring works before connecting real APIs.
    """
    import random

    engine = TrendScore()
    symbols = CONFIG["symbols"]
    names = CONFIG["company_names"]

    print("\n" + "=" * 60)
    print("  TrendScore DEMO — Simulated Data")
    print("=" * 60)

    # Simulate different levels of buzz for each stock
    buzz_levels = {
        "AAPL": {"mentions": 45, "tier1_pct": 0.3, "sentiment": 0.2},
        "MSFT": {"mentions": 30, "tier1_pct": 0.25, "sentiment": 0.15},
        "NVDA": {"mentions": 80, "tier1_pct": 0.4, "sentiment": 0.35},   # Hot AI stock
        "AMZN": {"mentions": 35, "tier1_pct": 0.2, "sentiment": 0.1},
        "GOOGL": {"mentions": 25, "tier1_pct": 0.15, "sentiment": -0.05},
        "META": {"mentions": 55, "tier1_pct": 0.2, "sentiment": 0.25},
        "BRK.B": {"mentions": 10, "tier1_pct": 0.5, "sentiment": 0.3},   # Few mentions but high quality
        "TSLA": {"mentions": 90, "tier1_pct": 0.1, "sentiment": 0.0},    # Lots of noise, mixed sentiment
        "AVGO": {"mentions": 20, "tier1_pct": 0.35, "sentiment": 0.2},
        "JPM": {"mentions": 15, "tier1_pct": 0.4, "sentiment": 0.1},
    }

    # Add some historical data for spike detection
    for sym in symbols:
        engine.history[sym] = [
            random.randint(10, 40) for _ in range(7)
        ]

    # Generate simulated mentions
    tier1_sources = ["Bloomberg", "CNBC", "Reuters", "WSJ", "MarketWatch"]
    tier2_sources = ["r/wallstreetbets", "r/stocks", "r/investing"]
    tier3_sources = ["Reddit", "Twitter", "General News"]

    positive_phrases = [
        "looking strong", "beat expectations", "bullish outlook",
        "analysts upgrade", "revenue growth", "strong quarter",
        "market leader", "innovation driving growth",
    ]
    negative_phrases = [
        "missed estimates", "facing headwinds", "regulatory concerns",
        "declining margins", "competitive pressure", "risk of downturn",
    ]
    neutral_phrases = [
        "trading sideways", "unchanged outlook", "market update",
        "quarterly report due", "sector analysis",
    ]

    for sym in symbols:
        buzz = buzz_levels.get(sym, {"mentions": 20, "tier1_pct": 0.2, "sentiment": 0.0})
        company = names[sym]

        for _ in range(buzz["mentions"]):
            # Pick source tier based on distribution
            r = random.random()
            if r < buzz["tier1_pct"]:
                source = random.choice(tier1_sources)
            elif r < buzz["tier1_pct"] + 0.3:
                source = random.choice(tier2_sources)
            else:
                source = random.choice(tier3_sources)

            # Generate text with sentiment bias
            if random.random() < (0.5 + buzz["sentiment"] / 2):
                phrase = random.choice(positive_phrases)
            elif random.random() < 0.3:
                phrase = random.choice(negative_phrases)
            else:
                phrase = random.choice(neutral_phrases)

            text = f"{company} {phrase} — {source} report"
            engine.add_mention(sym, source, text)

    # Calculate and display
    print("\n" + "-" * 60)
    print("  TRENDSCORE RANKINGS (Simulated)")
    print("-" * 60)

    rankings = engine.rank_all(symbols)

    for i, score in enumerate(rankings):
        bar = "█" * int(score["total_score"] / 5) + "░" * (20 - int(score["total_score"] / 5))
        sentiment_emoji = "🟢" if score["avg_sentiment"] > 0.1 else ("🔴" if score["avg_sentiment"] < -0.1 else "⚪")

        print(f"\n  #{i+1}  {score['symbol']:6s}  Score: {score['total_score']:5.1f}/100  {bar}")
        print(f"       Mentions: {score['mention_count']:3d}  |  Sentiment: {sentiment_emoji} {score['avg_sentiment']:+.3f}  |  Spike: {score['spike_score']:.0f}")

    print("\n" + "-" * 60)
    print("  TOP PICK: " + rankings[0]["symbol"] + f" (Score: {rankings[0]['total_score']})")
    print("  AVOID:    " + rankings[-1]["symbol"] + f" (Score: {rankings[-1]['total_score']})")
    print("-" * 60)

    return rankings


# ============================================================
# RUN
# ============================================================
if __name__ == "__main__":
    import sys

    if "--demo" in sys.argv:
        run_demo()
    else:
        # Check if API keys are set
        if CONFIG["reddit_client_id"] == "YOUR_REDDIT_CLIENT_ID" and CONFIG["newsapi_key"] == "YOUR_NEWSAPI_KEY":
            print("No API keys set yet. Running demo mode...")
            print("To use real data, set your keys in CONFIG at the top of this file.")
            print("")
            run_demo()
        else:
            run_trendscore()
