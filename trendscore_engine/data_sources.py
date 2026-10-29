#!/usr/bin/env python3
"""
Multi-Source Data Collector — 10 Real-Time Data Sources
========================================================

Collects trending stock data from ALL of these sources:

SOURCE                  | DATA TYPE          | FREE TIER              | API KEY NEEDED
------------------------|--------------------|------------------------|---------------
1. Yahoo Finance        | Price/Volume/Stats | Unlimited (yfinance)   | NO
2. Reddit (PRAW)        | Social mentions    | 100 req/min            | YES (free)
3. Google Trends        | Search interest    | Unlimited (pytrends)   | NO
4. NewsAPI              | News articles      | 500 req/day            | YES (free)
5. Marketaux            | News + Sentiment   | 100 req/day            | YES (free)
6. Finnhub              | Market data + News | 60 req/min             | YES (free)
7. Alpha Vantage        | Price/Technicals   | 25 req/day             | YES (free)
8. Financial Mod. Prep  | Gainers/Losers     | 250 req/day            | YES (free)
9. StockTwits           | Social sentiment   | Public trending feed   | NO (public)
10. Polygon.io (Massive)| Price/Volume       | 5 req/min              | YES (free)

SETUP:
    pip install yfinance pytrends praw requests textblob pandas numpy

    Then set API keys in api_keys.json (auto-generated on first run)
"""

import json
import os
import time
import re
import math
from datetime import datetime, timedelta
from collections import defaultdict, Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

# ============================================================
# API KEY MANAGEMENT
# ============================================================

API_KEYS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "api_keys.json")

DEFAULT_KEYS = {
    "reddit": {
        "client_id": "",
        "client_secret": "",
        "user_agent": "TrendScore/2.0",
        "_signup_url": "https://www.reddit.com/prefs/apps → Create App → Script type",
        "_free": True,
    },
    "newsapi": {
        "api_key": "",
        "_signup_url": "https://newsapi.org/register",
        "_free_limit": "500 requests/day",
        "_free": True,
    },
    "marketaux": {
        "api_key": "",
        "_signup_url": "https://www.marketaux.com/register",
        "_free_limit": "100 requests/day",
        "_free": True,
    },
    "finnhub": {
        "api_key": "",
        "_signup_url": "https://finnhub.io/register",
        "_free_limit": "60 requests/min",
        "_free": True,
    },
    "alpha_vantage": {
        "api_key": "",
        "_signup_url": "https://www.alphavantage.co/support/#api-key",
        "_free_limit": "25 requests/day",
        "_free": True,
    },
    "fmp": {
        "api_key": "",
        "_signup_url": "https://site.financialmodelingprep.com/developer/docs",
        "_free_limit": "250 requests/day",
        "_free": True,
    },
    "polygon": {
        "api_key": "",
        "_signup_url": "https://polygon.io/dashboard/signup",
        "_free_limit": "5 requests/min",
        "_free": True,
    },
}


def load_api_keys():
    """Load API keys from file, or create template if missing."""
    if os.path.exists(API_KEYS_FILE):
        with open(API_KEYS_FILE, "r") as f:
            keys = json.load(f)
        # Merge with defaults (in case new sources were added)
        for source, defaults in DEFAULT_KEYS.items():
            if source not in keys:
                keys[source] = defaults
        return keys
    else:
        # Create template
        with open(API_KEYS_FILE, "w") as f:
            json.dump(DEFAULT_KEYS, f, indent=2)
        print(f"\n[API Keys] Created template at: {API_KEYS_FILE}")
        print("[API Keys] Fill in your keys and re-run. All APIs are FREE to sign up.\n")
        return DEFAULT_KEYS


def get_key(keys, source, field="api_key"):
    """Get an API key, return None if empty."""
    val = keys.get(source, {}).get(field, "")
    return val if val and not val.startswith("YOUR_") else None


# ============================================================
# SOURCE 1: YAHOO FINANCE (No API key needed)
# ============================================================

