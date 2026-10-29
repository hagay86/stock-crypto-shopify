"""
Auto Trader — The execution engine that trades based on TrendScore + 3% Rule
=============================================================================

This connects TrendScore rankings to actual trade decisions.

STRATEGY:
1. TrendScore picks WHICH stocks to be in (highest online footprint)
2. The 3% Rule manages HOW MUCH to hold:
   - If a stock drops 3% from today's open → sell 50% of position
   - If a stock rises 3% from today's open → buy 50% more
   - Cycle repeats throughout the day
   - User sets stop date or runs infinite loop

SETUP:
    pip install alpaca-trade-api   (for paper trading — free)
    Get API key at https://alpaca.markets (free account, paper trading)
"""

import json
import time
from datetime import datetime, timedelta
from collections import defaultdict


# ============================================================
# CONFIGURATION
# ============================================================

TRADE_CONFIG = {
    # Alpaca Paper Trading — Free. Sign up at https://alpaca.markets
    # Go to: Paper Trading > API Keys > Generate
    "alpaca_api_key": "YOUR_ALPACA_KEY",
    "alpaca_secret_key": "YOUR_ALPACA_SECRET",
    "alpaca_base_url": "https://paper-api.alpaca.markets",  # Paper = fake money

    # STRATEGY SETTINGS
    "drop_threshold_pct": 3.0,     # Sell when stock drops this % from daily open
    "rise_threshold_pct": 3.0,     # Buy when stock rises this % from daily open
    "sell_pct": 50,                # Sell this % of position on drop
    "buy_pct": 50,                 # Buy this % more on rise
    "max_cycles_per_day": 5,       # Max buy/sell cycles per stock per day
    "check_interval_seconds": 60,  # How often to check prices (60 = every minute)

    # PORTFOLIO
    "starting_cash": 100000,
    "max_stocks": 10,              # Max stocks in portfolio at once
    "max_per_stock_pct": 15,       # Max % of portfolio in one stock
}


# ============================================================
# PORTFOLIO TRACKER (Local — no broker needed for testing)
# ============================================================

