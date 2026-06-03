"""
Pre-market data fetch: pulls OHLCV for all watchlist symbols from Alpha Vantage,
computes EMA/RSI/MACD/ATR locally to stay within 25 calls/day free tier limit,
detects setup flags, and writes to data/indicators_cache.json.
"""

import os
import json
import time
import logging
from datetime import datetime, date, timedelta
from pathlib import Path

import requests
import numpy as np
import pandas as pd
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

logging.basicConfig(
    filename="logs/fetch_indicators.log",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

AV_KEY = os.getenv("ALPHA_VANTAGE_API_KEY")
AV_BASE = "https://www.alphavantage.co/query"

WATCHLIST = ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "AMD", "JPM", "XLE"]


def fetch_daily_ohlcv(symbol: str) -> pd.DataFrame:
    params = {
        "function": "TIME_SERIES_DAILY",
        "symbol": symbol,
        "outputsize": "compact",
        "apikey": AV_KEY,
    }
    r = requests.get(AV_BASE, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()

    if "Time Series (Daily)" not in data:
        raise ValueError(f"No time series data for {symbol}: {data.get('Note', data.get('Information', 'unknown error'))}")

    ts = data["Time Series (Daily)"]
    rows = []
    for d, vals in ts.items():
        rows.append({
            "date": pd.to_datetime(d),
            "open": float(vals["1. open"]),
            "high": float(vals["2. high"]),
            "low": float(vals["3. low"]),
            "close": float(vals["4. close"]),
            "volume": float(vals["5. volume"]),
        })
    df = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    return df


def fetch_vix() -> float:
    """Fetch VIX last close via Alpha Vantage."""
    params = {
        "function": "TIME_SERIES_DAILY",
        "symbol": "VIX",
        "apikey": AV_KEY,
    }
    r = requests.get(AV_BASE, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()
    ts = data.get("Time Series (Daily)", {})
    if not ts:
        logging.warning("VIX data unavailable, defaulting to 20")
        return 20.0
    latest = sorted(ts.keys())[-1]
    return float(ts[latest]["4. close"])


def fetch_earnings_calendar() -> dict:
    """Returns dict of symbol -> nearest earnings date (within 10 days)."""
    params = {
        "function": "EARNINGS_CALENDAR",
        "horizon": "3month",
        "apikey": AV_KEY,
    }
    r = requests.get(AV_BASE, params=params, timeout=30)
    r.raise_for_status()

    earnings = {}
    today = date.today()
    cutoff = today + timedelta(days=10)

    for line in r.text.splitlines()[1:]:  # CSV, skip header
        parts = line.split(",")
        if len(parts) < 3:
            continue
        symbol, name, report_date_str = parts[0], parts[1], parts[2]
        if symbol not in WATCHLIST:
            continue
        try:
            report_date = datetime.strptime(report_date_str, "%Y-%m-%d").date()
        except ValueError:
            continue
        if today <= report_date <= cutoff:
            days_away = (report_date - today).days
            earnings[symbol] = {"date": report_date_str, "days_away": days_away}

    return earnings


# ── Indicator computations ────────────────────────────────────────────────────

def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, adjust=False).mean()
    avg_loss = loss.ewm(com=period - 1, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def macd(series: pd.Series, fast=12, slow=26, signal=9):
    fast_ema = ema(series, fast)
    slow_ema = ema(series, slow)
    macd_line = fast_ema - slow_ema
    signal_line = ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = df["high"]
    low = df["low"]
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(com=period - 1, adjust=False).mean()


def compute_indicators(df: pd.DataFrame) -> dict:
    close = df["close"]
    vol = df["volume"]

    e20 = ema(close, 20)
    e50 = ema(close, 50)
    e200 = ema(close, 200)
    rsi14 = rsi(close, 14)
    _, _, macd_hist = macd(close)
    atr14 = atr(df, 14)
    vol_sma20 = vol.rolling(20).mean()

    # 52-week high
    high_52wk = df["high"].rolling(252).max().iloc[-1]

    latest = df.iloc[-1]
    prev = df.iloc[-2]

    return {
        "price": round(float(close.iloc[-1]), 2),
        "daily_change_pct": round((float(close.iloc[-1]) / float(close.iloc[-2]) - 1) * 100, 2),
        "volume": int(latest["volume"]),
        "volume_sma20": round(float(vol_sma20.iloc[-1]), 0),
        "volume_ratio": round(float(vol.iloc[-1]) / float(vol_sma20.iloc[-1]), 2),
        "ema20": round(float(e20.iloc[-1]), 2),
        "ema50": round(float(e50.iloc[-1]), 2),
        "ema200": round(float(e200.iloc[-1]), 2),
        "rsi_14": round(float(rsi14.iloc[-1]), 1),
        "macd_histogram": round(float(macd_hist.iloc[-1]), 4),
        "macd_histogram_prev": round(float(macd_hist.iloc[-2]), 4),
        "atr_14": round(float(atr14.iloc[-1]), 2),
        "high_52wk": round(float(high_52wk), 2),
    }


# ── Setup flag detection ──────────────────────────────────────────────────────

def detect_setup_a(ind: dict, df: pd.DataFrame) -> bool:
    """EMA-20 pullback in uptrend."""
    price = ind["price"]
    ema20 = ind["ema20"]
    ema50 = ind["ema50"]
    ema200 = ind["ema200"]
    rsi14 = ind["rsi_14"]
    vol_ratio = ind["volume_ratio"]

    trend_up = ema20 > ema50 > ema200
    near_ema20 = abs(price - ema20) / ema20 <= 0.01
    closes_above = price > ema20
    rsi_range = 40 <= rsi14 <= 60
    volume_ok = vol_ratio >= 0.80

    return trend_up and near_ema20 and closes_above and rsi_range and volume_ok


def detect_setup_b(ind: dict, df: pd.DataFrame) -> bool:
    """Breakout from tight consolidation."""
    if len(df) < 10:
        return False

    # Look at last 5-20 bars for consolidation
    recent = df.tail(20)
    for window in range(5, min(16, len(recent))):
        consol = recent.iloc[-window - 1:-1]
        consol_high = consol["high"].max()
        consol_low = consol["low"].min()
        height_pct = (consol_high - consol_low) / consol_low

        if height_pct > 0.08:
            continue  # too wide

        price = ind["price"]
        vol_ratio = ind["volume_ratio"]
        close = df["close"].iloc[-1]
        bar_high = df["high"].iloc[-1]

        breakout = price > consol_high
        # closes near high (within 20% of bar range from top)
        bar_range = bar_high - df["low"].iloc[-1]
        closes_near_high = bar_range == 0 or (bar_high - close) / bar_range <= 0.20
        volume_ok = vol_ratio >= 1.50

        if breakout and closes_near_high and volume_ok:
            return True

    return False


def detect_setup_c(ind: dict, df: pd.DataFrame) -> bool:
    """Mean reversion on oversold strong name."""
    if len(df) < 3:
        return False

    close = df["close"]
    rsi14_series = rsi(close, 14)

    above_ema200 = ind["price"] > ind["ema200"]
    prev_rsi = float(rsi14_series.iloc[-2])
    curr_rsi = ind["rsi_14"]
    vol_ratio = ind["volume_ratio"]

    was_oversold = prev_rsi < 30
    now_recovering = curr_rsi >= 30
    volume_ok = vol_ratio >= 1.00

    return above_ema200 and was_oversold and now_recovering and volume_ok


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    if not AV_KEY:
        raise EnvironmentError("ALPHA_VANTAGE_API_KEY not set in .env")

    logging.info("Starting indicator fetch for %s", WATCHLIST)
    result = {}
    dfs = {}

    # Fetch OHLCV — 1 call per symbol (8 calls total for watchlist)
    for i, symbol in enumerate(WATCHLIST):
        try:
            logging.info("Fetching %s (%d/%d)", symbol, i + 1, len(WATCHLIST))
            df = fetch_daily_ohlcv(symbol)
            ind = compute_indicators(df)
            ind["setup_flags"] = {
                "A_pullback": detect_setup_a(ind, df),
                "B_breakout": detect_setup_b(ind, df),
                "C_reversion": detect_setup_c(ind, df),
            }
            result[symbol] = ind
            dfs[symbol] = df
        except Exception as e:
            logging.error("Failed to fetch %s: %s", symbol, e)
            result[symbol] = {"error": str(e)}

        # Alpha Vantage free tier: 5 calls/min, respect it
        if i < len(WATCHLIST) - 1:
            time.sleep(13)

    # Fetch VIX (1 extra call)
    try:
        time.sleep(13)
        vix = fetch_vix()
        result["_vix"] = vix
        logging.info("VIX: %.1f", vix)
    except Exception as e:
        logging.warning("VIX fetch failed: %s", e)
        result["_vix"] = 20.0

    # Earnings calendar (1 extra call)
    try:
        time.sleep(13)
        earnings = fetch_earnings_calendar()
        for symbol in WATCHLIST:
            if symbol in result and "error" not in result[symbol]:
                e_info = earnings.get(symbol)
                result[symbol]["earnings_within_5d"] = e_info is not None and e_info["days_away"] <= 5
                result[symbol]["earnings_date"] = e_info["date"] if e_info else None
    except Exception as e:
        logging.warning("Earnings calendar fetch failed: %s", e)
        for symbol in WATCHLIST:
            if symbol in result and "error" not in result[symbol]:
                result[symbol]["earnings_within_5d"] = False
                result[symbol]["earnings_date"] = None

    result["_fetched_at"] = datetime.utcnow().isoformat() + "Z"

    out_path = "data/indicators_cache.json"
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2)

    logging.info("Wrote %s", out_path)
    print(f"Indicators cached to {out_path}")


if __name__ == "__main__":
    main()
