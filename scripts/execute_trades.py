"""
Auto-execution: reads trading_proposal.json, validates through risk gate,
places market order + stop-loss bracket via Alpaca, and records position state.

Called at end of morning session after agent writes proposal.
Only runs on paper account unless ALLOW_LIVE_EXECUTION=true in .env.
"""

import json
import logging
import os
import sys
from datetime import datetime, date
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

sys.path.insert(0, str(Path(__file__).parent))
from risk_gate import check_all, record_trade_open, RiskGateBlock, get_state_summary

logging.basicConfig(
    filename="logs/execute_trades.log",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

# Safety: never allow live execution unless explicitly set
ALLOW_LIVE = os.getenv("ALLOW_LIVE_EXECUTION", "false").lower() == "true"
BASE_URL = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

if "paper" not in BASE_URL and not ALLOW_LIVE:
    print("🚨 BLOCKED: ALPACA_BASE_URL points to live account but ALLOW_LIVE_EXECUTION is not set.")
    print("   Set ALLOW_LIVE_EXECUTION=true in .env to enable live trading.")
    sys.exit(1)


def get_alpaca_client():
    from alpaca.trading.client import TradingClient
    return TradingClient(
        os.getenv("ALPACA_API_KEY"),
        os.getenv("ALPACA_SECRET_KEY"),
        paper="paper" in BASE_URL,
    )


def get_current_price(client, symbol: str) -> float:
    """Get latest ask price from Alpaca."""
    try:
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.requests import StockLatestQuoteRequest
        data_client = StockHistoricalDataClient(
            os.getenv("ALPACA_API_KEY"),
            os.getenv("ALPACA_SECRET_KEY"),
        )
        req = StockLatestQuoteRequest(symbol_or_symbols=symbol)
        quote = data_client.get_stock_latest_quote(req)
        return float(quote[symbol].ask_price) or float(quote[symbol].bid_price)
    except Exception as e:
        logging.warning("Could not get live quote for %s: %s — using proposal entry price", symbol, e)
        return None


def place_bracket_order(client, symbol: str, shares: float, entry_price: float,
                        stop_price: float, target_price: float) -> dict:
    """
    Place a market buy order with attached stop-loss and take-profit legs.
    Alpaca bracket orders handle stop and target automatically.
    """
    from alpaca.trading.requests import MarketOrderRequest, TakeProfitRequest, StopLossRequest
    from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass

    # Round shares to 4 decimal places (Alpaca fractional minimum)
    shares = round(shares, 4)
    if shares <= 0:
        raise ValueError(f"Invalid share quantity: {shares}")

    order_req = MarketOrderRequest(
        symbol=symbol,
        qty=shares,
        side=OrderSide.BUY,
        time_in_force=TimeInForce.DAY,
        order_class=OrderClass.BRACKET,
        take_profit=TakeProfitRequest(limit_price=round(target_price, 2)),
        stop_loss=StopLossRequest(stop_price=round(stop_price, 2)),
    )

    order = client.submit_order(order_req)
    logging.info(
        "ORDER PLACED: %s %s shares @ market, stop=%.2f target=%.2f order_id=%s",
        symbol, shares, stop_price, target_price, order.id,
    )
    return {
        "order_id": str(order.id),
        "symbol": symbol,
        "qty": shares,
        "stop_price": stop_price,
        "target_price": target_price,
        "status": str(order.status),
        "submitted_at": datetime.utcnow().isoformat() + "Z",
    }


def record_position(symbol: str, entry_price: float, stop_price: float,
                    target_price: float, shares: float, setup_type: str,
                    order_id: str):
    """Persist stop/target so midday/EOD scripts can track it."""
    state_path = Path("data/positions_state.json")
    state = {}
    if state_path.exists():
        with open(state_path) as f:
            state = json.load(f)

    state[symbol] = {
        "symbol": symbol,
        "entry_price": entry_price,
        "stop_level": stop_price,
        "target_level": target_price,
        "shares": shares,
        "setup_type": setup_type,
        "entry_date": date.today().isoformat(),
        "days_held": 0,
        "order_id": order_id,
    }

    with open(state_path, "w") as f:
        json.dump(state, f, indent=2)


def main():
    proposal_path = Path("data/trading_proposal.json")
    if not proposal_path.exists():
        print("No trading_proposal.json found — nothing to execute.")
        return

    with open(proposal_path) as f:
        proposal = json.load(f)

    # No-trade session
    if proposal.get("no_trade_reason") or not proposal.get("proposals"):
        reason = proposal.get("no_trade_reason", "No candidates passed filters")
        print(f"No trade session: {reason}")
        logging.info("No-trade session: %s", reason)
        return

    client = get_alpaca_client()
    account = client.get_account()
    account_value = float(account.portfolio_value)
    open_positions = client.get_all_positions()
    open_count = len(open_positions)

    risk_summary = get_state_summary(account_value)

    if risk_summary["trading_halted"]:
        print(f"🚨 TRADING HALTED — {risk_summary['halt_until']}")
        return

    executed = []
    skipped = []

    for p in proposal["proposals"]:
        symbol = p["symbol"]
        setup_type = p.get("setup_type", "")
        proposed_entry = float(p["entry_price"])
        stop_price = float(p["stop_price"])
        target_price = float(p["target_price"])

        # Get live price — use it for sizing if available
        live_price = get_current_price(client, symbol)
        entry_price = live_price if live_price else proposed_entry

        # Adjust stop/target proportionally if live price differs from proposal
        if live_price and abs(live_price - proposed_entry) / proposed_entry > 0.005:
            shift = live_price - proposed_entry
            stop_price = round(stop_price + shift, 2)
            target_price = round(target_price + shift, 2)
            logging.info(
                "%s price shifted %.2f→%.2f, adjusted stop=%.2f target=%.2f",
                symbol, proposed_entry, live_price, stop_price, target_price,
            )

        # Run risk gate
        try:
            sizing = check_all(
                account_value=account_value,
                entry_price=entry_price,
                stop_price=stop_price,
                open_position_count=open_count,
            )
        except RiskGateBlock as e:
            reason = str(e)
            print(f"  ✗ {symbol} blocked by risk gate: {reason}")
            logging.warning("GATE_BLOCK %s: %s", symbol, reason)
            skipped.append({"symbol": symbol, "reason": reason})
            continue

        shares = sizing["shares"]

        print(f"  → Placing order: {symbol} {shares} shares @ ~${entry_price:.2f} "
              f"| stop ${stop_price:.2f} | target ${target_price:.2f} "
              f"| risk ${sizing['dollar_risk']:.2f}")

        try:
            result = place_bracket_order(
                client, symbol, shares, entry_price, stop_price, target_price
            )
            record_trade_open(account_value)
            record_position(symbol, entry_price, stop_price, target_price,
                            shares, setup_type, result["order_id"])
            executed.append(result)
            open_count += 1
            print(f"  ✓ {symbol} order submitted — ID: {result['order_id']}")
        except Exception as e:
            print(f"  ✗ {symbol} order failed: {e}")
            logging.error("ORDER_FAILED %s: %s", symbol, e)
            skipped.append({"symbol": symbol, "reason": str(e)})

    # Write execution log
    log = {
        "date": date.today().isoformat(),
        "executed": executed,
        "skipped": skipped,
        "account_value_at_execution": account_value,
    }
    with open("data/execution_log.json", "w") as f:
        json.dump(log, f, indent=2)

    print(f"\nExecution complete: {len(executed)} orders placed, {len(skipped)} skipped.")
    if executed:
        print("Bracket orders include stop-loss and take-profit — Alpaca will manage exits automatically.")


if __name__ == "__main__":
    main()
