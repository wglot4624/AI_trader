"""
Appends completed trade records to journal/trades.csv.
Call after a position is closed, passing the trade data as JSON on stdin
or by importing append_trade() directly.
"""

import csv
import json
import sys
from datetime import datetime, date
from pathlib import Path

JOURNAL_PATH = Path("journal/trades.csv")

FIELDS = [
    "trade_id", "symbol", "setup_type", "entry_date", "exit_date",
    "entry_price", "exit_price", "shares", "stop_price", "target_price",
    "exit_reason", "gross_pnl", "r_multiple", "confluence_score",
    "regime_at_entry", "agent_confidence", "human_approved",
    "agent_bull_case", "agent_bear_case", "post_trade_notes",
]


def _ensure_header():
    JOURNAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not JOURNAL_PATH.exists():
        with open(JOURNAL_PATH, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            writer.writeheader()


def append_trade(trade: dict):
    """Append a single completed trade record to the journal CSV."""
    _ensure_header()

    # Compute r_multiple if not provided
    if "r_multiple" not in trade or trade["r_multiple"] is None:
        try:
            initial_risk = (float(trade["entry_price"]) - float(trade["stop_price"])) * float(trade["shares"])
            if initial_risk > 0:
                trade["r_multiple"] = round(float(trade["gross_pnl"]) / initial_risk, 2)
        except (KeyError, TypeError, ZeroDivisionError):
            trade["r_multiple"] = None

    # Auto-generate trade_id if missing
    if not trade.get("trade_id"):
        entry_date = trade.get("entry_date", date.today().isoformat()).replace("-", "")
        seq = _next_sequence(trade.get("symbol", "UNKNOWN"))
        trade["trade_id"] = f"{entry_date}-{trade.get('symbol', 'UNKNOWN')}-{seq:03d}"

    row = {field: trade.get(field, "") for field in FIELDS}

    with open(JOURNAL_PATH, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writerow(row)

    print(f"Journal entry written: {row['trade_id']}")


def _next_sequence(symbol: str) -> int:
    if not JOURNAL_PATH.exists():
        return 1
    with open(JOURNAL_PATH) as f:
        reader = csv.DictReader(f)
        count = sum(1 for r in reader if r.get("symbol") == symbol)
    return count + 1


def print_summary():
    """Print performance summary from journal."""
    _ensure_header()
    rows = []
    with open(JOURNAL_PATH) as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        print("No trades in journal yet.")
        return

    completed = [r for r in rows if r.get("exit_date")]
    if not completed:
        print(f"{len(rows)} trades recorded, none completed yet.")
        return

    pnls = [float(r["gross_pnl"]) for r in completed if r.get("gross_pnl")]
    r_multiples = [float(r["r_multiple"]) for r in completed if r.get("r_multiple")]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    win_rate = len(wins) / len(pnls) * 100 if pnls else 0
    avg_rr = sum(r for r in r_multiples if r > 0) / max(len([r for r in r_multiples if r > 0]), 1)
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")
    net_pnl = sum(pnls)

    print(f"\n{'='*40}")
    print(f"TRADE JOURNAL SUMMARY")
    print(f"{'='*40}")
    print(f"Total trades:   {len(completed)}")
    print(f"Win rate:       {win_rate:.1f}%  (target ≥ 40%)")
    print(f"Avg R:R:        {avg_rr:.2f}  (target ≥ 2.0)")
    print(f"Profit factor:  {profit_factor:.2f}  (target > 1.5)")
    print(f"Net P&L:        ${net_pnl:.2f}")
    print(f"Gross profit:   ${gross_profit:.2f}")
    print(f"Gross loss:     ${gross_loss:.2f}")
    print(f"{'='*40}\n")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "summary":
        print_summary()
    elif not sys.stdin.isatty():
        trade_data = json.load(sys.stdin)
        append_trade(trade_data)
    else:
        print("Usage: python write_journal.py summary")
        print("       echo '{...}' | python write_journal.py")
