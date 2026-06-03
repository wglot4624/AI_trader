"""
End-of-day check — runs at 3:45 PM ET.
Recommends hold or exit for each open position.
"""

import json
import logging
import os
from datetime import datetime, date
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

logging.basicConfig(
    filename="logs/eod_check.log",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)


def load_json(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    with open(p) as f:
        return json.load(f)


def get_current_prices() -> dict:
    api_key = os.getenv("ALPACA_API_KEY")
    secret_key = os.getenv("ALPACA_SECRET_KEY")

    try:
        from alpaca.trading.client import TradingClient
        client = TradingClient(api_key, secret_key, paper=True)
        positions = client.get_all_positions()
        return {p.symbol: float(p.current_price) for p in positions}
    except Exception as e:
        logging.error("Could not fetch live prices: %s", e)
        return {}


def recommend_action(pos: dict, live_price: float, atr: float) -> str:
    stop = pos.get("stop_level")
    target = pos.get("target_level")
    pnl_r = pos.get("pnl_r", 0) or 0

    if stop and live_price <= stop:
        return "EXIT — stop hit"

    if target and live_price >= target:
        return "EXIT — target reached"

    if stop and atr > 0:
        distance = live_price - stop
        if distance <= 0.3 * atr:
            return "REVIEW — dangerously close to stop, consider protective exit"

    # Trail stop to breakeven if 1R in profit
    if pnl_r >= 1.0 and not pos.get("stop_at_breakeven"):
        return f"TRAIL STOP to breakeven ({pos.get('entry_price')}) — position at {pnl_r:.2f}R"

    return "HOLD — let it run"


def main():
    if date.today().weekday() >= 5:
        return

    context = load_json("data/morning_context.json")
    indicators = load_json("data/indicators_cache.json")
    current_prices = get_current_prices()

    recommendations = []

    for pos in context.get("open_positions", []):
        symbol = pos["symbol"]
        atr = indicators.get(symbol, {}).get("atr_14", 0)
        live_price = current_prices.get(symbol, pos.get("current_price", 0))

        # Update pnl_r with latest price
        entry = pos.get("entry_price", 0)
        stop = pos.get("stop_level")
        if entry and stop and live_price:
            initial_risk = entry - stop
            if initial_risk > 0:
                pos["pnl_r"] = round((live_price - entry) / initial_risk, 2)

        action = recommend_action(pos, live_price, atr)

        rec = {
            "symbol": symbol,
            "live_price": round(live_price, 2),
            "entry_price": pos.get("entry_price"),
            "stop_level": pos.get("stop_level"),
            "target_level": pos.get("target_level"),
            "pnl_r": pos.get("pnl_r"),
            "days_held": pos.get("days_held"),
            "action": action,
        }
        recommendations.append(rec)
        logging.info("EOD %s: price=%.2f action=%s", symbol, live_price, action)

    report = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "session": "EOD",
        "recommendations": recommendations,
        "exits_required": [r for r in recommendations if r["action"].startswith("EXIT")],
    }

    out_path = Path("data/eod_report.json")
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2)

    print(f"EOD check complete: {out_path}")
    for r in recommendations:
        icon = "🔴" if r["action"].startswith("EXIT") else "🟡" if "REVIEW" in r["action"] else "🟢"
        print(f"  {icon} {r['symbol']}: {r['action']} (price={r['live_price']}, R={r['pnl_r']})")


if __name__ == "__main__":
    main()
