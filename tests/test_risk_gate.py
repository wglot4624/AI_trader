"""
Unit tests for risk_gate.py.
Run: python -m pytest tests/test_risk_gate.py -v
"""

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

# Point state file to a temp dir so tests don't pollute real state
_tmp_dir = tempfile.mkdtemp()
os.environ.setdefault("ALPACA_API_KEY", "test")
os.environ.setdefault("ALPACA_SECRET_KEY", "test")

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))


def _fresh_gate(tmp_path):
    """Return risk_gate module with state file isolated to tmp_path."""
    import importlib
    import risk_gate as rg
    rg.STATE_PATH = tmp_path / "risk_state.json"
    return rg


# ── calculate_position_size ───────────────────────────────────────────────────

def test_position_size_normal(tmp_path):
    rg = _fresh_gate(tmp_path)
    result = rg.calculate_position_size(
        account_value=500.0,
        entry_price=45.0,
        stop_price=43.50,
    )
    assert result["dollar_risk"] == pytest.approx(7.50, abs=0.01)
    assert result["shares"] == pytest.approx(5.0, abs=0.01)
    assert result["position_value"] == pytest.approx(225.0, abs=0.01)
    assert result["position_pct_of_account"] == pytest.approx(0.45, abs=0.01)
    assert result["capped_at_50pct"] is False


def test_position_size_capped_at_50pct(tmp_path):
    rg = _fresh_gate(tmp_path)
    # Very tight stop → many shares → cap triggers
    result = rg.calculate_position_size(
        account_value=100.0,
        entry_price=50.0,
        stop_price=49.90,  # only $0.10 stop → 15 shares uncapped → $750 = 750% of account
    )
    assert result["capped_at_50pct"] is True
    assert result["position_pct_of_account"] <= 0.50


def test_position_size_invalid_stop(tmp_path):
    rg = _fresh_gate(tmp_path)
    with pytest.raises(ValueError):
        rg.calculate_position_size(500.0, entry_price=40.0, stop_price=42.0)


def test_position_size_stop_equal_entry(tmp_path):
    rg = _fresh_gate(tmp_path)
    with pytest.raises(ValueError):
        rg.calculate_position_size(500.0, entry_price=40.0, stop_price=40.0)


# ── check_all: normal pass ────────────────────────────────────────────────────

def test_gate_passes_normal(tmp_path):
    rg = _fresh_gate(tmp_path)
    result = rg.check_all(
        account_value=500.0,
        entry_price=45.0,
        stop_price=43.50,
        open_position_count=0,
    )
    assert result["shares"] > 0
    assert result["within_limits"] if "within_limits" in result else True


# ── Max positions ─────────────────────────────────────────────────────────────

def test_gate_blocks_at_max_positions(tmp_path):
    rg = _fresh_gate(tmp_path)
    with pytest.raises(rg.RiskGateBlock, match="MAX_POSITIONS"):
        rg.check_all(500.0, 45.0, 43.50, open_position_count=3)


def test_gate_allows_at_two_positions(tmp_path):
    rg = _fresh_gate(tmp_path)
    result = rg.check_all(500.0, 45.0, 43.50, open_position_count=2)
    assert result["shares"] > 0


# ── Daily loss halt ───────────────────────────────────────────────────────────

def test_gate_blocks_on_daily_loss_halt(tmp_path):
    rg = _fresh_gate(tmp_path)
    # Simulate a bad day: -3.1% P&L
    rg.record_trade_close(pnl_dollars=-15.60, account_value=500.0)  # -3.1%
    # Manually set daily P&L to exceed threshold
    state = json.loads((tmp_path / "risk_state.json").read_text())
    state["daily_pnl_dollars"] = -16.0  # exceeds 3% of 500
    (tmp_path / "risk_state.json").write_text(json.dumps(state))

    with pytest.raises(rg.RiskGateBlock, match="DAILY_LOSS_LIMIT"):
        rg.check_all(500.0, 45.0, 43.50, open_position_count=0)


# ── Drawdown circuit breaker ──────────────────────────────────────────────────

