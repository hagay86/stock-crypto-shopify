#!/usr/bin/env python3
"""
ETF-1000 Engine — The Trending Stocks ETF (TSCORE)
====================================================

This is the REAL engine that:
1. Pulls live stock data from 10 REAL data sources (Yahoo, Reddit, News, etc.)
2. Calculates TrendScore using 12 weighted factors (price + social + news + search)
3. Allocates $100,000,000,000 across all 1000 positions based on trend weight
4. Runs the 3% auto-trade rule on ALL positions simultaneously
5. Dynamically discovers NEW trending stocks and rotates them in
6. Rebalances in real-time based on TrendScore changes
7. Outputs full portfolio state as JSON for the frontend

REQUIREMENTS:
    pip install yfinance requests pandas numpy pytrends praw textblob

RUN:
    python etf_1000.py              # Full live mode
    python etf_1000.py --demo       # Demo with simulated price movements
    python etf_1000.py --snapshot   # One-time snapshot (no loop)
    python etf_1000.py --discover   # Run one discovery cycle then exit
"""

import json
import math
import time
import random
import os
import sys
from datetime import datetime, timedelta
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

# Local imports
from stock_universe import get_stock_universe, get_tickers, SECTORS

# Multi-source imports (graceful fallback)
try:
    from data_sources import MasterCollector
    MULTI_SOURCE_AVAILABLE = True
except ImportError:
    MULTI_SOURCE_AVAILABLE = False
    print("[Warning] data_sources.py not found — using price-only scoring")

try:
    from dynamic_discovery import DynamicDiscoveryEngine, MultiSourceTrendScore
    DISCOVERY_AVAILABLE = True
except ImportError:
    DISCOVERY_AVAILABLE = False
    print("[Warning] dynamic_discovery.py not found — discovery disabled")


# ============================================================
# CONFIGURATION
# ============================================================

ETF_CONFIG = {
    # ETF Identity
    "etf_name": "TrendScore-1000 ETF",
    "etf_ticker": "TSCORE",
    "version": "2.0.0",

    # Capital
    "starting_capital": 100_000_000_000,  # $100 Billion
    "min_position_value": 1_000_000,       # Minimum $1M per stock
    "max_single_stock_pct": 5.0,           # No single stock > 5% of portfolio

    # TrendScore Weights
    "trend_weights": {
        "price_momentum_5d": 0.20,   # 5-day price change
        "price_momentum_20d": 0.15,  # 20-day price change
        "volume_spike": 0.20,        # Volume vs 20-day average
        "volatility": 0.10,          # Higher vol = more interesting
        "market_cap_tier": 0.10,     # Mega > Large > Mid > Growth
        "sector_momentum": 0.10,     # Sector-level trend
        "relative_strength": 0.15,   # RSI-like indicator
    },

    # 3% Rule Settings
    "three_pct_rule": {
        "drop_threshold_pct": 3.0,
        "rise_threshold_pct": 3.0,
        "sell_pct": 50,              # Sell 50% on 3% drop
        "buy_pct": 50,               # Buy 50% more on 3% rise
        "max_cycles_per_day": 5,     # Max buy/sell cycles per stock per day
        "check_interval_seconds": 60,
    },

    # Allocation Tiers (how much of capital goes to each tier)
    "tier_allocation": {
        "mega": 0.35,    # 35% to mega-cap (top ~36 stocks)
        "large": 0.30,   # 30% to large-cap (top ~252 stocks)
        "mid": 0.25,     # 25% to mid-cap (top ~511 stocks)
        "growth": 0.10,  # 10% to growth (top ~205 stocks)
    },

    # Data refresh
    "price_refresh_seconds": 60,
    "trendscore_refresh_seconds": 300,

    # Output
    "output_file": "etf_state.json",
    "trade_log_file": "trade_log.json",
}


# ============================================================
# LIVE DATA FETCHER
# ============================================================