class Portfolio:
    """
    Tracks your positions, cash, and trade history.
    Works in "simulation mode" without a broker for testing.
    """

    def __init__(self, starting_cash=100000):
        self.cash = starting_cash
        self.positions = {}     # { "AAPL": {"shares": 25, "avg_cost": 218.50} }
        self.trade_log = []     # List of all trades
        self.daily_opens = {}   # { "AAPL": 218.27 } — set at market open
        self.daily_cycles = defaultdict(int)  # Track cycles per stock today
        self.start_value = starting_cash

    def set_daily_opens(self, prices):
        """Call this at market open with current prices."""
        self.daily_opens = dict(prices)
        self.daily_cycles = defaultdict(int)  # Reset cycle count
        print(f"\n[Portfolio] Daily opens set for {len(prices)} stocks")

    def buy(self, symbol, current_price, pct_of_position=50):
        """
        Buy more shares of a stock.
        pct_of_position: buy this % more relative to current position value.
        """
        current_value = self.positions.get(symbol, {}).get("shares", 0) * current_price
        buy_value = current_value * (pct_of_position / 100) if current_value > 0 else min(self.cash * 0.1, 10000)

        if buy_value > self.cash:
            buy_value = self.cash

        if buy_value < 10:  # Minimum trade
            return None

        shares_to_buy = int(buy_value / current_price)
        if shares_to_buy == 0:
            return None

        cost = shares_to_buy * current_price
        self.cash -= cost

        pos = self.positions.get(symbol, {"shares": 0, "avg_cost": 0})
        total_shares = pos["shares"] + shares_to_buy
        total_cost = pos["shares"] * pos["avg_cost"] + cost
        avg_cost = total_cost / total_shares if total_shares > 0 else 0

        self.positions[symbol] = {"shares": total_shares, "avg_cost": avg_cost}

        trade = {
            "time": datetime.now().isoformat(),
            "action": "BUY",
            "symbol": symbol,
            "shares": shares_to_buy,
            "price": current_price,
            "value": round(cost, 2),
            "reason": f"Price up {pct_of_position}% rule",
        }
        self.trade_log.append(trade)
        self.daily_cycles[symbol] += 1

        print(f"  💰 BUY  {shares_to_buy} {symbol} @ ${current_price:.2f} (${cost:,.2f})")
        return trade

    def sell(self, symbol, current_price, pct_of_position=50):
        """
        Sell a percentage of your position.
        """
        pos = self.positions.get(symbol)
        if not pos or pos["shares"] == 0:
            return None

        shares_to_sell = max(1, int(pos["shares"] * pct_of_position / 100))
        if shares_to_sell > pos["shares"]:
            shares_to_sell = pos["shares"]

        revenue = shares_to_sell * current_price
        self.cash += revenue

        remaining = pos["shares"] - shares_to_sell
        if remaining == 0:
            del self.positions[symbol]
        else:
            self.positions[symbol]["shares"] = remaining

        profit = (current_price - pos["avg_cost"]) * shares_to_sell

        trade = {
            "time": datetime.now().isoformat(),
            "action": "SELL",
            "symbol": symbol,
            "shares": shares_to_sell,
            "price": current_price,
            "value": round(revenue, 2),
            "profit": round(profit, 2),
            "reason": f"Price down {pct_of_position}% rule",
        }
        self.trade_log.append(trade)
        self.daily_cycles[symbol] += 1

        emoji = "🟢" if profit >= 0 else "🔴"
        print(f"  {emoji} SELL {shares_to_sell} {symbol} @ ${current_price:.2f} (P&L: ${profit:+,.2f})")
        return trade

    def total_value(self, current_prices):
        """Calculate total portfolio value."""
        stock_value = sum(
            self.positions.get(sym, {}).get("shares", 0) * current_prices.get(sym, 0)
            for sym in self.positions
        )
        return self.cash + stock_value

    def summary(self, current_prices):
        """Print portfolio summary."""
        total = self.total_value(current_prices)
        pnl = total - self.start_value
        pnl_pct = (pnl / self.start_value) * 100

        print("\n" + "=" * 60)
        print("  PORTFOLIO SUMMARY")
        print("=" * 60)
        print(f"  Cash:         ${self.cash:>12,.2f}")

        stock_total = 0
        for sym, pos in sorted(self.positions.items()):
            price = current_prices.get(sym, 0)
            value = pos["shares"] * price
            stock_total += value
            gain = (price - pos["avg_cost"]) / pos["avg_cost"] * 100 if pos["avg_cost"] > 0 else 0
            emoji = "🟢" if gain >= 0 else "🔴"
            print(f"  {emoji} {sym:6s}  {pos['shares']:4d} shares × ${price:>8.2f} = ${value:>10,.2f}  ({gain:+.1f}%)")

        print(f"  {'─'*56}")
        print(f"  Stocks:       ${stock_total:>12,.2f}")
        print(f"  Total:        ${total:>12,.2f}")

        emoji = "🟢" if pnl >= 0 else "🔴"
        print(f"  {emoji} P&L:       ${pnl:>+12,.2f} ({pnl_pct:+.2f}%)")
        print(f"  Trades today: {len([t for t in self.trade_log if t['time'][:10] == datetime.now().strftime('%Y-%m-%d')])}")
        print("=" * 60)


# ============================================================
# THE 3% RULE ENGINE
# ============================================================

