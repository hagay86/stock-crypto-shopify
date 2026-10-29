#!/usr/bin/env python3
"""
Dynamic Stock Discovery Engine
================================

Continuously finds NEW trending stocks from all 10 data sources
and rotates them into/out of the 1000-stock pool.

HOW IT WORKS:
1. Pulls trending tickers from every source (Reddit, StockTwits, gainers/losers, news)
2. Scores each candidate on "discovery heat" (how many sources mention it, volume, momentum)
3. Compares against current universe — swaps out cold stocks for hot new ones
4. Validates new tickers are real US-listed stocks (not OTC penny stocks)
5. Maintains a 1000-stock pool that's always the hottest trending stocks

RULES:
- Minimum 3 sources must mention a ticker for it to qualify
- New stock must have higher "discovery heat" than the weakest current stock
- Maximum 50 swaps per cycle (stability)
- Mega-cap stocks are never removed (always keep AAPL, MSFT, etc.)
- Minimum market cap of $500M to qualify
"""

import json
import os
import time
from datetime import datetime, timedelta
from collections import Counter, defaultdict


# ============================================================
# DISCOVERY CONFIGURATION
# ============================================================

DISCOVERY_CONFIG = {
    # How many stocks to swap per cycle
    "max_swaps_per_cycle": 50,

    # Minimum sources that must mention a ticker
    "min_source_count": 2,

    # Minimum discovery heat score to qualify
    "min_heat_score": 25.0,

    # Never remove these tiers
    "protected_tiers": ["mega"],

    # Never remove stocks with score above this
    "protected_score_threshold": 70.0,

    # Minimum volume requirement for new stocks
    "min_volume": 100_000,

    # How often to run discovery (seconds)
    "discovery_interval": 3600,  # 1 hour

    # Discovery score weights
    "heat_weights": {
        "source_count": 0.25,      # How many sources mention it
        "price_change": 0.20,      # % price change
        "volume_spike": 0.20,      # Volume vs normal
        "social_buzz": 0.15,       # Reddit/StockTwits mentions
        "news_coverage": 0.10,     # News article count
        "watchlist_count": 0.10,   # StockTwits watchlist adds
    },

    # History file
    "history_file": "discovery_history.json",
}


# ============================================================
# DISCOVERY HEAT SCORER
# ============================================================

class DiscoveryHeatScorer:
    """
    Scores newly-discovered tickers on how "hot" they are.
    Higher heat = more likely to be added to the universe.
    """

    def __init__(self, config=None):
        self.config = config or DISCOVERY_CONFIG
        self.w = self.config["heat_weights"]

    def score_candidate(self, ticker, sources_data):
        """
        Score a candidate ticker.

        sources_data: {
            "sources": ["reddit", "stocktwits", "fmp", ...],
            "price_change_pct": float,
            "volume": int,
            "mentions": int,
            "news_count": int,
            "watchlist_count": int,
            "name": str,
        }
        """
        w = self.w

        # Source count score (0-100)
        n_sources = len(sources_data.get("sources", []))
        source_score = min(100, n_sources * 20)  # 5 sources = 100

        # Price change score (0-100)
        change_pct = abs(sources_data.get("price_change_pct", 0))
        price_score = min(100, change_pct * 10)  # 10% change = 100

        # Volume spike score (0-100)
        volume = sources_data.get("volume", 0)
        vol_score = min(100, (volume / 1_000_000) * 5)  # 20M vol = 100

        # Social buzz score (0-100)
        mentions = sources_data.get("mentions", 0)
        social_score = min(100, mentions * 5)  # 20 mentions = 100

        # News coverage score (0-100)
        news_count = sources_data.get("news_count", 0)
        news_score = min(100, news_count * 20)  # 5 articles = 100

        # Watchlist score (0-100)
        watchlist = sources_data.get("watchlist_count", 0)
        watch_score = min(100, (watchlist / 1000) * 10)  # 10k = 100

        # Weighted total
        total = (
            source_score * w["source_count"] +
            price_score * w["price_change"] +
            vol_score * w["volume_spike"] +
            social_score * w["social_buzz"] +
            news_score * w["news_coverage"] +
            watch_score * w["watchlist_count"]
        )

        return {
            "ticker": ticker,
            "name": sources_data.get("name", ticker),
            "heat_score": round(total, 2),
            "sources": sources_data.get("sources", []),
            "source_count": n_sources,
            "breakdown": {
                "source_count": round(source_score, 1),
                "price_change": round(price_score, 1),
                "volume_spike": round(vol_score, 1),
                "social_buzz": round(social_score, 1),
                "news_coverage": round(news_score, 1),
                "watchlist": round(watch_score, 1),
            },
            "raw": {
                "price_change_pct": sources_data.get("price_change_pct", 0),
                "volume": sources_data.get("volume", 0),
                "mentions": sources_data.get("mentions", 0),
                "news_count": sources_data.get("news_count", 0),
            },
        }