class YahooFinanceSource:
    """
    Fetches real-time price data, volume, moving averages,
    top gainers/losers, and most active stocks.
    """
    name = "Yahoo Finance"
    needs_key = False

    def __init__(self):
        self.yf = None
        try:
            import yfinance
            self.yf = yfinance
            self.available = True
        except ImportError:
            self.available = False
            print("[Yahoo] yfinance not installed. Run: pip install yfinance")

    def fetch_prices(self, tickers, period="1mo"):
        """Fetch price/volume data for a list of tickers."""
        if not self.available:
            return {}

        results = {}
        batch_size = 50

        for i in range(0, len(tickers), batch_size):
            batch = tickers[i:i + batch_size]
            try:
                data = self.yf.download(
                    " ".join(batch), period=period,
                    group_by="ticker", auto_adjust=True,
                    threads=True, progress=False
                )
                for ticker in batch:
                    try:
                        df = data[ticker] if len(batch) > 1 else data
                        if df is not None and not df.empty:
                            closes = df["Close"].dropna()
                            volumes = df["Volume"].dropna()
                            if len(closes) >= 2:
                                results[ticker] = {
                                    "price": float(closes.iloc[-1]),
                                    "open_today": float(df["Open"].iloc[-1]),
                                    "volume": int(volumes.iloc[-1]),
                                    "avg_volume_20d": int(volumes.tail(20).mean()),
                                    "price_5d_ago": float(closes.iloc[-5]) if len(closes) >= 5 else float(closes.iloc[0]),
                                    "price_20d_ago": float(closes.iloc[0]),
                                    "high_52w": float(closes.max()),
                                    "low_52w": float(closes.min()),
                                    "volatility": float(closes.pct_change().std() * 100),
                                    "prices": [float(x) for x in closes.tail(30).tolist()],
                                }
                    except:
                        pass
                print(f"  [Yahoo] Fetched {min(i+batch_size, len(tickers))}/{len(tickers)}")
            except Exception as e:
                print(f"  [Yahoo] Batch error: {e}")

        return results

    def fetch_trending(self):
        """Fetch Yahoo Finance trending tickers."""
        if not self.available:
            return []
        try:
            import yfinance as yf
            trending = yf.Tickers("^GSPC").tickers  # Market trending
            return []  # yfinance doesn't have direct trending API
        except:
            return []


# ============================================================
# SOURCE 2: REDDIT (Free API key)
# ============================================================

