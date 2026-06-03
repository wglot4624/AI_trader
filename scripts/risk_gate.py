"""
Risk gate — all hard limits live here in code, not in prompts.
Import this module to check any proposed trade before submission.
State persists in data/risk_state.json.
"""

import json
import logging
import os
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional

logging.basicConfig(
    filename="logs/risk_gate.log",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

STATE_PATH = Path("data/risk_state.json")

RISK_PCT = 0.015          # 1.5% per trade
MAX_POSITIONS = 3
MAX_DAILY_LOSS_PCT = 0.03  # 3%
MAX_DRAWDOWN_PCT = 0.15    # 15%
MAX_POSITION_PCT = 0.50    # 50% of account in one name
MAX_TRADES_PER_WEEK = 5
CONSECUTIVE_LOSS_PAUSE_HOURS = 48


def _load_state() -> dict:
    if STATE_PATH.exists():
        with open(STATE_PATH) as f:
            return json.load(f)
    return {
        "peak_account_value": None,
        "daily_pnl_dollars": 0.0,
        "daily_reset_date": None,
        "consecutive_losses": 0,
        "halt_until": None,
        "trades_this_week": 0,
        "week_reset_date": None,
        "completed_trades": [],
    }


def _save_state(state: dict):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, indent=2)


def _reset_daily_if_needed(state: dict) -> dict:
    today_str = date.today().isoformat()
    if state.get("daily_reset_date") != today_str:
        state["daily_pnl_dollars"] = 0.0
        state["daily_reset_date"] = today_str
    return state


def _reset_weekly_if_needed(state: dict) -> dict:
    today = date.today()
    week_start = (today - timedelta(days=today.weekday())).isoformat()
    if state.get("week_reset_date") != week_start:
        state["trades_this_week"] = 0
        state["week_reset_date"] = week_start
    return state


# ── Core calculation ──────────────────────────────────────────────────────────

def calculate_position_size(
    account_value: float,
    entry_price: float,
    stop_price: float,
) -> dict:
    """
    Returns position sizing details.
    Raises ValueError if stop_price >= entry_price.
    """
    if stop_price >= entry_price:
        raise ValueError(f"Stop price ({stop_price}) must be below entry price ({entry_price})")

    dollar_risk = account_value * RISK_PCT
    stop_distance = entry_price - stop_price
    shares = dollar_risk / stop_distance

    # Apply 50% cap
    max_shares_by_cap = (account_value * MAX_POSITION_PCT) / entry_price
    capped = shares > max_shares_by_cap
    shares = min(shares, max_shares_by_cap)
    shares = round(shares, 4)

    position_value = shares * entry_price
    position_pct = position_value / account_value

    return {
        "account_value": round(account_value, 2),
        "risk_pct": RISK_PCT,
        "dollar_risk": round(dollar_risk, 2),
        "entry_price": round(entry_price, 2),
        "stop_price": round(stop_price, 2),
        "stop_distance": round(stop_distance, 2),
        "shares": shares,
        "position_value": round(position_value, 2),
        "position_pct_of_account": round(position_pct, 3),
        "capped_at_50pct": capped,
    }


# ── Gate checks ───────────────────────────────────────────────────────────────

class RiskGateBlock(Exception):
    pass


def check_all(
    account_value: float,
    entry_price: float,
    stop_price: float,
    open_position_count: int,
) -> dict:
    """
    Run all hard-limit checks for a proposed new trade.
    Returns sizing dict if all checks pass.
    Raises RiskGateBlock with reason if any check fails.
    """
    state = _load_state()
    state = _reset_daily_if_needed(state)
    state = _reset_weekly_if_needed(state)

    # ── 1. Halt flag ──────────────────────────────────────────────────────────
    if state.get("halt_until"):
        halt_until = datetime.fromisoformat(state["halt_until"])
        if datetime.utcnow() < halt_until:
            raise RiskGateBlock(
                f"TRADING_HALTED until {halt_until.isoformat()} "
                f"(three consecutive losses circuit breaker)"
            )
        else:
            state["halt_until"] = None
            state["consecutive_losses"] = 0
            logging.info("Halt period expired, resuming trading")

    # ── 2. Max open positions ─────────────────────────────────────────────────
    if open_position_count >= MAX_POSITIONS:
        raise RiskGateBlock(
            f"MAX_POSITIONS exceeded: {open_position_count}/{MAX_POSITIONS} open"
        )

    # ── 3. Daily loss halt ────────────────────────────────────────────────────
    daily_loss_threshold = account_value * MAX_DAILY_LOSS_PCT
    if state["daily_pnl_dollars"] <= -daily_loss_threshold:
        raise RiskGateBlock(
            f"DAILY_LOSS_LIMIT: daily P&L is ${state['daily_pnl_dollars']:.2f}, "
            f"threshold is -${daily_loss_threshold:.2f}"
        )

    # ── 4. Drawdown circuit breaker ───────────────────────────────────────────
    peak = state.get("peak_account_value")
    if peak and account_value <= peak * (1 - MAX_DRAWDOWN_PCT):
        raise RiskGateBlock(
            f"DRAWDOWN_CIRCUIT_BREAKER: account ${account_value:.2f} is "
            f"{((peak - account_value) / peak * 100):.1f}% below peak ${peak:.2f}"
        )

    # ── 5. Weekly trade count ─────────────────────────────────────────────────
    if state["trades_this_week"] >= MAX_TRADES_PER_WEEK:
        raise RiskGateBlock(
            f"WEEKLY_TRADE_LIMIT: {state['trades_this_week']}/{MAX_TRADES_PER_WEEK} "
            f"trades completed this week"
        )

    # ── 6. Position sizing ────────────────────────────────────────────────────
    sizing = calculate_position_size(account_value, entry_price, stop_price)

    dollar_risk = sizing["dollar_risk"]
    max_allowed_risk = account_value * RISK_PCT
    if dollar_risk > max_allowed_risk * 1.01:  # 1% tolerance for float rounding
        raise RiskGateBlock(
            f"RISK_PCT_EXCEEDED: dollar risk ${dollar_risk:.2f} > ${max_allowed_risk:.2f}"
        )

    _save_state(state)
    logging.info(
        "GATE_PASS: entry=%.2f stop=%.2f shares=%.4f position_pct=%.1f%%",
        entry_price, stop_price, sizing["shares"], sizing["position_pct_of_account"] * 100,
    )
    return sizing