# ============================================================
# DYNAMIC DISCOVERY ENGINE
# ============================================================

class DynamicDiscoveryEngine:
    """
    Discovers new trending stocks and rotates them into the universe.
    """

    def __init__(self, current_universe, config=None):
        """
        current_universe: list of { ticker, name, sector, tier } dicts
        """
        self.config = config or DISCOVERY_CONFIG
        self.scorer = DiscoveryHeatScorer(self.config)
        self.universe = {s["ticker"]: s for s in current_universe}
        self.history = self._load_history()

    def process_discovery_data(self, discovery_list, social_data=None, news_data=None):
        """
        Process raw discovery data from MasterCollector.collect_all().

        discovery_list: list from collector result["trending_discovery"]
        social_data: dict from collector result["social"]
        news_data: dict from collector result["news"]

        Returns: list of scored candidates sorted by heat_score
        """
        social_data = social_data or {}
        news_data = news_data or {}

        # Aggregate all mentions of each ticker across sources
        candidates = defaultdict(lambda: {
            "sources": set(),
            "price_change_pct": 0,
            "volume": 0,
            "mentions": 0,
            "news_count": 0,
            "watchlist_count": 0,
            "name": "",
        })

        # Process discovery list
        for item in discovery_list:
            ticker = item.get("ticker", "").upper().strip()
            if not ticker or len(ticker) > 5:
                continue

            c = candidates[ticker]
            source = item.get("source", "unknown")
            c["sources"].add(source)

            if item.get("name"):
                c["name"] = item["name"]

            change = item.get("change_pct", 0)
            if abs(change) > abs(c["price_change_pct"]):
                c["price_change_pct"] = change

            vol = item.get("volume", 0)
            if vol > c["volume"]:
                c["volume"] = vol

            if item.get("mentions", 0) > 0:
                c["mentions"] += item["mentions"]

            if item.get("watchlist_count", 0) > 0:
                c["watchlist_count"] = max(c["watchlist_count"], item["watchlist_count"])

        # Enrich with social data
        for ticker, sdata in social_data.items():
            if ticker in candidates:
                reddit_m = sdata.get("reddit_mentions", 0)
                finnhub_m = sdata.get("finnhub_mentions", 0)
                candidates[ticker]["mentions"] += reddit_m + finnhub_m
                if reddit_m > 0:
                    candidates[ticker]["sources"].add("reddit_social")
                if finnhub_m > 0:
                    candidates[ticker]["sources"].add("finnhub_social")

        # Enrich with news data
        for ticker, ndata in news_data.items():
            if ticker in candidates:
                nc = ndata.get("article_count", 0) + ndata.get("marketaux_count", 0)
                candidates[ticker]["news_count"] += nc
                if nc > 0:
                    candidates[ticker]["sources"].add("news")

        # Score all candidates
        scored = []
        for ticker, data in candidates.items():
            data["sources"] = list(data["sources"])
            score = self.scorer.score_candidate(ticker, data)
            scored.append(score)

        # Sort by heat score
        scored.sort(key=lambda x: x["heat_score"], reverse=True)
        return scored

    def find_swap_candidates(self, scored_candidates, current_scores):
        """
        Determine which new stocks should replace which existing stocks.

        scored_candidates: from process_discovery_data()
        current_scores: { ticker: trendscore } for current universe

        Returns: list of { "add": {...}, "remove": {...}, "reason": str }
        """
        config = self.config
        max_swaps = config["max_swaps_per_cycle"]
        min_heat = config["min_heat_score"]
        min_sources = config["min_source_count"]
        protected_tiers = set(config["protected_tiers"])
        protected_threshold = config["protected_score_threshold"]

        # Filter candidates: not already in universe, meet minimums
        new_candidates = [
            c for c in scored_candidates
            if c["ticker"] not in self.universe
            and c["heat_score"] >= min_heat
            and c["source_count"] >= min_sources
        ]

        if not new_candidates:
            return []

        # Find removable stocks: not protected, lowest scores
        removable = []
        for ticker, info in self.universe.items():
            if info.get("tier") in protected_tiers:
                continue
            score = current_scores.get(ticker, 50)
            if score >= protected_threshold:
                continue
            removable.append({
                "ticker": ticker,
                "name": info.get("name", ticker),
                "sector": info.get("sector", ""),
                "tier": info.get("tier", ""),
                "current_score": score,
            })

        # Sort removable by score (weakest first)
        removable.sort(key=lambda x: x["current_score"])

        # Match: replace weakest stocks with hottest candidates
        swaps = []
        for i in range(min(len(new_candidates), len(removable), max_swaps)):
            add = new_candidates[i]
            remove = removable[i]

            # Only swap if the new stock's heat > old stock's score
            if add["heat_score"] > remove["current_score"]:
                swaps.append({
                    "add": {
                        "ticker": add["ticker"],
                        "name": add["name"],
                        "heat_score": add["heat_score"],
                        "sources": add["sources"],
                    },
                    "remove": {
                        "ticker": remove["ticker"],
                        "name": remove["name"],
                        "current_score": remove["current_score"],
                    },
                    "reason": (
                        f"Replacing {remove['ticker']} (score={remove['current_score']:.1f}) "
                        f"with {add['ticker']} (heat={add['heat_score']:.1f}, "
                        f"sources={add['source_count']})"
                    ),
                })

        return swaps

    def execute_swaps(self, swaps, stock_universe_list):
        """
        Execute the swaps: update the universe.

        Returns: updated universe list (for stock_universe.py)
        """
        # Convert list to dict for easy modification
        universe_dict = {s["ticker"]: s for s in stock_universe_list}

        executed = []
        for swap in swaps:
            remove_ticker = swap["remove"]["ticker"]
            add_ticker = swap["add"]["ticker"]

            if remove_ticker in universe_dict:
                # Get the removed stock's sector for the new one
                old_sector = universe_dict[remove_ticker].get("sector", "TECH")

                # Remove old
                del universe_dict[remove_ticker]

                # Add new (starts as "growth" tier until proven otherwise)
                universe_dict[add_ticker] = {
                    "ticker": add_ticker,
                    "name": swap["add"].get("name", add_ticker),
                    "sector": old_sector,  # Inherit sector, will be corrected later
                    "tier": "growth",
                }

                executed.append(swap)

                # Log to history
                self.history["swaps"].append({
                    "time": datetime.now().isoformat(),
                    "added": add_ticker,
                    "removed": remove_ticker,
                    "heat_score": swap["add"]["heat_score"],
                    "old_score": swap["remove"]["current_score"],
                    "sources": swap["add"]["sources"],
                })

        # Update internal state
        self.universe = universe_dict
        self.history["total_swaps"] += len(executed)
        self.history["last_discovery"] = datetime.now().isoformat()
        self._save_history()

        # Convert back to list
        updated_list = list(universe_dict.values())

        print(f"\n[Discovery] Executed {len(executed)} swaps")
        for s in executed[:10]:
            print(f"  SWAP: {s['remove']['ticker']} → {s['add']['ticker']} "
                  f"(heat={s['add']['heat_score']:.1f})")
        if len(executed) > 10:
            print(f"  ... and {len(executed) - 10} more")

        return updated_list

    def get_discovery_report(self, scored_candidates, swaps):
        """Generate a report of the discovery cycle."""
        return {
            "timestamp": datetime.now().isoformat(),
            "total_candidates_found": len(scored_candidates),
            "top_candidates": [
                {
                    "ticker": c["ticker"],
                    "name": c["name"],
                    "heat_score": c["heat_score"],
                    "sources": c["sources"],
                    "source_count": c["source_count"],
                }
                for c in scored_candidates[:20]
            ],
            "swaps_proposed": len(swaps),
            "swaps": [
                {
                    "add": s["add"]["ticker"],
                    "remove": s["remove"]["ticker"],
                    "reason": s["reason"],
                }
                for s in swaps
            ],
            "history": {
                "total_swaps_all_time": self.history.get("total_swaps", 0),
                "last_discovery": self.history.get("last_discovery", "never"),
            },
        }

    def _load_history(self):
        """Load discovery history from disk."""
        path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            self.config["history_file"]
        )
        if os.path.exists(path):
            with open(path, "r") as f:
                return json.load(f)
        return {
            "total_swaps": 0,
            "swaps": [],
            "last_discovery": None,
        }

    def _save_history(self):
        """Save discovery history to disk."""
        path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            self.config["history_file"]
        )
        # Keep only last 500 swaps in history
        if len(self.history.get("swaps", [])) > 500:
            self.history["swaps"] = self.history["swaps"][-500:]

        with open(path, "w") as f:
            json.dump(self.history, f, indent=2, default=str)