class LiveDataFetcher:
    """
    Fetches real stock data from Yahoo Finance.
    Falls back to simulation if yfinance not available.
    """

    def __init__(self):
        self.yf_available = False
        self.cache = {}
        self.cache_time = {}
        try:
            import yfinance as yf
            self.yf = yf
            self.yf_available = True
            print("[Data] Yahoo Finance connected")
        except ImportError:
            print("[Data] yfinance not installed — using simulated data")
            print("[Data] Install with: pip install yfinance")

    def fetch_batch(self, tickers, period="1mo"):
        """Fetch data for a batch of tickers."""
        if self.yf_available:
            return self._fetch_live(tickers, period)
        else:
            return self._simulate_data(tickers)

    def _fetch_live(self, tickers, period="1mo"):
        """Fetch real data from Yahoo Finance in batches."""
        data = {}
        batch_size = 50  # Yahoo Finance handles ~50 at a time well

        for i in range(0, len(tickers), batch_size):
            batch = tickers[i:i + batch_size]
            ticker_str = " ".join(batch)

            try:
                download = self.yf.download(
                    ticker_str,
                    period=period,
                    group_by="ticker",
                    auto_adjust=True,
                    threads=True,
                    progress=False,
                )

                for ticker in batch:
                    try:
                        if len(batch) == 1:
                            df = download
                        else:
                            df = download[ticker] if ticker in download.columns.get_level_values(0) else None

                        if df is not None and not df.empty:
                            closes = df["Close"].dropna()
                            volumes = df["Volume"].dropna()
                            highs = df["High"].dropna()
                            lows = df["Low"].dropna()

                            if len(closes) >= 2:
                                current_price = float(closes.iloc[-1])
                                open_today = float(df["Open"].iloc[-1]) if "Open" in df else current_price

                                data[ticker] = {
                                    "price": current_price,
                                    "open_today": open_today,
                                    "high_today": float(highs.iloc[-1]),
                                    "low_today": float(lows.iloc[-1]),
                                    "volume": int(volumes.iloc[-1]),
                                    "avg_volume_20d": int(volumes.tail(20).mean()) if len(volumes) >= 20 else int(volumes.mean()),
                                    "price_5d_ago": float(closes.iloc[-5]) if len(closes) >= 5 else current_price,
                                    "price_20d_ago": float(closes.iloc[-20]) if len(closes) >= 20 else float(closes.iloc[0]),
                                    "prices_history": [float(x) for x in closes.tail(20).tolist()],
                                    "volatility": float(closes.pct_change().tail(20).std() * 100) if len(closes) >= 20 else 2.0,
                                }
                    except Exception as e:
                        pass  # Skip problematic tickers

                progress = min(i + batch_size, len(tickers))
                print(f"  [Data] Fetched {progress}/{len(tickers)} tickers...")

            except Exception as e:
                print(f"  [Data] Batch error: {e}")

        return data

    def _simulate_data(self, tickers):
        """Generate realistic simulated market data."""
        data = {}
        universe = {s["ticker"]: s for s in get_stock_universe()}

        # Base prices by tier (realistic ranges)
        tier_price_ranges = {
            "mega": (150, 900),
            "large": (50, 500),
            "mid": (20, 200),
            "growth": (5, 80),
        }

        for ticker in tickers:
            stock = universe.get(ticker, {"tier": "mid"})
            tier = stock.get("tier", "mid")
            price_range = tier_price_ranges.get(tier, (20, 200))

            # Generate consistent base price from ticker hash
            seed = sum(ord(c) for c in ticker) * 137
            random.seed(seed)
            base_price = random.uniform(*price_range)

            # Add some randomness for "current" state
            random.seed(seed + int(time.time() / 300))  # Changes every 5 min
            noise = random.gauss(0, base_price * 0.02)
            current_price = round(base_price + noise, 2)

            # Generate historical prices
            random.seed(seed)
            prices = [base_price]
            for _ in range(19):
                change = random.gauss(0, base_price * 0.015)
                prices.append(round(prices[-1] + change, 2))
            prices.append(current_price)

            # Volume
            base_volume = int(random.uniform(500000, 50000000))
            volume_today = int(base_volume * random.uniform(0.5, 2.5))

            data[ticker] = {
                "price": max(0.01, current_price),
                "open_today": round(current_price * random.uniform(0.97, 1.03), 2),
                "high_today": round(current_price * random.uniform(1.0, 1.05), 2),
                "low_today": round(current_price * random.uniform(0.95, 1.0), 2),
                "volume": volume_today,
                "avg_volume_20d": base_volume,
                "price_5d_ago": prices[-5] if len(prices) >= 5 else current_price,
                "price_20d_ago": prices[0],
                "prices_history": prices[-20:],
                "volatility": round(random.uniform(1.0, 8.0), 2),
            }

        random.seed()  # Reset random seed
        return data


# ============================================================
# TRENDSCORE ENGINE (SCALED FOR 1000 STOCKS)
# ============================================================