class RedditSource:
    """
    Scans finance subreddits for stock mentions.
    Captures: mention count, upvotes, sentiment, source quality.
    """
    name = "Reddit"
    needs_key = True

    SUBREDDITS = [
        "wallstreetbets", "stocks", "investing", "stockmarket",
        "options", "pennystocks", "Daytrading", "SecurityAnalysis",
        "dividends", "ValueInvesting", "growth_investing",
        "thetagang", "algotrading", "FluentInFinance",
    ]

    # Regex to find stock tickers in text (e.g., $AAPL or AAPL)
    TICKER_PATTERN = re.compile(r'(?:\$([A-Z]{1,5}))|(?:\b([A-Z]{2,5})\b)')

    # Common words that look like tickers but aren't
    TICKER_BLACKLIST = {
        "THE", "AND", "FOR", "ARE", "BUT", "NOT", "YOU", "ALL",
        "CAN", "HER", "WAS", "ONE", "OUR", "OUT", "HAS", "HIS",
        "HOW", "ITS", "MAY", "NEW", "NOW", "OLD", "SEE", "WAY",
        "WHO", "DID", "GET", "HIM", "LET", "SAY", "SHE", "TOO",
        "USE", "CEO", "CFO", "IPO", "ETF", "ATH", "DCA", "RSI",
        "PE", "EPS", "GDP", "CPI", "FED", "SEC", "IMO", "LOL",
        "DD", "WSB", "ITM", "OTM", "IV", "YOLO", "HODL", "APE",
        "RIP", "BEAR", "BULL", "LONG", "SHORT", "PUT", "CALL",
        "BUY", "SELL", "HOLD", "PUMP", "DUMP", "DIP", "MOON",
        "EDIT", "TLDR", "LINK", "POST", "JUST", "LIKE", "WILL",
        "BEEN", "HAVE", "THEY", "THIS", "THAT", "WITH", "FROM",
        "WHEN", "WHAT", "SOME", "EACH", "MUCH", "VERY", "ALSO",
        "THAN", "OVER", "SUCH", "TAKE", "YEAR", "THEM", "SAME",
        "DOWN", "WELL", "BACK", "BEEN", "THEN", "MORE", "MANY",
        "MOST", "ONLY", "COME", "MADE", "FIND", "HERE", "KNOW",
        "WANT", "GIVE", "MOST", "INTO", "MAKE", "LOOK", "GOOD",
        "BEST", "EVER", "EVEN", "KEEP", "REAL", "CASH", "DEBT",
        "LOSS", "GAIN", "RISK", "FREE", "HOPE", "DONE", "HUGE",
        "GOES", "ELSE", "HIGH", "LOW", "SAFE", "FUND", "BOND",
        "RATE", "WEEK", "NEXT", "LAST", "PART", "IDEA", "PLAY",
        "MOVE", "WORK", "HELP", "STILL", "EVERY", "TOTAL", "STOCK",
    }

    def __init__(self, keys):
        self.reddit = None
        client_id = get_key(keys, "reddit", "client_id")
        client_secret = get_key(keys, "reddit", "client_secret")
        user_agent = keys.get("reddit", {}).get("user_agent", "TrendScore/2.0")

        if client_id and client_secret:
            try:
                import praw
                self.reddit = praw.Reddit(
                    client_id=client_id,
                    client_secret=client_secret,
                    user_agent=user_agent,
                )
                self.available = True
                print("[Reddit] Connected")
            except ImportError:
                self.available = False
                print("[Reddit] praw not installed. Run: pip install praw")
            except Exception as e:
                self.available = False
                print(f"[Reddit] Connection failed: {e}")
        else:
            self.available = False
            print("[Reddit] No API key — skipping")

    def collect_mentions(self, known_tickers=None, limit_per_sub=100):
        """
        Scan subreddits and count stock mentions.
        Returns: { ticker: { mentions, upvotes, comments, sentiment_sum, posts[] } }
        """
        if not self.available:
            return {}

        mentions = defaultdict(lambda: {
            "mentions": 0, "upvotes": 0, "comments": 0,
            "sentiment_sum": 0, "posts": [], "sources": set(),
        })

        for sub_name in self.SUBREDDITS:
            try:
                subreddit = self.reddit.subreddit(sub_name)
                for post in subreddit.hot(limit=limit_per_sub):
                    text = f"{post.title} {post.selftext}"
                    tickers_found = self._extract_tickers(text, known_tickers)

                    for ticker in tickers_found:
                        m = mentions[ticker]
                        m["mentions"] += 1
                        m["upvotes"] += post.score
                        m["comments"] += post.num_comments
                        m["sources"].add(f"r/{sub_name}")
                        m["sentiment_sum"] += self._quick_sentiment(text)
                        if len(m["posts"]) < 5:
                            m["posts"].append({
                                "title": post.title[:200],
                                "score": post.score,
                                "sub": sub_name,
                            })

                print(f"  [Reddit] Scanned r/{sub_name}")
            except Exception as e:
                print(f"  [Reddit] Error r/{sub_name}: {e}")

        # Convert sets to lists for JSON
        for ticker in mentions:
            mentions[ticker]["sources"] = list(mentions[ticker]["sources"])

        return dict(mentions)

    def _extract_tickers(self, text, known_tickers=None):
        """Extract stock tickers from text."""
        found = set()
        for match in self.TICKER_PATTERN.finditer(text):
            ticker = match.group(1) or match.group(2)
            if ticker and ticker not in self.TICKER_BLACKLIST:
                if known_tickers is None or ticker in known_tickers:
                    found.add(ticker)
        return found

    def _quick_sentiment(self, text):
        """Quick sentiment score -1 to +1."""
        try:
            from textblob import TextBlob
            return TextBlob(text[:500]).sentiment.polarity
        except:
            positive = ["buy","bull","up","grow","profit","beat","surge","rally","moon","rocket","calls","long"]
            negative = ["sell","bear","down","crash","loss","miss","drop","fall","puts","short","dump","rip"]
            text_l = text.lower()
            p = sum(1 for w in positive if w in text_l)
            n = sum(1 for w in negative if w in text_l)
            t = p + n
            return (p - n) / t if t > 0 else 0


# ============================================================
# SOURCE 3: GOOGLE TRENDS (No API key needed)
# ============================================================

class GoogleTrendsSource:
    """
    Gets search interest scores from Google Trends.
    Shows how much people are searching for a stock.
    """
    name = "Google Trends"
    needs_key = False

    def __init__(self):
        try:
            from pytrends.request import TrendReq
            self.pytrends = TrendReq(hl='en-US', tz=360)
            self.available = True
            print("[Trends] Connected")
        except ImportError:
            self.available = False
            print("[Trends] pytrends not installed. Run: pip install pytrends")

    def fetch_interest(self, tickers_with_names, timeframe='now 7-d'):
        """
        Get Google Trends interest for stock tickers.
        tickers_with_names: { "AAPL": "Apple stock", "TSLA": "Tesla stock", ... }
        Returns: { ticker: interest_score (0-100) }
        """
        if not self.available:
            return {}

        results = {}
        items = list(tickers_with_names.items())

        # Google Trends allows max 5 keywords at a time
        for i in range(0, len(items), 5):
            batch = items[i:i + 5]
            keywords = [f"{name} stock" for _, name in batch]

            try:
                self.pytrends.build_payload(keywords, timeframe=timeframe)
                data = self.pytrends.interest_over_time()

                if not data.empty:
                    for (ticker, name), keyword in zip(batch, keywords):
                        col = keyword if keyword in data.columns else None
                        if col:
                            results[ticker] = int(data[col].iloc[-1])

                time.sleep(0.5)  # Rate limit
            except Exception as e:
                print(f"  [Trends] Error: {e}")
                time.sleep(2)

        print(f"  [Trends] Got interest for {len(results)} stocks")
        return results

    def get_trending_searches(self):
        """Get currently trending searches (may include stocks)."""
        if not self.available:
            return []
        try:
            trending = self.pytrends.trending_searches(pn='united_states')
            return trending[0].tolist()[:20] if not trending.empty else []
        except:
            return []


