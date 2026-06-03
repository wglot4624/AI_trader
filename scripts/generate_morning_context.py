"""
Generates morning_context.json from cached indicators + live Alpaca account state.
Run at 8:00 AM ET on trading days (after fetch_indicators.py).
"""

import json
import logging
import os
import sys
from datetime import datetime, date, timedelta
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

sys.path.insert(0, str(Path(__file__).parent))
from risk_gate import get_state_summary

logging.basicConfig(
    filename="logs/morning_context.log",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

WATCHLIST = ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "AMD", "JPM", "XLE"]

ECONOMIC_EVENTS = [
    # Manually maintained — update weekly
    # {"date": "2025-06-04", "event": "FOMC Minutes", "impact": "HIGH"},
]


def load_indicators() -> dict:
    path = Path("data/indicators_cache.json")
    if not path.exists():
        raise FileNotFoundError("data/indicators_cache.json not found — run fetch_indicators.py first")

    with open(path) as f:
        data = json.load(f)

    # Validate freshness (must be from today)
    fetched_at = data.get("_fetched_at", "")
    if fetched_at:
        fetched_date = fetched_at[:10]
        today = date.today().isoformat()
        if fetched_date != today:
            logging.warning("Indicators cache is from %s, today is %s", fetched_date, today)

    return data


def classify_regime(spy: dict, vix: float) -> dict:
    """Classify market regime based on SPY indicators and VIX."""
    ema20 = spy.get("ema20", 0)
    ema50 = spy.get("ema50", 0)
    ema200 = spy.get("ema200", 0)
    rsi14 = spy.get("rsi_14", 50)
    price = spy.get("price", 0)
    high_52wk = spy.get("high_52wk", price)
    daily_change_pct = spy.get("daily_change_pct", 0)

    pct_from_52wk_high = ((price - high_52wk) / high_52wk * 100) if high_52wk > 0 else 0

    # NO TRADE conditions take priority
    if price < ema200:
        return {
            "classification": "NO_TRADE_RISK_OFF",
            "reason": "SPY below 200 EMA",
            "setups_active": [],
        }
    if daily_change_pct <= -3.0:
        return {
            "classification": "NO_TRADE_RISK_OFF",
            "reason": f"SPY dropped {daily_change_pct:.1f}% today",
            "setups_active": [],
        }
    if vix > 30:
        return {
            "classification": "NO_TRADE_RISK_OFF",
            "reason": f"VIX at {vix:.1f} (> 30)",
            "setups_active": [],
        }

    # Trending up
    if ema20 > ema50 > ema200 and rsi14 > 50 and pct_from_52wk_high >= -5.0:
        return {
            "classification": "TRENDING_UP",
            "reason": "EMA stack bullish, RSI > 50, within 5% of 52wk high",
            "setups_active": ["A", "B"],
        }

    # Choppy / range
    ema_spread = abs(ema20 - ema50) / ema50 * 100 if ema50 > 0 else 100
    if 40 <= rsi14 <= 60 and ema_spread < 3.0:
        return {
            "classification": "CHOPPY_RANGE",
            "reason": "EMAs converging, RSI neutral 40-60",
            "setups_active": ["C", "B"],
        }

    # Default: choppy
    return {
        "classification": "CHOPPY_RANGE",
        "reason": "No clear trend signal",
        "setups_active": ["C"],
    }


def get_alpaca_state() -> dict:
    """Pull account value and open positions from Alpaca."""
    api_key = os.getenv("ALPACA_API_KEY")
    secret_key = os.getenv("ALPACA_SECRET_KEY")
    base_url = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

    try:
        from alpaca.trading.client import TradingClient
        from alpaca.trading.requests import GetAssetsRequest

        is_paper = "paper" in base_url
        client = TradingClient(api_key, secret_key, paper=is_paper)
        account = client.get_account()

        account_value = float(account.portfolio_value)
        cash = float(account.cash)

        positions_raw = client.get_all_positions()
        positions = []
        for p in positions_raw:
            positions.append({
                "symbol": p.symbol,
                "entry_price": round(float(p.avg_entry_price), 2),
                "current_price": round(float(p.current_price), 2),
                "shares": round(float(p.qty), 4),
                "pnl_dollars": round(float(p.unrealized_pl), 2),
                "pnl_pct": round(float(p.unrealized_plpc) * 100, 2),
                "market_value": round(float(p.market_value), 2),
                # stop/target loaded from state file if tracked separately
                "stop_level": None,
                "target_level": None,
                "days_held": None,
                "pnl_r": None,
                "stop_at_breakeven": False,
                "action_required": "Review",
            })

        return {
            "account_value": round(account_value, 2),
            "cash_available": round(cash, 2),
            "open_positions": len(positions),
            "positions": positions,
        }

    except ImportError:
        logging.warning("alpaca-py not installed — using mock account state")
    except Exception as e:
        logging.error("Alpaca API error: %s", e)

    # Fallback if Alpaca unavailable
    return {
        "account_value": 0.0,
        "cash_available": 0.0,
        "open_positions": 0,
        "positions": [],
        "error": "Alpaca unavailable — set .env keys and ensure alpaca-py is installed",
    }


def load_position_stops() -> dict:
    """Load manually tracked stop/target levels from data/positions_state.json."""
    path = Path("data/positions_state.json")
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}