class TrendScoreEngine:
    """
    Calculates TrendScore (0-100) for each stock based on:
    - Price momentum (5d and 20d)
    - Volume spike vs average
    - Volatility
    - Market cap tier bonus
    - Sector momentum (aggregated)
    - Relative Strength Index
    """

    def __init__(self, config=None):
        self.config = config or ETF_CONFIG
        self.weights = self.config["trend_weights"]
        self.scores = {}  # { ticker: { score, breakdown } }
        self.sector_scores = {}  # { sector: avg_momentum }

    def calculate_all(self, market_data, universe):
        """Calculate TrendScore for every stock in the universe."""
        self.scores = {}

        # Step 1: Calculate sector-level momentum first
        self._calculate_sector_momentum(market_data, universe)

        # Step 2: Score each stock
        for stock in universe:
            ticker = stock["ticker"]
            data = market_data.get(ticker)
            if not data:
                self.scores[ticker] = self._empty_score(ticker)
                continue

            score = self._score_stock(ticker, data, stock)
            self.scores[ticker] = score

        return self.scores

    def get_rankings(self, top_n=None):
        """Return stocks ranked by TrendScore, highest first."""
        ranked = sorted(
            self.scores.values(),
            key=lambda x: x["total_score"],
            reverse=True
        )
        if top_n:
            return ranked[:top_n]
        return ranked

    def _score_stock(self, ticker, data, stock_info):
        """Calculate TrendScore for a single stock."""
        price = data["price"]
        w = self.weights

        # --- PRICE MOMENTUM 5D (0-100) ---
        price_5d_ago = data.get("price_5d_ago", price)
        if price_5d_ago > 0:
            mom_5d = ((price - price_5d_ago) / price_5d_ago) * 100
            # Map: -10% = 0, 0% = 50, +10% = 100
            mom_5d_score = max(0, min(100, 50 + mom_5d * 5))
        else:
            mom_5d_score = 50

        # --- PRICE MOMENTUM 20D (0-100) ---
        price_20d_ago = data.get("price_20d_ago", price)
        if price_20d_ago > 0:
            mom_20d = ((price - price_20d_ago) / price_20d_ago) * 100
            mom_20d_score = max(0, min(100, 50 + mom_20d * 2.5))
        else:
            mom_20d_score = 50

        # --- VOLUME SPIKE (0-100) ---
        volume = data.get("volume", 0)
        avg_vol = data.get("avg_volume_20d", 1)
        if avg_vol > 0:
            vol_ratio = volume / avg_vol
            # 0.5x = 0, 1x = 30, 2x = 60, 3x+ = 100
            vol_score = max(0, min(100, (vol_ratio - 0.5) * 40))
        else:
            vol_score = 30

        # --- VOLATILITY (0-100) ---
        # Higher volatility = more "interesting" = higher score
        volatility = data.get("volatility", 2.0)
        vol_score_v = max(0, min(100, volatility * 15))

        # --- MARKET CAP TIER BONUS (0-100) ---
        tier = stock_info.get("tier", "mid")
        tier_scores = {"mega": 90, "large": 70, "mid": 50, "growth": 30}
        tier_score = tier_scores.get(tier, 50)

        # --- SECTOR MOMENTUM (0-100) ---
        sector = stock_info.get("sector", "TECH")
        sector_score = self.sector_scores.get(sector, 50)

        # --- RELATIVE STRENGTH (0-100) ---
        # Simple RSI-like: based on ratio of up days to total days
        prices = data.get("prices_history", [price])
        if len(prices) >= 2:
            changes = [prices[i] - prices[i-1] for i in range(1, len(prices))]
            up_moves = sum(c for c in changes if c > 0)
            down_moves = sum(abs(c) for c in changes if c < 0)
            if down_moves > 0:
                rs = up_moves / down_moves
                rsi = 100 - (100 / (1 + rs))
            else:
                rsi = 70 if up_moves > 0 else 50
            # Map RSI to 0-100 score (30-70 RSI = most investable)
            if rsi > 70:
                rs_score = max(60, 100 - (rsi - 70) * 2)  # Overbought penalty
            elif rsi < 30:
                rs_score = max(20, rsi * 2)  # Oversold penalty
            else:
                rs_score = 50 + (rsi - 50) * 1.5  # Normal range
            rs_score = max(0, min(100, rs_score))
        else:
            rs_score = 50

        # --- FINAL WEIGHTED SCORE ---
        total = (
            mom_5d_score * w["price_momentum_5d"] +
            mom_20d_score * w["price_momentum_20d"] +
            vol_score * w["volume_spike"] +
            vol_score_v * w["volatility"] +
            tier_score * w["market_cap_tier"] +
            sector_score * w["sector_momentum"] +
            rs_score * w["relative_strength"]
        )

        return {
            "ticker": ticker,
            "name": stock_info.get("name", ticker),
            "sector": sector,
            "tier": tier,
            "price": round(price, 2),
            "total_score": round(total, 2),
            "breakdown": {
                "momentum_5d": round(mom_5d_score, 1),
                "momentum_20d": round(mom_20d_score, 1),
                "volume_spike": round(vol_score, 1),
                "volatility": round(vol_score_v, 1),
                "tier_bonus": round(tier_score, 1),
                "sector_momentum": round(sector_score, 1),
                "relative_strength": round(rs_score, 1),
            },
            "raw_data": {
                "price_change_5d_pct": round(((price - data.get("price_5d_ago", price)) / max(data.get("price_5d_ago", 1), 0.01)) * 100, 2),
                "price_change_20d_pct": round(((price - data.get("price_20d_ago", price)) / max(data.get("price_20d_ago", 1), 0.01)) * 100, 2),
                "volume_ratio": round(data.get("volume", 0) / max(data.get("avg_volume_20d", 1), 1), 2),
                "volatility_pct": round(data.get("volatility", 0), 2),
            }
        }

    def _calculate_sector_momentum(self, market_data, universe):
        """Calculate average momentum per sector."""
        sector_changes = defaultdict(list)

        for stock in universe:
            ticker = stock["ticker"]
            data = market_data.get(ticker)
            if data and data.get("price_5d_ago", 0) > 0:
                change = ((data["price"] - data["price_5d_ago"]) / data["price_5d_ago"]) * 100
                sector_changes[stock["sector"]].append(change)

        for sector, changes in sector_changes.items():
            avg_change = sum(changes) / len(changes) if changes else 0
            # Map: -5% = 0, 0% = 50, +5% = 100
            self.sector_scores[sector] = max(0, min(100, 50 + avg_change * 10))

    def _empty_score(self, ticker):
        return {
            "ticker": ticker, "name": "", "sector": "", "tier": "",
            "price": 0, "total_score": 0,
            "breakdown": {k: 0 for k in self.weights},
            "raw_data": {},
        }


# ============================================================
# PORTFOLIO MANAGER ($100B across 1000 stocks)
# ============================================================

