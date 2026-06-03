"""
Manually track stop/target levels for open positions.
Alpaca doesn't store these — we track them in data/positions_state.json.

Usage:
  python update_position.py add AAPL --entry 192.00 --stop 188.50 --target 199.00 --setup A_PULLBACK
  python update_position.py close AAPL --exit-price 199.20 --reason TARGET_HIT
  python update_position.py list
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

STATE_PATH = Path("data/positions_state.json")


def load() -> dict:
    if STATE_PATH.exists():
        with open(STATE_PATH) as f:
            return json.load(f)
    return {}


def save(state: dict):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, indent=2)


def cmd_add(args):
    state = load()
    state[args.symbol] = {
        "symbol": args.symbol,
        "entry_price": args.entry,
        "stop_level": args.stop,
        "target_level": args.target,
        "setup_type": args.setup,
        "entry_date": date.today().isoformat(),
        "days_held": 0,
    }
    save(state)
    print(f"Added {args.symbol}: entry={args.entry}, stop={args.stop}, target={args.target}")


def cmd_close(args):
    state = load()
    if args.symbol not in state:
        print(f"{args.symbol} not found in open positions")
        sys.exit(1)

    pos = state.pop(args.symbol)
    save(state)

    # Build journal entry template
    from write_journal import append_trade
    entry = pos.get("entry_price", 0)
    shares = args.shares or 0
    pnl = round((args.exit_price - entry) * shares, 2) if shares else None

    trade = {
        "symbol": args.symbol,
        "setup_type": pos.get("setup_type"),
        "entry_date": pos.get("entry_date"),
        "exit_date": date.today().isoformat(),
        "entry_price": entry,
        "exit_price": args.exit_price,
        "shares": shares,
        "stop_price": pos.get("stop_level"),
        "target_price": pos.get("target_level"),
        "exit_reason": args.reason,
        "gross_pnl": pnl,
        "human_approved": True,
    }
    append_trade(trade)
    print(f"Closed {args.symbol} at {args.exit_price}. Journal entry written.")


def cmd_list(args):
    state = load()
    if not state:
        print("No open positions tracked.")
        return
    for sym, pos in state.items():
        print(f"  {sym}: entry={pos['entry_price']}, stop={pos['stop_level']}, "
              f"target={pos['target_level']}, held since {pos['entry_date']}")


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd")

    p_add = sub.add_parser("add")
    p_add.add_argument("symbol")
    p_add.add_argument("--entry", type=float, required=True)
    p_add.add_argument("--stop", type=float, required=True)
    p_add.add_argument("--target", type=float, required=True)
    p_add.add_argument("--setup", default="")

    p_close = sub.add_parser("close")
    p_close.add_argument("symbol")
    p_close.add_argument("--exit-price", type=float, required=True)
    p_close.add_argument("--reason", default="MANUAL_EXIT",
                         choices=["TARGET_HIT", "STOP_HIT", "MANUAL_EXIT", "REGIME_CHANGE"])
    p_close.add_argument("--shares", type=float, default=0)

    sub.add_parser("list")

    args = parser.parse_args()
    if args.cmd == "add":
        cmd_add(args)
    elif args.cmd == "close":
        cmd_close(args)
    elif args.cmd == "list":
        cmd_list(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