# ============================================================
# SOURCE 4: NEWS API (Free key)
# ============================================================

class NewsAPISource:
    """
    Fetches financial news articles with sentiment.
    500 requests/day on free tier.
    """
    name = "NewsAPI"
    needs_key = True

    def __init__(self, keys):
        self.api_key = get_key(keys, "newsapi")
        self.available = bool(self.api_key)
        if self.available:
            print("[NewsAPI] Connected")
        else:
            print("[NewsAPI] No API key — skipping")

    def fetch_news(self, tickers_with_names, max_articles=20):
        """
        Fetch news for each stock.
        Returns: { ticker: { count, sources[], sentiment_avg, headlines[] } }
        """
        if not self.available:
            return {}

        import requests
        results = {}

        for ticker, name in list(tickers_with_names.items())[:50]:  # Limit to save quota
            try:
                resp = requests.get(
                    "https://newsapi.org/v2/everything",
                    params={
                        "q": f'"{name}" OR "{ticker}" stock',
                        "language": "en",
                        "sortBy": "publishedAt",
                        "pageSize": max_articles,
                        "apiKey": self.api_key,
                    },
                    timeout=10,
                )
                data = resp.json()

                if data.get("status") == "ok":
                    articles = data.get("articles", [])
                    sources = set()
                    sentiments = []
                    headlines = []

                    for a in articles:
                        source = a.get("source", {}).get("name", "unknown")
                        sources.add(source)
                        text = f"{a.get('title', '')} {a.get('description', '')}"
                        sent = self._sentiment(text)
                        sentiments.append(sent)
                        headlines.append({
                            "title": a.get("title", "")[:150],
                            "source": source,
                            "sentiment": round(sent, 3),
                        })

                    results[ticker] = {
                        "count": len(articles),
                        "sources": list(sources),
                        "sentiment_avg": round(sum(sentiments) / max(len(sentiments), 1), 3),
                        "headlines": headlines[:5],
                    }

                time.sleep(0.2)
            except Exception as e:
                pass

        print(f"  [NewsAPI] Got news for {len(results)} stocks")
        return results

    def _sentiment(self, text):
        try:
            from textblob import TextBlob
            return TextBlob(text[:500]).sentiment.polarity
        except:
            return 0


# ============================================================
# SOURCE 5: MARKETAUX (Free key — News + Sentiment)
# ============================================================

class MarketauxSource:
    """
    Financial news with built-in entity-level sentiment scoring.
    100 requests/day on free tier.
    """
    name = "Marketaux"
    needs_key = True

    def __init__(self, keys):
        self.api_key = get_key(keys, "marketaux")
        self.available = bool(self.api_key)
        if self.available:
            print("[Marketaux] Connected")
        else:
            print("[Marketaux] No API key — skipping")

    def fetch_sentiment(self, tickers, limit=50):
        """
        Fetch news + sentiment for tickers.
        Returns: { ticker: { sentiment, relevance, news_count, highlights[] } }
        """
        if not self.available:
            return {}

        import requests
        results = {}

        # Marketaux lets you query multiple symbols at once
        for i in range(0, min(len(tickers), 200), 10):
            batch = tickers[i:i + 10]
            try:
                resp = requests.get(
                    "https://api.marketaux.com/v1/news/all",
                    params={
                        "symbols": ",".join(batch),
                        "filter_entities": "true",
                        "language": "en",
                        "limit": limit,
                        "api_token": self.api_key,
                    },
                    timeout=15,
                )
                data = resp.json()

                for article in data.get("data", []):
                    for entity in article.get("entities", []):
                        sym = entity.get("symbol", "")
                        if sym in batch:
                            if sym not in results:
                                results[sym] = {
                                    "sentiment": 0, "relevance": 0,
                                    "news_count": 0, "highlights": [],
                                }
                            r = results[sym]
                            r["news_count"] += 1
                            r["sentiment"] += entity.get("sentiment_score", 0)
                            r["relevance"] += entity.get("relevance_score", 0)
                            if len(r["highlights"]) < 3:
                                r["highlights"].append(article.get("title", "")[:150])

                time.sleep(1)
            except Exception as e:
                print(f"  [Marketaux] Error: {e}")

        # Average out sentiment
        for sym in results:
            n = results[sym]["news_count"]
            if n > 0:
                results[sym]["sentiment"] = round(results[sym]["sentiment"] / n, 3)
                results[sym]["relevance"] = round(results[sym]["relevance"] / n, 3)

        print(f"  [Marketaux] Got sentiment for {len(results)} stocks")
        return results