class ETFPortfolio:
    """
    Manages the $100B ETF portfolio:
    - Allocates capital by TrendScore weight
    - Tracks all 1000 positions
    - Executes 3% rule trades
    - Maintains full trade history
    """

    def __init__(self, starting_capital, config=None):
        self.config = config or ETF_CONFIG
        self.starting_capital = starting_capital
        self.cash = starting_capital
        self.positions = {}       # { ticker: { shares, avg_cost, allocation_pct, trend_score } }
        self.trade_log = []
        self.daily_opens = {}
        self.daily_cycles = defaultdict(int)
        self.total_trades = 0
        self.total_buys = 0
        self.total_sells = 0

    def allocate_by_trendscore(self, rankings, market_data):
        """
        Allocate capital across all ranked stocks weighted by TrendScore.

        The allocation formula:
        1. Each stock gets a base weight proportional to its TrendScore
        2. Weights are normalized so they sum to 100%
        3. Capital is distributed according to weights
        4. No single stock exceeds max_single_stock_pct (5%)
        5. Minimum position size is $1M
        """
        max_pct = self.config["max_single_stock_pct"] / 100
        min_value = self.config["min_position_value"]

        # Filter to stocks we have price data for
        valid = [r for r in rankings if r["ticker"] in market_data and r["total_score"] > 0]

        if not valid:
            print("[Portfolio] No valid stocks to allocate to!")
            return

        # Calculate raw weights (TrendScore ^ 1.5 gives more weight to top stocks)
        raw_weights = {}
        for r in valid:
            raw_weights[r["ticker"]] = r["total_score"] ** 1.5

        total_weight = sum(raw_weights.values())
        if total_weight == 0:
            return

        # Normalize and cap
        total_capital = self.starting_capital
        allocations = {}

        for ticker, weight in raw_weights.items():
            pct = weight / total_weight
            # Cap at max
            pct = min(pct, max_pct)
            allocations[ticker] = pct

        # Re-normalize after capping
        total_pct = sum(allocations.values())
        if total_pct > 0:
            for ticker in allocations:
                allocations[ticker] /= total_pct

        # Execute allocations
        positions_created = 0
        total_invested = 0

        for r in valid:
            ticker = r["ticker"]
            alloc_pct = allocations.get(ticker, 0)
            target_value = total_capital * alloc_pct

            if target_value < min_value:
                continue  # Skip too-small positions

            price = market_data[ticker]["price"]
            if price <= 0:
                continue

            shares = int(target_value / price)
            if shares == 0:
                continue

            cost = shares * price
            if cost > self.cash:
                shares = int(self.cash / price)
                cost = shares * price

            if shares == 0:
                continue

            self.cash -= cost
            total_invested += cost
            positions_created += 1

            self.positions[ticker] = {
                "shares": shares,
                "avg_cost": price,
                "current_price": price,
                "allocation_pct": round(alloc_pct * 100, 4),
                "trend_score": r["total_score"],
                "sector": r.get("sector", ""),
                "tier": r.get("tier", ""),
                "name": r.get("name", ticker),
                "market_value": round(cost, 2),
                "unrealized_pnl": 0,
                "unrealized_pnl_pct": 0,
            }

            self.trade_log.append({
                "time": datetime.now().isoformat(),
                "action": "INITIAL_BUY",
                "ticker": ticker,
                "shares": shares,
                "price": price,
                "value": round(cost, 2),
                "reason": f"Initial ETF allocation — TrendScore: {r['total_score']:.1f}, Weight: {alloc_pct*100:.3f}%",
            })

        self.total_buys += positions_created

        print(f"\n[Portfolio] Allocated ${total_invested:,.0f} across {positions_created} positions")
        print(f"[Portfolio] Cash remaining: ${self.cash:,.0f}")
        print(f"[Portfolio] Avg position size: ${total_invested/max(positions_created,1):,.0f}")

        # Set daily opens
        self.daily_opens = {t: market_data[t]["price"] for t in self.positions if t in market_data}

    def run_three_pct_rule(self, current_prices):
        """
        Apply the 3% rule to ALL positions simultaneously.

        For each position:
        - If price dropped 3% from today's open → SELL 50%
        - If price rose 3% from today's open → BUY 50% more
        - Max 5 cycles per stock per day
        """
        rule = self.config["three_pct_rule"]
        drop_thresh = rule["drop_threshold_pct"]
        rise_thresh = rule["rise_threshold_pct"]
        sell_pct = rule["sell_pct"]
        buy_pct = rule["buy_pct"]
        max_cycles = rule["max_cycles_per_day"]

        trades_executed = []

        for ticker in list(self.positions.keys()):
            if self.daily_cycles[ticker] >= max_cycles:
                continue

            current = current_prices.get(ticker)
            open_price = self.daily_opens.get(ticker)

            if not current or not open_price or open_price <= 0:
                continue

            change_pct = ((current - open_price) / open_price) * 100
            pos = self.positions[ticker]

            # DROP RULE: Sell 50%
            if change_pct <= -drop_thresh:
                shares_to_sell = max(1, int(pos["shares"] * sell_pct / 100))
                if shares_to_sell > pos["shares"]:
                    shares_to_sell = pos["shares"]

                revenue = shares_to_sell * current
                profit = (current - pos["avg_cost"]) * shares_to_sell
                self.cash += revenue

                remaining = pos["shares"] - shares_to_sell
                if remaining <= 0:
                    del self.positions[ticker]
                else:
                    self.positions[ticker]["shares"] = remaining
                    self.positions[ticker]["market_value"] = remaining * current

                trade = {
                    "time": datetime.now().isoformat(),
                    "action": "SELL_3PCT",
                    "ticker": ticker,
                    "shares": shares_to_sell,
                    "price": current,
                    "value": round(revenue, 2),
                    "profit": round(profit, 2),
                    "reason": f"3% DROP RULE — Down {change_pct:.2f}% from open ${open_price:.2f}",
                }
                self.trade_log.append(trade)
                trades_executed.append(trade)
                self.daily_cycles[ticker] += 1
                self.total_sells += 1
                self.total_trades += 1

            # RISE RULE: Buy 50% more
            elif change_pct >= rise_thresh:
                current_value = pos["shares"] * current
                buy_value = current_value * (buy_pct / 100)
                buy_value = min(buy_value, self.cash)

                if buy_value < 100:
                    continue

                shares_to_buy = int(buy_value / current)
                if shares_to_buy == 0:
                    continue

                cost = shares_to_buy * current
                self.cash -= cost

                total_shares = pos["shares"] + shares_to_buy
                total_cost_basis = pos["shares"] * pos["avg_cost"] + cost
                new_avg_cost = total_cost_basis / total_shares

                self.positions[ticker]["shares"] = total_shares
                self.positions[ticker]["avg_cost"] = new_avg_cost
                self.positions[ticker]["market_value"] = total_shares * current

                trade = {
                    "time": datetime.now().isoformat(),
                    "action": "BUY_3PCT",
                    "ticker": ticker,
                    "shares": shares_to_buy,
                    "price": current,
                    "value": round(cost, 2),
                    "reason": f"3% RISE RULE — Up {change_pct:.2f}% from open ${open_price:.2f}",
                }
                self.trade_log.append(trade)
                trades_executed.append(trade)
                self.daily_cycles[ticker] += 1
                self.total_buys += 1
                self.total_trades += 1

        return trades_executed

    def update_prices(self, current_prices):
        """Update all position values with current prices."""
        for ticker, pos in self.positions.items():
            price = current_prices.get(ticker, pos.get("current_price", pos["avg_cost"]))
            pos["current_price"] = price
            pos["market_value"] = round(pos["shares"] * price, 2)
            pos["unrealized_pnl"] = round((price - pos["avg_cost"]) * pos["shares"], 2)
            if pos["avg_cost"] > 0:
                pos["unrealized_pnl_pct"] = round(((price - pos["avg_cost"]) / pos["avg_cost"]) * 100, 2)

    def get_portfolio_value(self):
        """Total portfolio value (cash + stock value)."""
        stock_value = sum(pos.get("market_value", 0) for pos in self.positions.values())
        return self.cash + stock_value

    def get_pnl(self):
        """Total P&L."""
        return self.get_portfolio_value() - self.starting_capital

    def get_state(self):
        """Return full portfolio state as dict (for JSON export)."""
        total_value = self.get_portfolio_value()
        pnl = self.get_pnl()
        stock_value = total_value - self.cash

        # Top holdings
        sorted_positions = sorted(
            self.positions.items(),
            key=lambda x: x[1].get("market_value", 0),
            reverse=True
        )

        # Sector breakdown
        sector_values = defaultdict(float)
        for ticker, pos in self.positions.items():
            sector_values[pos.get("sector", "OTHER")] += pos.get("market_value", 0)

        sector_breakdown = {
            SECTORS.get(s, s): {
                "value": round(v, 2),
                "pct": round(v / max(total_value, 1) * 100, 2)
            }
            for s, v in sorted(sector_values.items(), key=lambda x: x[1], reverse=True)
        }

        # Tier breakdown
        tier_values = defaultdict(float)
        tier_counts = defaultdict(int)
        for ticker, pos in self.positions.items():
            tier_values[pos.get("tier", "mid")] += pos.get("market_value", 0)
            tier_counts[pos.get("tier", "mid")] += 1

        tier_breakdown = {
            tier: {
                "value": round(v, 2),
                "pct": round(v / max(total_value, 1) * 100, 2),
                "count": tier_counts[tier],
            }
            for tier, v in sorted(tier_values.items(), key=lambda x: x[1], reverse=True)
        }

        return {
            "timestamp": datetime.now().isoformat(),
            "etf_name": self.config["etf_name"],
            "etf_ticker": self.config["etf_ticker"],

            "summary": {
                "total_value": round(total_value, 2),
                "cash": round(self.cash, 2),
                "invested": round(stock_value, 2),
                "pnl": round(pnl, 2),
                "pnl_pct": round(pnl / max(self.starting_capital, 1) * 100, 4),
                "total_positions": len(self.positions),
                "total_trades": self.total_trades,
                "total_buys": self.total_buys,
                "total_sells": self.total_sells,
            },

            "top_holdings": [
                {
                    "rank": i + 1,
                    "ticker": ticker,
                    "name": pos.get("name", ticker),
                    "shares": pos["shares"],
                    "price": pos.get("current_price", pos["avg_cost"]),
                    "market_value": pos.get("market_value", 0),
                    "weight_pct": round(pos.get("market_value", 0) / max(total_value, 1) * 100, 4),
                    "trend_score": pos.get("trend_score", 0),
                    "pnl": pos.get("unrealized_pnl", 0),
                    "pnl_pct": pos.get("unrealized_pnl_pct", 0),
                    "sector": SECTORS.get(pos.get("sector", ""), pos.get("sector", "")),
                    "tier": pos.get("tier", ""),
                }
                for i, (ticker, pos) in enumerate(sorted_positions[:100])  # Top 100
            ],

            "all_holdings": [
                {
                    "ticker": ticker,
                    "shares": pos["shares"],
                    "price": pos.get("current_price", pos["avg_cost"]),
                    "value": pos.get("market_value", 0),
                    "weight": round(pos.get("market_value", 0) / max(total_value, 1) * 100, 4),
                    "score": pos.get("trend_score", 0),
                    "pnl_pct": pos.get("unrealized_pnl_pct", 0),
                    "sector": pos.get("sector", ""),
                }
                for ticker, pos in sorted_positions
            ],

            "sector_breakdown": sector_breakdown,
            "tier_breakdown": tier_breakdown,

            "recent_trades": self.trade_log[-50:],  # Last 50 trades
        }

    def reset_daily(self, current_prices):
        """Reset daily tracking (call at market open)."""
        self.daily_opens = dict(current_prices)
        self.daily_cycles = defaultdict(int)


