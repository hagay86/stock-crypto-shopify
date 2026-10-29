# TrendScore Engine — Setup Guide

## What You're Building

An algorithm that:
1. **Scores stocks by online buzz** (who's talking about them, how much, positive or negative)
2. **Automatically trades** based on a 3% daily rule (sell 50% on drops, buy 50% on rises)
3. **Runs on autopilot** until you stop it

---

## Step 1: Install Python

If you don't have Python installed:
- Go to https://python.org/downloads
- Download Python 3.11 or newer
- During install, CHECK the box that says "Add Python to PATH"

---

## Step 2: Install Required Libraries

Open Terminal (Mac) or Command Prompt (Windows) and run:

```
pip install pytrends praw requests textblob
```

For paper trading (later):
```
pip install alpaca-trade-api
```

---

## Step 3: Get Your Free API Keys

### Reddit API (Free)
1. Go to https://www.reddit.com/prefs/apps
2. Click "create another app..."
3. Pick **"script"** as the type
4. Name it anything (e.g., "TrendScore")
5. Set redirect URI to `http://localhost`
6. Click "create app"
7. Copy the **client ID** (under the app name) and **secret**

### NewsAPI (Free — 500 requests/day)
1. Go to https://newsapi.org/register
2. Sign up with email
3. Copy your API key from the dashboard

### Alpaca Paper Trading (Free — for later)
1. Go to https://alpaca.markets
2. Sign up for free
3. Go to Paper Trading > API Keys
4. Generate and copy your key + secret

---

## Step 4: Add Your Keys

Open `trendscore.py` and find the CONFIG section at the top.
Replace the placeholder values:

```python
CONFIG = {
    "reddit_client_id": "paste_your_id_here",
    "reddit_client_secret": "paste_your_secret_here",
    "newsapi_key": "paste_your_key_here",
    ...
}
```

---

## Step 5: Test It

### Run the demo first (no API keys needed):
```
python trendscore.py --demo
```
This shows you how the scoring works with simulated data.

### Run with real data:
```
python trendscore.py
```
This pulls real mentions from Reddit and news, then scores all 10 stocks.

### Run the auto-trader demo:
```
python auto_trader.py
```
This simulates a full trading day with the 3% rule.

---

## Step 6: Run It Daily

Once everything works, you'd run the TrendScore collection hourly
and the auto-trader continuously during market hours (9:30am - 4pm ET).

For now, run manually and check the results. We'll automate later.

---

## Files

| File | What it does |
|------|-------------|
| `trendscore.py` | The scoring engine — collects data and ranks stocks |
| `auto_trader.py` | The trading engine — executes the 3% buy/sell rule |
| `trendscore_latest.json` | Most recent scores (auto-generated) |
| `demo_results.json` | Demo trading results (auto-generated) |

---

## What's Next

1. Run the demo, see the scores
2. Get API keys, run with real data
3. Paper trade for 2-3 months
4. Document performance
5. Build the pitch deck with real numbers
