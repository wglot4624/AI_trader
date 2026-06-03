"""
Full morning pipeline: fetch indicators → generate context → print for agent.
The Cowork scheduled task runs this and feeds the output to the agent.
"""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent


def run(script: str):
    result = subprocess.run(
        [sys.executable, script],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"ERROR running {script}:\n{result.stderr}")
        sys.exit(1)
    return result.stdout.strip()


def main():
    print("=== AI Swing Trader — Morning Session ===\n")

    print("Fetching market data...")
    run("scripts/fetch_indicators.py")

    print("Generating morning context...")
    run("scripts/generate_morning_context.py")

    # Read and print the context for the agent
    ctx_path = ROOT / "data" / "morning_context.json"
    with open(ctx_path) as f:
        ctx = json.load(f)

    regime = ctx.get("market_regime", {})
    account = ctx.get("account_state", {})

    print(f"\nRegime: {regime.get('classification')} — {regime.get('reason')}")
    print(f"Setups active: {regime.get('setups_active')}")
    print(f"Account: ${account.get('paper_account_value', 0):,.2f} | "
          f"Positions: {account.get('open_positions')}/3 | "
          f"Halted: {account.get('trading_halted')}")

    if account.get("trading_halted"):
        print("\n⚠ TRADING HALTED — No proposals will be generated.")
        return

    if not regime.get("setups_active"):
        print("\n⚠ NO TRADE regime — No proposals will be generated.")
        return

    candidates = [
        w["symbol"] for w in ctx.get("watchlist", [])
        if any(w.get("setup_flags", {}).values()) and not w.get("earnings_within_5d")
    ]
    print(f"\nSetup candidates: {candidates if candidates else 'None — no flags triggered'}")

    print("\n--- MORNING CONTEXT FOR AGENT ---")
    print("Read docs/agent_prompt.txt as your system prompt, then analyze:")
    print(json.dumps(ctx, indent=2))


if __name__ == "__main__":
    main()