# ============================================================
# SOURCE 6: FINNHUB (Free key)
# ============================================================

class FinnhubSource:
    """
    Real-time market data, company news, and social sentiment.
    60 requests/min on free tier.
    """
    name = "Finnhub"
    needs_key = True

    def __init__(self, keys):
        self.api_key = get_key(keys, "finnhub")
        self.available = bool(self.api_key)
        if self.available:
            print("[Finnhub] Connected")
        else:
            print("[Finnhub] No API key — skipping")

    def fetch_social_sentiment(self, tickers):
        """Fetch social sentiment from Finnhub."""
        if not self.available:
            return {}

        import requests
        results = {}

        for ticker in tickers[:50]:  # Rate limit
            try:
                resp = requests.get(
                    "https://finnhub.io/api/v1/stock/social-sentiment",
                    params={"symbol": ticker, "from": (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d"), "to": datetime.now().strftime("%Y-%m-%d"), "token": self.api_key},
                    timeout=10,
                )
                data = resp.json()
                reddit_data = data.get("reddit", [])
                twitter_data = data.get("twitter", [])

                total_mentions = sum(d.get("mention", 0) for d in reddit_data + twitter_data)
                total_positive = sum(d.get("positiveScore", 0) for d in reddit_data + twitter_data)
                total_negative = sum(d.get("negativeScore", 0) for d in reddit_data + twitter_data)

                if total_mentions > 0:
                    results[ticker] = {
                        "mentions": total_mentions,
                        "positive_score": round(total_positive, 3),
                        "negative_score": round(total_negative, 3),
                        "net_sentiment": round(total_positive - total_negative, 3),
                    }

                time.sleep(0.5)
            except:
                pass

        print(f"  [Finnhub] Got social sentiment for {len(results)} stocks")
        return results

    def fetch_recommendations(self, tickers):
        """Fetch analyst recommendations."""
        if not self.available:
            return {}

        import requests
        results = {}

        for ticker in tickers[:30]:
            try:
                resp = requests.get(
                    "https://finnhub.io/api/v1/stock/recommendation",
                    params={"symbol": ticker, "token": self.api_key},
                    timeout=10,
                )
                data = resp.json()
                if data:
                    latest = data[0]
                    results[ticker] = {
                        "buy": latest.get("buy", 0),
                        "hold": latest.get("hold", 0),
                        "sell": latest.get("sell", 0),
                        "strong_buy": latest.get("strongBuy", 0),
                        "strong_sell": latest.get("strongSell", 0),
                    }
                time.sleep(0.5)
            except:
                pass

        print(f"  [Finnhub] Got recommendations for {len(results)} stocks")
        return results


# ============================================================
# SOURCE 7: ALPHA VANTAGE (Free key)
# ============================================================

class AlphaVantageSource:
    """
    Technical indicators and top gainers/losers.
    25 requests/day on free tier (use wisely).
    """
    name = "Alpha Vantage"
    needs_key = True

    def __init__(self, keys):
        self.api_key = get_key(keys, "alpha_vantage")
        self.available = bool(self.api_key)
        if self.available:
            print("[AlphaVantage] Connected")
        else:
            print("[AlphaVantage] No API key — skipping")

    def fetch_top_gainers_losers(self):
        """
        Get top gainers, losers, and most active stocks.
        This is GOLD for dynamic discovery — shows what's trending RIGHT NOW.
        """
        if not self.available:
            return {"gainers": [], "losers": [], "most_active": []}

        import requests
        try:
            resp = requests.get(
                "https://www.alphavantage.co/query",
                params={"function": "TOP_GAINERS_LOSERS", "apikey": self.api_key},
                timeout=15,
            )
            data = resp.json()
            return {
                "gainers": [
                    {"ticker": s["ticker"], "price": float(s.get("price", 0)),
                     "change_pct": float(s.get("change_percentage", "0%").replace("%", "")),
                     "volume": int(s.get("volume", 0))}
                    for s in data.get("top_gainers", [])[:20]
                ],
                "losers": [
                    {"ticker": s["ticker"], "price": float(s.get("price", 0)),
                     "change_pct": float(s.get("change_percentage", "0%").replace("%", "")),
                     "volume": int(s.get("volume", 0))}
                    for s in data.get("top_losers", [])[:20]
                ],
                "most_active": [
                    {"ticker": s["ticker"], "price": float(s.get("price", 0)),
                     "change_pct": float(s.get("change_percentage", "0%").replace("%", "")),
                     "volume": int(s.get("volume", 0))}
                    for s in data.get("most_actively_traded", [])[:20]
                ],
            }
        except Exception as e:
            print(f"  [AlphaVantage] Error: {e}")
            return {"gainers": [], "losers": [], "most_active": []}


# ============================================================
# SOURCE 8: FINANCIAL MODELING PREP (Free key)
# ============================================================

class FMPSource:
    """
    Stock screener, gainers/losers, sector performance.
    250 requests/day on free tier.
    """
    name = "Financial Modeling Prep"
    needs_key = True
    BASE = "https://financialmodelingprep.com/api/v3"

    def __init__(self, keys):
        self.api_key = get_key(keys, "fmp")
        self.available = bool(self.api_key)
        if self.available:
            print("[FMP] Connected")
        else:
            print("[FMP] No API key — skipping")

    def fetch_gainers_losers(self):
        """Top gainers and losers — great for dynamic discovery."""
        if not self.available:
            return {"gainers": [], "losers": []}

        import requests
        results = {"gainers": [], "losers": []}
        try:
            for endpoint, key in [("stock_market/gainers", "gainers"), ("stock_market/losers", "losers")]:
                resp = requests.get(f"{self.BASE}/{endpoint}", params={"apikey": self.api_key}, timeout=10)
                data = resp.json()
                results[key] = [
                    {"ticker": s["symbol"], "name": s.get("name", ""),
                     "price": s.get("price", 0), "change_pct": s.get("changesPercentage", 0),
                     "volume": s.get("volume", 0)}
                    for s in (data if isinstance(data, list) else [])[:30]
                ]
        except Exception as e:
            print(f"  [FMP] Error: {e}")
        print(f"  [FMP] Got {len(results['gainers'])} gainers, {len(results['losers'])} losers")
        return results

    def fetch_most_active(self):
        """Most actively traded stocks."""
        if not self.available:
            return []
        import requests
        try:
            resp = requests.get(f"{self.BASE}/stock_market/actives", params={"apikey": self.api_key}, timeout=10)
            data = resp.json()
            return [{"ticker": s["symbol"], "name": s.get("name", ""), "volume": s.get("volume", 0), "change_pct": s.get("changesPercentage", 0)} for s in (data if isinstance(data, list) else [])[:30]]
        except:
            return []

    def fetch_sector_performance(self):
        """Sector-level performance."""
        if not self.available:
            return {}
        import requests
        try:
            resp = requests.get(f"{self.BASE}/sector-performance", params={"apikey": self.api_key}, timeout=10)
            data = resp.json()
            return {s["sector"]: float(s.get("changesPercentage", "0%").replace("%", "")) for s in (data if isinstance(data, list) else [])}
        except:
            return {}


# ============================================================
# SOURCE 9: STOCKTWITS (No API key for trending)
# ============================================================

class StockTwitsSource:
    """
    Social sentiment from StockTwits — the Twitter of stocks.
    Trending endpoint is public (no auth needed).
    """
    name = "StockTwits"
    needs_key = False

    def __init__(self):
        self.available = True
        print("[StockTwits] Connected (public API)")

    def fetch_trending(self):
        """Fetch trending tickers from StockTwits."""
        import requests
        try:
            resp = requests.get(
                "https://api.stocktwits.com/api/2/trending/symbols.json",
                timeout=10,
            )
            data = resp.json()
            symbols = data.get("symbols", [])
            return [
                {
                    "ticker": s.get("symbol", ""),
                    "name": s.get("title", ""),
                    "watchlist_count": s.get("watchlist_count", 0),
                }
                for s in symbols
            ]
        except Exception as e:
            print(f"  [StockTwits] Error: {e}")
            return []

    def fetch_sentiment(self, ticker):
        """Fetch sentiment for a specific ticker."""
        import requests
        try:
            resp = requests.get(
                f"https://api.stocktwits.com/api/2/streams/symbol/{ticker}.json",
                timeout=10,
            )
            data = resp.json()
            messages = data.get("messages", [])
            bullish = sum(1 for m in messages if m.get("entities", {}).get("sentiment", {}).get("basic") == "Bullish")
            bearish = sum(1 for m in messages if m.get("entities", {}).get("sentiment", {}).get("basic") == "Bearish")
            total = bullish + bearish
            return {
                "bullish": bullish,
                "bearish": bearish,
                "total_messages": len(messages),
                "sentiment_ratio": round(bullish / total, 3) if total > 0 else 0.5,
            }
        except:
            return None


# ============================================================
# SOURCE 10: POLYGON.IO / MASSIVE (Free key)
# ============================================================

class PolygonSource:
    """
    Market data, gainers/losers, snapshot data.
    5 requests/min on free tier.
    """
    name = "Polygon.io"
    needs_key = True

    def __init__(self, keys):
        self.api_key = get_key(keys, "polygon")
        self.available = bool(self.api_key)
        if self.available:
            print("[Polygon] Connected")
        else:
            print("[Polygon] No API key — skipping")

    def fetch_gainers_losers(self, direction="gainers"):
        """Top gainers or losers from Polygon snapshot."""
        if not self.available:
            return []

        import requests
        try:
            resp = requests.get(
                f"https://api.polygon.io/v2/snapshot/locale/us/markets/stocks/{direction}",
                params={"apiKey": self.api_key},
                timeout=15,
            )
            data = resp.json()
            return [
                {
                    "ticker": t.get("ticker", ""),
                    "price": t.get("day", {}).get("c", 0),
                    "change_pct": t.get("todaysChangePerc", 0),
                    "volume": t.get("day", {}).get("v", 0),
                    "prev_close": t.get("prevDay", {}).get("c", 0),
                }
                for t in data.get("tickers", [])[:20]
            ]
        except Exception as e:
            print(f"  [Polygon] Error: {e}")
            return []


# ============================================================
# MASTER COLLECTOR — Combines all sources
# ============================================================

class MasterCollector:
    """
    Orchestrates all 10 data sources into a unified data pipeline.
    """

    def __init__(self):
        self.keys = load_api_keys()
        print("\n" + "=" * 60)
        print("  Initializing 10 Data Sources")
        print("=" * 60)

        # Initialize all sources
        self.yahoo = YahooFinanceSource()
        self.reddit = RedditSource(self.keys)
        self.trends = GoogleTrendsSource()
        self.newsapi = NewsAPISource(self.keys)
        self.marketaux = MarketauxSource(self.keys)
        self.finnhub = FinnhubSource(self.keys)
        self.alpha_vantage = AlphaVantageSource(self.keys)
        self.fmp = FMPSource(self.keys)
        self.stocktwits = StockTwitsSource()
        self.polygon = PolygonSource(self.keys)

        # Report status
        sources = [self.yahoo, self.reddit, self.trends, self.newsapi,
                   self.marketaux, self.finnhub, self.alpha_vantage,
                   self.fmp, self.stocktwits, self.polygon]
        active = sum(1 for s in sources if s.available)
        print(f"\n  Active sources: {active}/10")
        for s in sources:
            status = "READY" if s.available else "NEEDS KEY" if s.needs_key else "INSTALL"
            icon = "OK" if s.available else "--"
            print(f"    [{icon}] {s.name:25s} {status}")
        print()

    def collect_all(self, tickers, ticker_names=None):
        """
        Run ALL data sources and return unified data.

        Returns:
        {
            "prices": { ticker: { price, volume, ... } },
            "social": { ticker: { mentions, sentiment, ... } },
            "news": { ticker: { count, sentiment, ... } },
            "trending_discovery": [ { ticker, source, score } ],
            "sector_performance": { sector: pct_change },
        }
        """
        ticker_names = ticker_names or {}
        result = {
            "prices": {},
            "social": {},
            "news": {},
            "trending_discovery": [],
            "sector_performance": {},
            "sources_used": [],
            "timestamp": datetime.now().isoformat(),
        }

        # 1. Yahoo Finance — Prices
        print("[Collecting] Yahoo Finance prices...")
        result["prices"] = self.yahoo.fetch_prices(tickers)
        if result["prices"]:
            result["sources_used"].append("yahoo_finance")

        # 2. Reddit — Social mentions
        print("[Collecting] Reddit mentions...")
        reddit_data = self.reddit.collect_mentions(known_tickers=set(tickers))
        for ticker, data in reddit_data.items():
            result["social"][ticker] = result["social"].get(ticker, {})
            result["social"][ticker]["reddit_mentions"] = data["mentions"]
            result["social"][ticker]["reddit_upvotes"] = data["upvotes"]
            result["social"][ticker]["reddit_sentiment"] = round(data["sentiment_sum"] / max(data["mentions"], 1), 3)
            result["social"][ticker]["reddit_sources"] = data["sources"]
        if reddit_data:
            result["sources_used"].append("reddit")

        # 3. Google Trends — Search interest
        print("[Collecting] Google Trends interest...")
        # Only query top 100 tickers (rate limits)
        top_tickers = {t: ticker_names.get(t, t) for t in tickers[:100]}
        trends_data = self.trends.fetch_interest(top_tickers)
        for ticker, interest in trends_data.items():
            result["social"][ticker] = result["social"].get(ticker, {})
            result["social"][ticker]["google_trends_interest"] = interest
        if trends_data:
            result["sources_used"].append("google_trends")

        # 4. NewsAPI — News articles
        print("[Collecting] NewsAPI articles...")
        news_data = self.newsapi.fetch_news({t: ticker_names.get(t, t) for t in tickers[:50]})
        for ticker, data in news_data.items():
            result["news"][ticker] = result["news"].get(ticker, {})
            result["news"][ticker].update(data)
        if news_data:
            result["sources_used"].append("newsapi")

        # 5. Marketaux — Sentiment
        print("[Collecting] Marketaux sentiment...")
        maux_data = self.marketaux.fetch_sentiment(tickers[:100])
        for ticker, data in maux_data.items():
            result["news"][ticker] = result["news"].get(ticker, {})
            result["news"][ticker]["marketaux_sentiment"] = data["sentiment"]
            result["news"][ticker]["marketaux_relevance"] = data["relevance"]
            result["news"][ticker]["marketaux_count"] = data["news_count"]
        if maux_data:
            result["sources_used"].append("marketaux")

        # 6. Finnhub — Social sentiment
        print("[Collecting] Finnhub social sentiment...")
        finnhub_social = self.finnhub.fetch_social_sentiment(tickers[:50])
        for ticker, data in finnhub_social.items():
            result["social"][ticker] = result["social"].get(ticker, {})
            result["social"][ticker]["finnhub_mentions"] = data["mentions"]
            result["social"][ticker]["finnhub_sentiment"] = data["net_sentiment"]
        if finnhub_social:
            result["sources_used"].append("finnhub")

        # 7-10. Discovery sources (gainers, losers, most active, trending)
        print("[Collecting] Trending discovery from all sources...")
        discovery = []

        # Alpha Vantage
        av_data = self.alpha_vantage.fetch_top_gainers_losers()
        for item in av_data.get("gainers", []) + av_data.get("most_active", []):
            discovery.append({"ticker": item["ticker"], "source": "alpha_vantage", "change_pct": item.get("change_pct", 0), "volume": item.get("volume", 0)})
        if av_data.get("gainers"):
            result["sources_used"].append("alpha_vantage")

        # FMP
        fmp_data = self.fmp.fetch_gainers_losers()
        for item in fmp_data.get("gainers", []):
            discovery.append({"ticker": item["ticker"], "source": "fmp", "change_pct": item.get("change_pct", 0), "volume": item.get("volume", 0), "name": item.get("name", "")})
        fmp_active = self.fmp.fetch_most_active()
        for item in fmp_active:
            discovery.append({"ticker": item["ticker"], "source": "fmp_active", "change_pct": item.get("change_pct", 0), "volume": item.get("volume", 0), "name": item.get("name", "")})
        if fmp_data.get("gainers"):
            result["sources_used"].append("fmp")

        # StockTwits
        st_trending = self.stocktwits.fetch_trending()
        for item in st_trending:
            discovery.append({"ticker": item["ticker"], "source": "stocktwits", "watchlist_count": item.get("watchlist_count", 0), "name": item.get("name", "")})
        if st_trending:
            result["sources_used"].append("stocktwits")

        # Polygon
        poly_gainers = self.polygon.fetch_gainers_losers("gainers")
        for item in poly_gainers:
            discovery.append({"ticker": item["ticker"], "source": "polygon", "change_pct": item.get("change_pct", 0), "volume": item.get("volume", 0)})
        if poly_gainers:
            result["sources_used"].append("polygon")

        # Reddit-discovered tickers (not in existing universe)
        existing = set(tickers)
        for ticker in reddit_data:
            if ticker not in existing:
                discovery.append({"ticker": ticker, "source": "reddit_discovery", "mentions": reddit_data[ticker]["mentions"]})

        result["trending_discovery"] = discovery

        # Sector performance
        result["sector_performance"] = self.fmp.fetch_sector_performance()

        print(f"\n[Collected] {len(result['sources_used'])} sources active")
        print(f"[Collected] Prices: {len(result['prices'])} | Social: {len(result['social'])} | News: {len(result['news'])}")
        print(f"[Collected] Discovery: {len(discovery)} trending candidates")

        return result


# ============================================================
# CLI
# ============================================================

if __name__ == "__main__":
    collector = MasterCollector()

    # Quick test
    test_tickers = ["AAPL", "NVDA", "TSLA", "META", "AMZN"]
    test_names = {"AAPL": "Apple", "NVDA": "NVIDIA", "TSLA": "Tesla", "META": "Meta", "AMZN": "Amazon"}

    print("\nRunning test collection...")
    data = collector.collect_all(test_tickers, test_names)
    print(f"\nResults:")
    print(json.dumps({k: v for k, v in data.items() if k != "trending_discovery"}, indent=2, default=str)[:2000])