class ThreePercentRule:
    """
    The core trading logic:
    - Check each stock's price vs daily open
    - If down 3% → sell 50%
    - If up 3% → buy 50%
    - Repeat until max cycles or user stop time
    """

    def __init__(self, portfolio, config=None):
        self.portfolio = portfolio
        self.config = config or TRADE_CONFIG
        self.active = True
        self.stop_time = None  # User can set a stop datetime

    def set_stop_time(self, stop_datetime):
        """Set when the algorithm should stop. Pass None for infinite loop."""
        self.stop_time = stop_datetime
        if stop_datetime:
            print(f"[Rule] Will stop at {stop_datetime.strftime('%Y-%m-%d %H:%M')}")
        else:
            print("[Rule] Running in infinite loop mode (pause manually)")

    def check(self, current_prices):
        """
        Run one check cycle. Call this every minute (or however often you want).
        Returns list of trades executed.
        """
        if not self.active:
            return []

        # Check stop time
        if self.stop_time and datetime.now() >= self.stop_time:
            self.active = False
            print("[Rule] Stop time reached. Algorithm paused.")
            return []

        trades = []
        max_cycles = self.config["max_cycles_per_day"]

        for symbol in list(self.portfolio.positions.keys()):
            # Skip if we've hit max cycles for this stock today
            if self.portfolio.daily_cycles[symbol] >= max_cycles:
                continue

            current = current_prices.get(symbol)
            open_price = self.portfolio.daily_opens.get(symbol)

            if not current or not open_price:
                continue

            change_pct = ((current - open_price) / open_price) * 100

            # DROP RULE: Stock dropped 3% from open → SELL 50%
            if change_pct <= -self.config["drop_threshold_pct"]:
                trade = self.portfolio.sell(
                    symbol, current,
                    pct_of_position=self.config["sell_pct"]
                )
                if trade:
                    trade["reason"] = f"Down {change_pct:.1f}% from open (threshold: -{self.config['drop_threshold_pct']}%)"
                    trades.append(trade)

            # RISE RULE: Stock rose 3% from open → BUY 50% more
            elif change_pct >= self.config["rise_threshold_pct"]:
                trade = self.portfolio.buy(
                    symbol, current,
                    pct_of_position=self.config["buy_pct"]
                )
                if trade:
                    trade["reason"] = f"Up {change_pct:.1f}% from open (threshold: +{self.config['rise_threshold_pct']}%)"
                    trades.append(trade)

        return trades


# ============================================================
# COMBINED: TrendScore + 3% Rule
# ============================================================

def run_full_algorithm(trendscore_rankings, portfolio, current_prices, config=None):
    """
    The full algorithm in one function:
    1. Use TrendScore rankings to decide which stocks to be in
    2. Buy into top-ranked stocks if not already holding
    3. Apply 3% rule to manage positions

    Call this on a regular interval (every minute during market hours).
    """
    config = config or TRADE_CONFIG

    # Step 1: Get top stocks from TrendScore
    top_stocks = [r["symbol"] for r in trendscore_rankings[:config["max_stocks"]]]

    # Step 2: Buy into top-ranked stocks we don't already hold
    for sym in top_stocks:
        if sym not in portfolio.positions and sym in current_prices:
            # Allocate equal portion of cash to each new stock
            allocation = portfolio.cash * (config["max_per_stock_pct"] / 100)
            allocation = min(allocation, portfolio.cash * 0.2)  # Never more than 20% of cash at once

            if allocation > 100:  # Minimum $100 buy
                shares = int(allocation / current_prices[sym])
                if shares > 0:
                    portfolio.buy(sym, current_prices[sym])
                    print(f"  [TrendScore] Entered {sym} — Score: {trendscore_rankings[[r['symbol'] for r in trendscore_rankings].index(sym)]['total_score']}")

    # Step 3: Sell stocks that dropped out of top rankings
    for sym in list(portfolio.positions.keys()):
        if sym not in top_stocks:
            print(f"  [TrendScore] {sym} dropped out of top {config['max_stocks']} — selling")
            portfolio.sell(sym, current_prices[sym], pct_of_position=100)

    # Step 4: Apply 3% rule to all positions
    rule = ThreePercentRule(portfolio, config)
    trades = rule.check(current_prices)

    return trades


# ============================================================
# DEMO: Run with simulated prices
# ============================================================