def enrich_positions(positions: list, stops: dict, indicators: dict) -> list:
    """Merge stop/target data and compute R-multiples."""
    for p in positions:
        sym = p["symbol"]
        if sym in stops:
            s = stops[sym]
            p["stop_level"] = s.get("stop_level")
            p["target_level"] = s.get("target_level")
            p["entry_price"] = p["entry_price"] or s.get("entry_price")
            p["days_held"] = s.get("days_held")

            if p["stop_level"] and p["entry_price"]:
                initial_risk = p["entry_price"] - p["stop_level"]
                if initial_risk > 0:
                    p["pnl_r"] = round((p["current_price"] - p["entry_price"]) / initial_risk, 2)
                    p["stop_at_breakeven"] = p["pnl_r"] >= 1.0

            if p["stop_level"] and p["current_price"]:
                atr = indicators.get(sym, {}).get("atr_14", 0)
                if atr > 0 and (p["current_price"] - p["stop_level"]) <= 0.5 * atr:
                    p["action_required"] = "Near stop — review"
                elif p["target_level"] and abs(p["current_price"] - p["target_level"]) / p["target_level"] < 0.01:
                    p["action_required"] = "Near target — consider exit"
                else:
                    p["action_required"] = "None — let it run"

    return positions


def build_watchlist_entries(indicators: dict, regime: dict) -> list:
    entries = []
    for symbol in WATCHLIST:
        if symbol == "SPY":
            continue  # SPY is regime barometer, not a trade candidate at this scale
        ind = indicators.get(symbol, {})
        if "error" in ind:
            continue

        entry = {
            "symbol": symbol,
            "price": ind.get("price"),
            "daily_change_pct": ind.get("daily_change_pct"),
            "volume_ratio": ind.get("volume_ratio"),
            "ema20": ind.get("ema20"),
            "ema50": ind.get("ema50"),
            "ema200": ind.get("ema200"),
            "rsi_14": ind.get("rsi_14"),
            "macd_histogram": ind.get("macd_histogram"),
            "atr_14": ind.get("atr_14"),
            "setup_flags": ind.get("setup_flags", {}),
            "earnings_within_5d": ind.get("earnings_within_5d", False),
            "earnings_date": ind.get("earnings_date"),
            "news_flag": None,  # populated by agent web search
        }
        entries.append(entry)
    return entries


def main():
    today = date.today()
    # Skip weekends
    if today.weekday() >= 5:
        print("Weekend — no market session")
        return

    indicators = load_indicators()
    spy = indicators.get("SPY", {})
    vix = float(indicators.get("_vix", 20.0))

    regime = classify_regime(spy, vix)
    logging.info("Regime: %s", regime["classification"])

    alpaca = get_alpaca_state()
    stops = load_position_stops()
    enriched_positions = enrich_positions(alpaca["positions"], stops, indicators)

    risk_summary = get_state_summary(alpaca["account_value"])

    watchlist_entries = build_watchlist_entries(indicators, regime)

    session_id = datetime.utcnow().strftime("%Y%m%d-AM")

    context = {
        "date": today.isoformat(),
        "session_id": session_id,

        "market_regime": {
            "classification": regime["classification"],
            "reason": regime["reason"],
            "spy_price": spy.get("price"),
            "spy_ema20": spy.get("ema20"),
            "spy_ema50": spy.get("ema50"),
            "spy_ema200": spy.get("ema200"),
            "spy_rsi_14": spy.get("rsi_14"),
            "spy_daily_change_pct": spy.get("daily_change_pct"),
            "spy_pct_from_52wk_high": round(
                (spy.get("price", 0) - spy.get("high_52wk", spy.get("price", 1))) /
                spy.get("high_52wk", spy.get("price", 1)) * 100, 2
            ) if spy.get("high_52wk") else None,
            "vix": vix,
            "setups_active": regime["setups_active"],
        },

        "account_state": {
            "paper_account_value": alpaca["account_value"],
            "cash_available": alpaca["cash_available"],
            "open_positions": alpaca["open_positions"],
            "max_positions_allowed": 3,
            "consecutive_losses": risk_summary["consecutive_losses"],
            "daily_pnl_dollars": risk_summary["daily_pnl_dollars"],
            "daily_pnl_pct": risk_summary["daily_pnl_pct"],
            "drawdown_from_peak_pct": risk_summary["drawdown_from_peak_pct"],
            "trading_halted": risk_summary["trading_halted"],
        },

        "watchlist": watchlist_entries,
        "open_positions": enriched_positions,
        "economic_calendar": ECONOMIC_EVENTS,

        "_generated_at": datetime.utcnow().isoformat() + "Z",
        "_data_freshness": indicators.get("_fetched_at", "unknown"),
    }

    out_path = Path("data/morning_context.json")
    with open(out_path, "w") as f:
        json.dump(context, f, indent=2)

    logging.info("morning_context.json written for session %s", session_id)
    print(f"Morning context ready: {out_path}")
    print(f"Regime: {regime['classification']} — setups active: {regime['setups_active']}")
    print(f"Account: ${alpaca['account_value']:.2f} | Open positions: {alpaca['open_positions']}/3")
    if risk_summary["trading_halted"]:
        print(f"⚠ TRADING HALTED until {risk_summary['halt_until']}")


if __name__ == "__main__":
    main()