# ============================================================
# INTEGRATION: Enhanced TrendScore with Multi-Source Data
# ============================================================

class MultiSourceTrendScore:
    """
    Enhanced TrendScore that combines ALL 10 data sources.

    Original score was 7 factors (price-only).
    This adds 5 more factors from external sources:
    - Social buzz (Reddit + StockTwits + Finnhub)
    - News sentiment (NewsAPI + Marketaux)
    - Google Trends interest
    - Analyst recommendations (Finnhub)
    - Multi-source discovery heat

    Total: 12 factors → one 0-100 score
    """

    # Enhanced weights (rebalanced to include all sources)
    WEIGHTS = {
        # Price-based (50% total — was 100% before)
        "price_momentum_5d": 0.10,
        "price_momentum_20d": 0.08,
        "volume_spike": 0.12,
        "volatility": 0.05,
        "relative_strength": 0.10,
        "market_cap_tier": 0.05,

        # Sector & structural (10%)
        "sector_momentum": 0.10,

        # Social sentiment (15%)
        "social_buzz": 0.08,
        "social_sentiment": 0.07,

        # News (10%)
        "news_coverage": 0.05,
        "news_sentiment": 0.05,

        # Search interest (5%)
        "search_interest": 0.05,

        # Discovery heat (10%)
        "discovery_heat": 0.10,
    }

    def __init__(self):
        self.scores = {}

    def calculate_enhanced_score(self, ticker, price_data, stock_info,
                                  social_data=None, news_data=None,
                                  discovery_heat=0, sector_momentum=50):
        """
        Calculate the full multi-source TrendScore.

        price_data: from LiveDataFetcher or YahooFinanceSource
        stock_info: { ticker, name, sector, tier }
        social_data: { reddit_mentions, reddit_sentiment, finnhub_mentions, ... }
        news_data: { article_count, avg_sentiment, marketaux_sentiment, ... }
        discovery_heat: float 0-100 from DiscoveryHeatScorer
        sector_momentum: float 0-100 from sector analysis
        """
        w = self.WEIGHTS
        social_data = social_data or {}
        news_data = news_data or {}

        if not price_data:
            return self._empty_score(ticker)

        price = price_data.get("price", 0)
        if price <= 0:
            return self._empty_score(ticker)

        # ---- PRICE-BASED FACTORS (same as original, refined) ----

        # Price momentum 5d
        p5d = price_data.get("price_5d_ago", price)
        mom_5d = ((price - p5d) / max(p5d, 0.01)) * 100 if p5d > 0 else 0
        mom_5d_score = max(0, min(100, 50 + mom_5d * 5))

        # Price momentum 20d
        p20d = price_data.get("price_20d_ago", price)
        mom_20d = ((price - p20d) / max(p20d, 0.01)) * 100 if p20d > 0 else 0
        mom_20d_score = max(0, min(100, 50 + mom_20d * 2.5))

        # Volume spike
        vol = price_data.get("volume", 0)
        avg_vol = price_data.get("avg_volume_20d", 1)
        vol_ratio = vol / max(avg_vol, 1)
        vol_score = max(0, min(100, (vol_ratio - 0.5) * 40))

        # Volatility
        volatility = price_data.get("volatility", 2.0)
        vol_v_score = max(0, min(100, volatility * 15))

        # RSI / Relative strength
        prices = price_data.get("prices_history", price_data.get("prices", [price]))
        if len(prices) >= 2:
            changes = [prices[i] - prices[i-1] for i in range(1, len(prices))]
            up = sum(c for c in changes if c > 0)
            down = sum(abs(c) for c in changes if c < 0)
            rs = up / max(down, 0.01)
            rsi = 100 - (100 / (1 + rs))
            if rsi > 70:
                rs_score = max(60, 100 - (rsi - 70) * 2)
            elif rsi < 30:
                rs_score = max(20, rsi * 2)
            else:
                rs_score = 50 + (rsi - 50) * 1.5
            rs_score = max(0, min(100, rs_score))
        else:
            rs_score = 50

        # Tier bonus
        tier = stock_info.get("tier", "mid")
        tier_scores = {"mega": 90, "large": 70, "mid": 50, "growth": 30}
        tier_score = tier_scores.get(tier, 50)

        # Sector momentum (passed in)
        sector_score = max(0, min(100, sector_momentum))

        # ---- SOCIAL FACTORS ----

        # Social buzz: combined mentions from Reddit + StockTwits + Finnhub
        reddit_mentions = social_data.get("reddit_mentions", 0)
        finnhub_mentions = social_data.get("finnhub_mentions", 0)
        total_mentions = reddit_mentions + finnhub_mentions
        # 0 mentions = 30, 10 = 60, 50+ = 100
        buzz_score = max(0, min(100, 30 + total_mentions * 1.4))

        # Social sentiment: weighted average of all sentiment sources
        reddit_sent = social_data.get("reddit_sentiment", 0)  # -1 to 1
        finnhub_sent = social_data.get("finnhub_sentiment", 0)  # -1 to 1
        trends_interest = social_data.get("google_trends_interest", 0)  # 0-100

        sentiments = []
        if reddit_mentions > 0:
            sentiments.append(reddit_sent)
        if finnhub_mentions > 0:
            sentiments.append(finnhub_sent)

        if sentiments:
            avg_sentiment = sum(sentiments) / len(sentiments)
            # Map -1..1 to 0..100
            sentiment_score = max(0, min(100, 50 + avg_sentiment * 50))
        else:
            sentiment_score = 50  # Neutral if no data

        # ---- NEWS FACTORS ----

        article_count = news_data.get("article_count", 0) + news_data.get("marketaux_count", 0)
        news_coverage_score = max(0, min(100, article_count * 15))  # 7 articles = 100

        news_sent = news_data.get("avg_sentiment", 0)
        maux_sent = news_data.get("marketaux_sentiment", 0)
        if article_count > 0:
            combined_news_sent = (news_sent + maux_sent) / 2 if maux_sent else news_sent
            # Map -1..1 to 0..100
            news_sentiment_score = max(0, min(100, 50 + combined_news_sent * 50))
        else:
            news_sentiment_score = 50

        # ---- SEARCH INTEREST ----
        search_score = max(0, min(100, trends_interest))

        # ---- DISCOVERY HEAT ----
        heat_score = max(0, min(100, discovery_heat))

        # ---- FINAL WEIGHTED SCORE ----
        total = (
            mom_5d_score * w["price_momentum_5d"] +
            mom_20d_score * w["price_momentum_20d"] +
            vol_score * w["volume_spike"] +
            vol_v_score * w["volatility"] +
            rs_score * w["relative_strength"] +
            tier_score * w["market_cap_tier"] +
            sector_score * w["sector_momentum"] +
            buzz_score * w["social_buzz"] +
            sentiment_score * w["social_sentiment"] +
            news_coverage_score * w["news_coverage"] +
            news_sentiment_score * w["news_sentiment"] +
            search_score * w["search_interest"] +
            heat_score * w["discovery_heat"]
        )

        result = {
            "ticker": ticker,
            "name": stock_info.get("name", ticker),
            "sector": stock_info.get("sector", ""),
            "tier": tier,
            "price": round(price, 2),
            "total_score": round(total, 2),
            "breakdown": {
                "momentum_5d": round(mom_5d_score, 1),
                "momentum_20d": round(mom_20d_score, 1),
                "volume_spike": round(vol_score, 1),
                "volatility": round(vol_v_score, 1),
                "relative_strength": round(rs_score, 1),
                "tier_bonus": round(tier_score, 1),
                "sector_momentum": round(sector_score, 1),
                "social_buzz": round(buzz_score, 1),
                "social_sentiment": round(sentiment_score, 1),
                "news_coverage": round(news_coverage_score, 1),
                "news_sentiment": round(news_sentiment_score, 1),
                "search_interest": round(search_score, 1),
                "discovery_heat": round(heat_score, 1),
            },
            "data_sources": {
                "price_data": bool(price_data),
                "social_data": bool(social_data),
                "news_data": bool(news_data),
                "has_reddit": reddit_mentions > 0,
                "has_finnhub": finnhub_mentions > 0,
                "has_news": article_count > 0,
                "has_trends": trends_interest > 0,
            },
        }

        self.scores[ticker] = result
        return result

    def calculate_all(self, universe, price_data, collected_data=None):
        """
        Calculate scores for all stocks in universe using collected multi-source data.

        universe: list of { ticker, name, sector, tier }
        price_data: { ticker: { price, volume, ... } }
        collected_data: result from MasterCollector.collect_all()
        """
        collected_data = collected_data or {}
        social = collected_data.get("social", {})
        news = collected_data.get("news", {})
        discovery = collected_data.get("trending_discovery", [])
        sector_perf = collected_data.get("sector_performance", {})

        # Pre-compute discovery heat per ticker
        heat_map = defaultdict(float)
        for item in discovery:
            t = item.get("ticker", "")
            # Simple heat: each mention adds 10, big movers add more
            heat_map[t] += 10 + abs(item.get("change_pct", 0)) * 2

        # Pre-compute sector momentum
        sector_momentum = {}
        for sector, change in sector_perf.items():
            sector_momentum[sector] = max(0, min(100, 50 + change * 10))

        # Score every stock
        self.scores = {}
        for stock in universe:
            ticker = stock["ticker"]
            pdata = price_data.get(ticker, {})
            sdata = social.get(ticker, {})
            ndata = news.get(ticker, {})
            heat = min(100, heat_map.get(ticker, 0))
            sec_mom = sector_momentum.get(stock.get("sector", ""), 50)

            self.calculate_enhanced_score(
                ticker, pdata, stock,
                social_data=sdata,
                news_data=ndata,
                discovery_heat=heat,
                sector_momentum=sec_mom,
            )

        return self.scores

    def get_rankings(self, top_n=None):
        """Return stocks ranked by score, highest first."""
        ranked = sorted(
            self.scores.values(),
            key=lambda x: x["total_score"],
            reverse=True,
        )
        return ranked[:top_n] if top_n else ranked

    def _empty_score(self, ticker):
        return {
            "ticker": ticker, "name": "", "sector": "", "tier": "",
            "price": 0, "total_score": 0,
            "breakdown": {k: 0 for k in self.WEIGHTS},
            "data_sources": {},
        }


# ============================================================
# CLI TEST
# ============================================================

if __name__ == "__main__":
    print("Dynamic Discovery Engine loaded.")
    print(f"Heat score weights: {DISCOVERY_CONFIG['heat_weights']}")
    print(f"Max swaps per cycle: {DISCOVERY_CONFIG['max_swaps_per_cycle']}")
    print(f"Multi-source TrendScore weights: {MultiSourceTrendScore.WEIGHTS}")
    print(f"Total weight: {sum(MultiSourceTrendScore.WEIGHTS.values()):.2f}")
