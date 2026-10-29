# TrendScore ETF-1000 — API Keys Setup Guide

## Overview

The TrendScore engine pulls data from **10 real-time sources**. 7 of them need free API keys. Here's exactly where to get each one and what they do.

---

## Quick Status

| # | Source | API Key? | Free Tier | What It Does |
|---|--------|----------|-----------|--------------|
| 1 | Yahoo Finance | NO key needed | Unlimited | Live prices, volume, history |
| 2 | Reddit (PRAW) | YES (free) | 100 req/min | Social mentions from r/wallstreetbets etc. |
| 3 | Google Trends | NO key needed | Unlimited | Search interest for stock names |
| 4 | NewsAPI | YES (free) | 500 req/day | News articles mentioning stocks |
| 5 | Marketaux | YES (free) | 100 req/day | News sentiment analysis |
| 6 | Finnhub | YES (free) | 60 req/min | Social sentiment + analyst ratings |
| 7 | Alpha Vantage | YES (free) | 25 req/day | Top gainers/losers/most active |
| 8 | Financial Modeling Prep | YES (free) | 250 req/day | Sector performance + screener |
| 9 | StockTwits | NO key needed | Public feed | Trending stocks + sentiment |
| 10 | Polygon.io | YES (free) | 5 req/min | Comprehensive market snapshots |

**Total cost: $0.00** — All free tiers are sufficient for the ETF engine.

---

## Step-by-Step Setup

### 1. Yahoo Finance — NO SETUP NEEDED
Already built in via the `yfinance` Python package.
```
pip install yfinance
```

### 2. Reddit API Key
1. Go to: https://www.reddit.com/prefs/apps
2. Click "Create App" or "Create Another App"
3. Select **"script"** as the app type
4. Name: `TrendScore` (anything works)
5. Redirect URI: `http://localhost:8080`
6. Click "Create app"
7. Copy the **client_id** (shown under the app name) and **client_secret**

```
pip install praw
```

### 3. Google Trends — NO SETUP NEEDED
Uses the `pytrends` library, no API key required.
```
pip install pytrends
```

### 4. NewsAPI
1. Go to: https://newsapi.org/register
2. Sign up with email
3. Copy your API key from the dashboard

### 5. Marketaux
1. Go to: https://www.marketaux.com/register
2. Sign up with email
3. Copy your API key from the dashboard

### 6. Finnhub
1. Go to: https://finnhub.io/register
2. Sign up with email
3. Copy your API key from the dashboard

### 7. Alpha Vantage
1. Go to: https://www.alphavantage.co/support/#api-key
2. Enter your name and email
3. Click "Get Free API Key"
4. Copy the key shown on screen

### 8. Financial Modeling Prep (FMP)
1. Go to: https://site.financialmodelingprep.com/developer/docs
2. Click "Get API Key" or "Sign Up"
3. Copy your API key from the dashboard

### 9. StockTwits — NO SETUP NEEDED
The trending endpoint is public and requires no authentication.

### 10. Polygon.io
1. Go to: https://polygon.io/dashboard/signup
2. Sign up with email
3. Copy your API key from the dashboard

---

## Configure Your Keys

After getting your keys, edit the file `trendscore_engine/api_keys.json`:

```json
{
  "reddit": {
    "client_id": "YOUR_REDDIT_CLIENT_ID",
    "client_secret": "YOUR_REDDIT_CLIENT_SECRET",
    "user_agent": "TrendScore/2.0"
  },
  "newsapi": {
    "api_key": "YOUR_NEWSAPI_KEY"
  },
  "marketaux": {
    "api_key": "YOUR_MARKETAUX_KEY"
  },
  "finnhub": {
    "api_key": "YOUR_FINNHUB_KEY"
  },
  "alpha_vantage": {
    "api_key": "YOUR_ALPHA_VANTAGE_KEY"
  },
  "fmp": {
    "api_key": "YOUR_FMP_KEY"
  },
  "polygon": {
    "api_key": "YOUR_POLYGON_KEY"
  }
}
```

The file is auto-generated on first run if it doesn't exist.

---

## Install All Dependencies

```bash
pip install yfinance pytrends praw requests textblob pandas numpy
```

---

## Test Your Setup

```bash
cd trendscore_engine
python data_sources.py
```

This will show which sources connected successfully and which still need keys.

---

## How Sources Feed Into TrendScore

The 12-factor scoring model:

**Price factors (50% of score):**
- Price momentum 5-day (10%)
- Price momentum 20-day (8%)
- Volume spike (12%)
- Volatility (5%)
- Relative strength / RSI (10%)
- Market cap tier bonus (5%)

**Sector (10%):**
- Sector momentum (10%)

**Social (15%):**
- Social buzz — Reddit + StockTwits + Finnhub mentions (8%)
- Social sentiment — averaged across all social sources (7%)

**News (10%):**
- News coverage — article count from NewsAPI + Marketaux (5%)
- News sentiment — averaged sentiment scores (5%)

**Search interest (5%):**
- Google Trends interest score (5%)

**Discovery heat (10%):**
- How many sources independently flagged this stock as trending (10%)