# ── State update functions (call after trade events) ─────────────────────────

def record_trade_open(account_value: float):
    """Call when a new trade is opened."""
    state = _load_state()
    state = _reset_daily_if_needed(state)
    state = _reset_weekly_if_needed(state)

    if state.get("peak_account_value") is None or account_value > state["peak_account_value"]:
        state["peak_account_value"] = account_value

    _save_state(state)
    logging.info("Trade opened. Account: $%.2f", account_value)


def record_trade_close(pnl_dollars: float, account_value: float):
    """Call when a trade is closed. Updates daily P&L, consecutive losses, weekly count."""
    state = _load_state()
    state = _reset_daily_if_needed(state)
    state = _reset_weekly_if_needed(state)

    state["daily_pnl_dollars"] += pnl_dollars
    state["trades_this_week"] += 1

    if pnl_dollars < 0:
        state["consecutive_losses"] += 1
        logging.info("Loss recorded. Consecutive losses: %d", state["consecutive_losses"])
        if state["consecutive_losses"] >= 3:
            halt_until = (datetime.utcnow() + timedelta(hours=CONSECUTIVE_LOSS_PAUSE_HOURS)).isoformat()
            state["halt_until"] = halt_until
            logging.warning(
                "THREE_CONSECUTIVE_LOSSES: trading halted until %s", halt_until
            )
            print(f"⚠ THREE CONSECUTIVE LOSSES — trading halted until {halt_until}")
    else:
        state["consecutive_losses"] = 0

    # Update peak
    if account_value > (state.get("peak_account_value") or 0):
        state["peak_account_value"] = account_value

    _save_state(state)


def record_daily_pnl(pnl_dollars: float, account_value: float):
    """Update daily P&L without closing a trade (e.g., mark-to-market)."""
    state = _load_state()
    state = _reset_daily_if_needed(state)
    state["daily_pnl_dollars"] = pnl_dollars

    if account_value > (state.get("peak_account_value") or 0):
        state["peak_account_value"] = account_value

    # Check drawdown
    peak = state.get("peak_account_value")
    if peak and account_value <= peak * (1 - MAX_DRAWDOWN_PCT):
        state["halt_until"] = "9999-12-31T00:00:00"  # manual reset required
        logging.critical(
            "DRAWDOWN_CIRCUIT_BREAKER TRIGGERED: account $%.2f, peak $%.2f",
            account_value, peak,
        )
        print(f"🚨 DRAWDOWN CIRCUIT BREAKER: account ${account_value:.2f} — MANUAL RESET REQUIRED")

    _save_state(state)


def get_state_summary(account_value: float) -> dict:
    state = _load_state()
    state = _reset_daily_if_needed(state)
    state = _reset_weekly_if_needed(state)

    peak = state.get("peak_account_value") or account_value
    drawdown_pct = (peak - account_value) / peak if peak > 0 else 0.0

    halt_active = False
    if state.get("halt_until"):
        halt_until = datetime.fromisoformat(state["halt_until"])
        halt_active = datetime.utcnow() < halt_until

    daily_loss_pct = state["daily_pnl_dollars"] / account_value if account_value > 0 else 0

    return {
        "trading_halted": halt_active,
        "halt_until": state.get("halt_until"),
        "consecutive_losses": state.get("consecutive_losses", 0),
        "daily_pnl_dollars": round(state["daily_pnl_dollars"], 2),
        "daily_pnl_pct": round(daily_loss_pct * 100, 2),
        "drawdown_from_peak_pct": round(drawdown_pct * 100, 2),
        "peak_account_value": round(peak, 2),
        "trades_this_week": state.get("trades_this_week", 0),
    }


def manual_reset_halt():
    """Manual override to clear a circuit breaker halt."""
    state = _load_state()
    state["halt_until"] = None
    state["consecutive_losses"] = 0
    _save_state(state)
    logging.warning("MANUAL_HALT_RESET: operator cleared halt")
    print("Halt cleared. Trading can resume.")