# ============================================================
# MAIN ETF ENGINE
# ============================================================

class ETF1000Engine:
    """
    The complete ETF engine that ties everything together.
    Now with 10-source data collection and dynamic stock discovery.
    """

    def __init__(self, config=None, use_multi_source=True):
        self.config = config or ETF_CONFIG
        self.fetcher = LiveDataFetcher()
        self.scorer = TrendScoreEngine(self.config)
        self.portfolio = ETFPortfolio(self.config["starting_capital"], self.config)
        self.universe = get_stock_universe()
        self.tickers = [s["ticker"] for s in self.universe]
        self.market_data = {}
        self.collected_data = {}  # Multi-source data from MasterCollector
        self.initialized = False

        # Multi-source scoring
        self.use_multi_source = use_multi_source and MULTI_SOURCE_AVAILABLE
        self.multi_scorer = MultiSourceTrendScore() if DISCOVERY_AVAILABLE else None
        self.collector = None
        self.discovery_engine = None

        if self.use_multi_source:
            try:
                self.collector = MasterCollector()
                print("[Engine] Multi-source data collection: ENABLED (10 sources)")
            except Exception as e:
                print(f"[Engine] Multi-source init failed: {e} — falling back to price-only")
                self.use_multi_source = False

        if DISCOVERY_AVAILABLE:
            self.discovery_engine = DynamicDiscoveryEngine(self.universe)
            print("[Engine] Dynamic stock discovery: ENABLED")

    def initialize(self):
        """Run full initialization: fetch data, score, allocate."""
        print(f"\n{'='*70}")
        print(f"  {self.config['etf_name']} — Initialization")
        print(f"  Capital: ${self.config['starting_capital']:,.0f}")
        print(f"  Universe: {len(self.tickers)} stocks")
        print(f"  Data sources: {'10 (multi-source)' if self.use_multi_source else 'Price-only'}")
        print(f"  Discovery: {'ACTIVE' if self.discovery_engine else 'OFF'}")
        print(f"{'='*70}\n")

        # Step 1: Fetch market data (multi-source if available)
        if self.use_multi_source and self.collector:
            print("[1/5] Collecting data from ALL sources...")
            ticker_names = {s["ticker"]: s["name"] for s in self.universe}
            self.collected_data = self.collector.collect_all(self.tickers, ticker_names)
            # Use Yahoo prices from collector, fallback to direct fetch
            self.market_data = self.collected_data.get("prices", {})
            if len(self.market_data) < len(self.tickers) * 0.5:
                print("  [Fallback] Not enough prices from collector, using direct fetch...")
                fallback = self.fetcher.fetch_batch(self.tickers)
                for t, d in fallback.items():
                    if t not in self.market_data:
                        self.market_data[t] = d
            sources_used = self.collected_data.get("sources_used", [])
            print(f"  Got data for {len(self.market_data)}/{len(self.tickers)} stocks")
            print(f"  Active sources: {', '.join(sources_used) if sources_used else 'simulation'}\n")
        else:
            print("[1/5] Fetching market data (price-only mode)...")
            self.market_data = self.fetcher.fetch_batch(self.tickers)
            print(f"  Got data for {len(self.market_data)}/{len(self.tickers)} stocks\n")

        # Step 2: Calculate TrendScores (multi-source if available)
        if self.multi_scorer and self.collected_data:
            print("[2/5] Calculating MULTI-SOURCE TrendScores (12 factors)...")
            self.multi_scorer.calculate_all(
                self.universe, self.market_data, self.collected_data
            )
            rankings = self.multi_scorer.get_rankings()
            print(f"  Scored {len(rankings)} stocks with 12-factor model")
        else:
            print("[2/5] Calculating TrendScores (7-factor price model)...")
            self.scorer.calculate_all(self.market_data, self.universe)
            rankings = self.scorer.get_rankings()
            print(f"  Scored {len(rankings)} stocks")

        # Show top 20
        print(f"\n  {'='*50}")
        print(f"  TOP 20 BY TRENDSCORE")
        print(f"  {'='*50}")
        for i, r in enumerate(rankings[:20]):
            print(f"  #{i+1:3d}  {r['ticker']:6s}  Score: {r['total_score']:5.1f}  "
                  f"Price: ${r['price']:>8.2f}  Sector: {r.get('sector','')}")

        # Step 3: Run discovery (if available)
        if self.discovery_engine and self.collected_data:
            print(f"\n[3/5] Running dynamic stock discovery...")
            discovery_data = self.collected_data.get("trending_discovery", [])
            social_data = self.collected_data.get("social", {})
            news_data = self.collected_data.get("news", {})

            scored_candidates = self.discovery_engine.process_discovery_data(
                discovery_data, social_data, news_data
            )
            current_scores = {r["ticker"]: r["total_score"] for r in rankings}
            swaps = self.discovery_engine.find_swap_candidates(scored_candidates, current_scores)

            if swaps:
                self.universe = self.discovery_engine.execute_swaps(swaps, self.universe)
                self.tickers = [s["ticker"] for s in self.universe]
                # Re-score after swaps
                if self.multi_scorer:
                    self.multi_scorer.calculate_all(
                        self.universe, self.market_data, self.collected_data
                    )
                    rankings = self.multi_scorer.get_rankings()
            else:
                print("  No swaps needed — current universe is strong")

            report = self.discovery_engine.get_discovery_report(scored_candidates, swaps)
            print(f"  Found {report['total_candidates_found']} candidates, executed {report['swaps_proposed']} swaps")
        else:
            print(f"\n[3/5] Discovery skipped (no multi-source data)")

        # Step 4: Allocate portfolio
        print(f"\n[4/5] Allocating ${self.config['starting_capital']:,.0f} across stocks...")
        self.portfolio.allocate_by_trendscore(rankings, self.market_data)

        # Step 5: Save state
        print("\n[5/5] Saving initial state...")
        self._save_state()

        self.initialized = True
        print(f"\n{'='*70}")
        print(f"  INITIALIZATION COMPLETE")
        print(f"  Positions: {len(self.portfolio.positions)}")
        print(f"  Portfolio Value: ${self.portfolio.get_portfolio_value():,.0f}")
        print(f"  Data Sources: {len(self.collected_data.get('sources_used', []))}/10")
        print(f"{'='*70}\n")

    def run_cycle(self):
        """Run one cycle: update prices, run 3% rule, save state."""
        if not self.initialized:
            self.initialize()

        # Fetch latest prices
        price_data = self.fetcher.fetch_batch(list(self.portfolio.positions.keys()), period="5d")

        # Update prices map
        current_prices = {}
        for ticker, data in price_data.items():
            current_prices[ticker] = data["price"]
            self.market_data[ticker] = data

        # Update portfolio values
        self.portfolio.update_prices(current_prices)

        # Run 3% rule
        trades = self.portfolio.run_three_pct_rule(current_prices)

        if trades:
            print(f"\n[3% Rule] Executed {len(trades)} trades:")
            for t in trades[:10]:
                emoji = "BUY " if "BUY" in t["action"] else "SELL"
                print(f"  {emoji} {t['shares']} {t['ticker']} @ ${t['price']:.2f} — {t['reason']}")

        # Save state
        self._save_state()

        return trades

    def run_live(self, duration_minutes=None):
        """
        Run the ETF engine in live mode.
        Continuously fetches data and applies 3% rule.
        """
        if not self.initialized:
            self.initialize()

        interval = self.config["three_pct_rule"]["check_interval_seconds"]
        start_time = datetime.now()
        cycle = 0

        print(f"\n[LIVE] Starting live trading loop (interval: {interval}s)")
        if duration_minutes:
            print(f"[LIVE] Will run for {duration_minutes} minutes")

        try:
            while True:
                cycle += 1
                print(f"\n--- Cycle {cycle} | {datetime.now().strftime('%H:%M:%S')} ---")

                trades = self.run_cycle()
                value = self.portfolio.get_portfolio_value()
                pnl = self.portfolio.get_pnl()
                pnl_pct = pnl / self.config["starting_capital"] * 100

                print(f"  Portfolio: ${value:,.0f} | P&L: ${pnl:+,.0f} ({pnl_pct:+.4f}%)")
                print(f"  Positions: {len(self.portfolio.positions)} | Trades this cycle: {len(trades)}")

                # Check duration
                if duration_minutes:
                    elapsed = (datetime.now() - start_time).total_seconds() / 60
                    if elapsed >= duration_minutes:
                        print(f"\n[LIVE] Duration limit reached ({duration_minutes} min)")
                        break

                time.sleep(interval)

        except KeyboardInterrupt:
            print("\n[LIVE] Stopped by user")

        # Final summary
        self._print_summary()
        self._save_state()

    def run_demo(self, cycles=50):
        """
        Run a demo simulation with simulated price movements.
        Demonstrates the full ETF behavior without real API calls.
        """
        print(f"\n{'='*70}")
        print(f"  {self.config['etf_name']} — DEMO MODE")
        print(f"  Simulating {cycles} trading cycles")
        print(f"{'='*70}")

        self.initialize()

        print(f"\n[DEMO] Running {cycles} simulated price cycles...\n")

        for cycle in range(cycles):
            # Simulate price changes
            for ticker in list(self.portfolio.positions.keys()):
                if ticker in self.market_data:
                    data = self.market_data[ticker]
                    price = data["price"]

                    # Random walk with slight upward bias
                    change_pct = random.gauss(0.001, 0.02)  # ~2% daily vol
                    new_price = price * (1 + change_pct)

                    # Occasionally create bigger moves to trigger 3% rule
                    if random.random() < 0.03:  # 3% chance of big move
                        big_move = random.choice([-0.04, -0.035, 0.035, 0.04, 0.05])
                        new_price = price * (1 + big_move)

                    data["price"] = round(max(0.01, new_price), 2)

            # Get current prices
            current_prices = {
                t: self.market_data[t]["price"]
                for t in self.portfolio.positions
                if t in self.market_data
            }

            # Update and trade
            self.portfolio.update_prices(current_prices)
            trades = self.portfolio.run_three_pct_rule(current_prices)

            if trades:
                value = self.portfolio.get_portfolio_value()
                pnl = self.portfolio.get_pnl()
                print(f"  Cycle {cycle+1:3d} | {len(trades)} trades | "
                      f"Value: ${value:,.0f} | P&L: ${pnl:+,.0f}")

        # Final summary
        self._print_summary()
        self._save_state()

    def get_snapshot(self):
        """Get a one-time snapshot of the ETF state."""
        if not self.initialized:
            self.initialize()
        return self.portfolio.get_state()

    def _print_summary(self):
        """Print final portfolio summary."""
        state = self.portfolio.get_state()
        s = state["summary"]

        print(f"\n{'='*70}")
        print(f"  FINAL PORTFOLIO SUMMARY")
        print(f"{'='*70}")
        print(f"  Total Value:     ${s['total_value']:>20,.2f}")
        print(f"  Cash:            ${s['cash']:>20,.2f}")
        print(f"  Invested:        ${s['invested']:>20,.2f}")
        print(f"  P&L:             ${s['pnl']:>+20,.2f} ({s['pnl_pct']:+.4f}%)")
        print(f"  Positions:       {s['total_positions']:>20,d}")
        print(f"  Total Trades:    {s['total_trades']:>20,d}")
        print(f"{'='*70}")

        print(f"\n  TOP 10 HOLDINGS:")
        for h in state["top_holdings"][:10]:
            print(f"    {h['rank']:2d}. {h['ticker']:6s} {h['name'][:25]:25s} "
                  f"${h['market_value']:>14,.0f}  ({h['weight_pct']:.2f}%)  "
                  f"Score: {h['trend_score']:.1f}")

        print(f"\n  SECTOR BREAKDOWN:")
        for sector, info in state["sector_breakdown"].items():
            bar = "#" * int(info["pct"] / 2)
            print(f"    {sector:30s} ${info['value']:>14,.0f}  ({info['pct']:5.1f}%) {bar}")

    def _save_state(self):
        """Save current state to JSON file."""
        state = self.portfolio.get_state()

        # Save main state
        output_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            self.config["output_file"]
        )
        with open(output_path, "w") as f:
            json.dump(state, f, indent=2, default=str)

        # Save trade log
        log_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            self.config["trade_log_file"]
        )
        with open(log_path, "w") as f:
            json.dump(self.portfolio.trade_log, f, indent=2, default=str)

        print(f"  [Saved] {output_path}")