def run_demo():
    """
    Simulate a trading day with the full algorithm.
    Shows how TrendScore + 3% Rule work together.
    """
    import random

    print("\n" + "=" * 60)
    print("  AUTO TRADER DEMO — Simulated Trading Day")
    print("=" * 60)

    # Initial prices (approximate real values)
    prices = {
        "AAPL": 218.27, "MSFT": 421.50, "NVDA": 882.35,
        "AMZN": 194.60, "GOOGL": 171.82, "META": 582.14,
        "BRK.B": 462.30, "TSLA": 261.45, "AVGO": 186.70,
        "JPM": 232.80,
    }

    # Simulated TrendScore rankings
    fake_rankings = [
        {"symbol": "NVDA",  "total_score": 82.3},
        {"symbol": "TSLA",  "total_score": 71.5},
        {"symbol": "META",  "total_score": 68.2},
        {"symbol": "AAPL",  "total_score": 61.8},
        {"symbol": "AMZN",  "total_score": 57.4},
        {"symbol": "MSFT",  "total_score": 55.1},
        {"symbol": "AVGO",  "total_score": 48.9},
        {"symbol": "JPM",   "total_score": 42.3},
        {"symbol": "GOOGL", "total_score": 38.7},
        {"symbol": "BRK.B", "total_score": 31.2},
    ]

    # Create portfolio
    portfolio = Portfolio(starting_cash=100000)

    print("\n📊 TrendScore Rankings:")
    for i, r in enumerate(fake_rankings):
        print(f"   #{i+1} {r['symbol']:6s} — Score: {r['total_score']}")

    # Set daily opens
    portfolio.set_daily_opens(prices)

    # Initial buy based on TrendScore (top 10)
    print("\n📈 Initial portfolio allocation based on TrendScore...")
    for r in fake_rankings[:10]:
        sym = r["symbol"]
        allocation = portfolio.cash * 0.09  # ~9% each
        shares = int(allocation / prices[sym])
        if shares > 0:
            portfolio.buy(sym, prices[sym])

    portfolio.summary(prices)

    # Simulate price movements throughout the day
    print("\n⏰ Simulating trading day (30 price updates)...")
    print("-" * 60)

    rule = ThreePercentRule(portfolio)

    for tick in range(30):
        # Random price movements
        for sym in prices:
            change = (random.random() - 0.48) * prices[sym] * 0.008  # Slight upward bias
            prices[sym] = round(prices[sym] + change, 2)

        # Make some stocks move more dramatically to trigger rules
        if tick == 8:
            prices["TSLA"] *= 0.965  # -3.5% drop
            print(f"\n  ⚠️  TSLA drops sharply to ${prices['TSLA']:.2f}!")
        if tick == 15:
            prices["NVDA"] *= 1.035  # +3.5% rise
            print(f"\n  🚀 NVDA surges to ${prices['NVDA']:.2f}!")
        if tick == 22:
            prices["META"] *= 0.96   # -4% drop
            print(f"\n  ⚠️  META drops to ${prices['META']:.2f}!")

        # Run the 3% rule
        trades = rule.check(prices)

    # Final summary
    portfolio.summary(prices)

    # Trade history
    print(f"\n📋 Trade Log ({len(portfolio.trade_log)} trades):")
    for t in portfolio.trade_log[-10:]:  # Last 10
        emoji = "💰" if t["action"] == "BUY" else "💸"
        print(f"   {emoji} {t['action']} {t['shares']} {t['symbol']} @ ${t['price']:.2f} — {t.get('reason', '')}")

    # Save results
    results = {
        "date": datetime.now().isoformat(),
        "final_value": portfolio.total_value(prices),
        "starting_value": portfolio.start_value,
        "pnl": portfolio.total_value(prices) - portfolio.start_value,
        "trades": portfolio.trade_log,
    }
    with open("demo_results.json", "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n  Results saved to demo_results.json")


if __name__ == "__main__":
    run_demo()