def test_gate_blocks_on_drawdown(tmp_path):
    rg = _fresh_gate(tmp_path)
    # Set peak to $600, current account to $500 = 16.7% drawdown > 15%
    state = {
        "peak_account_value": 600.0,
        "daily_pnl_dollars": 0.0,
        "daily_reset_date": "2099-01-01",
        "consecutive_losses": 0,
        "halt_until": None,
        "trades_this_week": 0,
        "week_reset_date": "2099-01-01",
    }
    (tmp_path / "risk_state.json").write_text(json.dumps(state))

    with pytest.raises(rg.RiskGateBlock, match="DRAWDOWN_CIRCUIT_BREAKER"):
        rg.check_all(account_value=500.0, entry_price=45.0, stop_price=43.50, open_position_count=0)


# ── Consecutive losses circuit breaker ───────────────────────────────────────

def test_three_consecutive_losses_trigger_halt(tmp_path):
    rg = _fresh_gate(tmp_path)
    # Initialize peak
    state = rg._load_state()
    state["peak_account_value"] = 500.0
    state["daily_reset_date"] = "2099-01-01"
    state["week_reset_date"] = "2099-01-01"
    rg._save_state(state)

    rg.record_trade_close(pnl_dollars=-5.0, account_value=495.0)
    rg.record_trade_close(pnl_dollars=-5.0, account_value=490.0)
    rg.record_trade_close(pnl_dollars=-5.0, account_value=485.0)

    state = rg._load_state()
    assert state["halt_until"] is not None
    assert state["consecutive_losses"] == 3


def test_halt_blocks_new_trades(tmp_path):
    rg = _fresh_gate(tmp_path)
    state = rg._load_state()
    state["peak_account_value"] = 500.0
    state["daily_reset_date"] = "2099-01-01"
    state["week_reset_date"] = "2099-01-01"
    # Set halt in future
    from datetime import datetime, timedelta
    state["halt_until"] = (datetime.utcnow() + timedelta(hours=24)).isoformat()
    rg._save_state(state)

    with pytest.raises(rg.RiskGateBlock, match="TRADING_HALTED"):
        rg.check_all(500.0, 45.0, 43.50, open_position_count=0)


def test_win_resets_consecutive_losses(tmp_path):
    rg = _fresh_gate(tmp_path)
    state = rg._load_state()
    state["peak_account_value"] = 500.0
    state["consecutive_losses"] = 2
    state["daily_reset_date"] = "2099-01-01"
    state["week_reset_date"] = "2099-01-01"
    rg._save_state(state)

    rg.record_trade_close(pnl_dollars=10.0, account_value=510.0)

    state = rg._load_state()
    assert state["consecutive_losses"] == 0


# ── Weekly trade limit ────────────────────────────────────────────────────────

def test_gate_blocks_at_weekly_limit(tmp_path):
    rg = _fresh_gate(tmp_path)
    from datetime import date, timedelta
    today = date.today()
    week_start = (today - timedelta(days=today.weekday())).isoformat()
    state = rg._load_state()
    state["peak_account_value"] = 500.0
    state["trades_this_week"] = 5
    state["daily_reset_date"] = today.isoformat()
    state["week_reset_date"] = week_start
    rg._save_state(state)

    with pytest.raises(rg.RiskGateBlock, match="WEEKLY_TRADE_LIMIT"):
        rg.check_all(500.0, 45.0, 43.50, open_position_count=0)


# ── Manual reset ──────────────────────────────────────────────────────────────

def test_manual_reset_clears_halt(tmp_path):
    rg = _fresh_gate(tmp_path)
    from datetime import datetime, timedelta
    state = rg._load_state()
    state["halt_until"] = (datetime.utcnow() + timedelta(hours=24)).isoformat()
    state["consecutive_losses"] = 3
    state["peak_account_value"] = 500.0
    state["daily_reset_date"] = "2099-01-01"
    state["week_reset_date"] = "2099-01-01"
    rg._save_state(state)

    rg.manual_reset_halt()

    state = rg._load_state()
    assert state["halt_until"] is None
    assert state["consecutive_losses"] == 0