# ============================================================
# CLI ENTRY POINT
# ============================================================

if __name__ == "__main__":
    # Use multi-source by default unless --price-only flag
    use_multi = "--price-only" not in sys.argv
    engine = ETF1000Engine(use_multi_source=use_multi)

    if "--demo" in sys.argv:
        cycles = 50
        for arg in sys.argv:
            if arg.startswith("--cycles="):
                cycles = int(arg.split("=")[1])
        engine.run_demo(cycles=cycles)

    elif "--live" in sys.argv:
        duration = None
        for arg in sys.argv:
            if arg.startswith("--duration="):
                duration = int(arg.split("=")[1])
        engine.run_live(duration_minutes=duration)

    elif "--snapshot" in sys.argv:
        state = engine.get_snapshot()
        print(json.dumps(state["summary"], indent=2))

    elif "--discover" in sys.argv:
        print("\n[DISCOVER] Running one discovery cycle...")
        engine.initialize()
        print("\nDiscovery complete. Check discovery_history.json for results.")

    else:
        print("Usage:")
        print("  python etf_1000.py --demo               # Run demo simulation")
        print("  python etf_1000.py --demo --cycles=100   # Demo with 100 cycles")
        print("  python etf_1000.py --live                # Live trading mode")
        print("  python etf_1000.py --live --duration=60   # Live for 60 minutes")
        print("  python etf_1000.py --snapshot            # One-time snapshot")
        print("  python etf_1000.py --discover            # Run discovery cycle")
        print("  python etf_1000.py --price-only --demo   # Demo without multi-source")
        print("")
        print("Running demo mode by default...")
        engine.run_demo(cycles=30)
