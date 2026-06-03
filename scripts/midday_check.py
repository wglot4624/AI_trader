"""
Midday position check — runs at 12:00 PM ET.
Flags positions within 0.5 ATR of their stop.
"""

import json
import logging
import os
import sys
from datetime import datetime, date
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

logging.basicConfig(
    filename="logs/midday_check.log",
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
    """Fetch current prices from Alpaca for open positions."""
    api_key = os.getenv("ALPACA_API_KEY")
    secret_key = os.getenv("ALPACA_SECRET_KEY")
    base_url = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

    try:
        from alpaca.trading.client import TradingClient
        client = TradingClient(api_key, secret_key, paper=True)
        positions = client.get_all_positions()
        return {p.symbol: float(p.current_price) for p in positions}
    except Exception as e:
        logging.error("Could not fetch live prices: %s", e)
        return {}


def main():
    if date.today().weekday() >= 5:
        return

    context = load_json("data/morning_context.json")
    stops_data = load_json("data/positions_state.json")
    indicators = load_json("data/indicators_cache.json")

    current_prices = get_current_prices()
    flags = []

    for pos in context.get("open_positions", []):
        symbol = pos["symbol"]
        stop = pos.get("stop_level")
        target = pos.get("target_level")
        atr = indicators.get(symbol, {}).get("atr_14", 0)

        live_price = current_prices.get(symbol, pos.get("current_price", 0))

        if not stop or not live_price:
            continue

        distance_to_stop = live_price - stop

        flag = {
            "symbol": symbol,
            "live_price": round(live_price, 2),
            "stop_level": stop,
            "target_level": target,
            "distance_to_stop": round(distance_to_stop, 2),
            "atr_14": atr,
            "alert": None,
        }

        if atr > 0 and distance_to_stop <= 0.5 * atr:
            flag["alert"] = f"NEAR STOP — within 0.5 ATR ({atr:.2f})"
            logging.warning("%s near stop: price=%.2f stop=%.2f distance=%.2f", symbol, live_price, stop, distance_to_stop)

        if live_price <= stop:
            flag["alert"] = "STOP HIT — exit immediately"
            logging.warning("%s stop HIT: price=%.2f stop=%.2f", symbol, live_price, stop)

        if target and live_price >= target:
            flag["alert"] = "TARGET REACHED — consider exit"
            logging.info("%s target reached: price=%.2f target=%.2f", symbol, live_price, target)

        flags.append(flag)

    report = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "session": "MIDDAY",
        "position_flags": flags,
        "action_required": any(f["alert"] for f in flags),
    }

    out_path = Path("data/midday_report.json")
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2)

    print(f"Midday check complete: {out_path}")
    for f in flags:
        if f["alert"]:
            print(f"  ⚠ {f['symbol']}: {f['alert']} (price={f['live_price']}, stop={f['stop_level']})")
        else:
            print(f"  ✓ {f['symbol']}: price={f['live_price']}, stop={f['stop_level']} — OK")


if __name__ == "__main__":
    main()
