"""
Trading dashboard — Flask server.
Run: .venv/bin/python dashboard/app.py
Then open http://localhost:5001
"""

import csv
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, render_template_string

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

ROOT = Path(__file__).parent.parent
app = Flask(__name__)


def load_json(filename: str) -> dict | list:
    path = ROOT / "data" / filename
    if not path.exists():
        return {}
    with open(path) as f:
        return json.load(f)


def load_journal() -> list:
    path = ROOT / "journal" / "trades.csv"
    if not path.exists():
        return []
    with open(path) as f:
        reader = csv.DictReader(f)
        return [r for r in reader if r.get("exit_date")]


def compute_stats(trades: list) -> dict:
    if not trades:
        return {
            "total_trades": 0, "win_rate": None, "avg_rr": None,
            "profit_factor": None, "net_pnl": 0,
            "gross_profit": 0, "gross_loss": 0,
        }

    pnls = []
    r_multiples = []
    for t in trades:
        try:
            pnls.append(float(t["gross_pnl"]))
        except (ValueError, KeyError):
            pass
        try:
            r_multiples.append(float(t["r_multiple"]))
        except (ValueError, KeyError):
            pass

    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))

    return {
        "total_trades": len(trades),
        "win_rate": round(len(wins) / len(pnls) * 100, 1) if pnls else None,
        "avg_rr": round(
            sum(r for r in r_multiples if r > 0) / max(len([r for r in r_multiples if r > 0]), 1), 2
        ) if r_multiples else None,
        "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss > 0 else None,
        "net_pnl": round(sum(pnls), 2),
        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2),
    }


@app.route("/api/context")
def api_context():
    return jsonify(load_json("morning_context.json"))


@app.route("/api/proposal")
def api_proposal():
    return jsonify(load_json("trading_proposal.json"))


@app.route("/api/eod")
def api_eod():
    return jsonify(load_json("eod_report.json"))


@app.route("/api/midday")
def api_midday():
    return jsonify(load_json("midday_report.json"))


@app.route("/api/stats")
def api_stats():
    trades = load_journal()
    stats = compute_stats(trades)
    stats["recent_trades"] = trades[-10:][::-1]
    return jsonify(stats)


@app.route("/api/risk")
def api_risk():
    path = ROOT / "data" / "risk_state.json"
    if not path.exists():
        return jsonify({})
    with open(path) as f:
        return jsonify(json.load(f))


@app.route("/")
def index():
    return render_template_string(DASHBOARD_HTML)


DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI Swing Trader</title>
<style>
  :root {
    --bg: #0d0f14;
    --surface: #161a23;
    --border: #232838;
    --text: #e2e8f0;
    --muted: #64748b;
    --green: #22c55e;
    --red: #ef4444;
    --yellow: #f59e0b;
    --blue: #3b82f6;
    --purple: #a855f7;
    --font-mono: 'JetBrains Mono', 'Fira Code', 'Courier New', monospace;
    --font: -apple-system, BlinkMacSystemFont, 'Inter', sans-serif;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: var(--bg); color: var(--text); font-family: var(--font); font-size: 14px; line-height: 1.5; }

  header {
    display: flex; align-items: center; justify-content: space-between;
    padding: 14px 24px; border-bottom: 1px solid var(--border);
    background: var(--surface);
  }
  header h1 { font-size: 15px; font-weight: 600; letter-spacing: 0.03em; color: var(--text); }
  header .meta { display: flex; gap: 20px; align-items: center; }
  .badge {
    font-size: 11px; font-weight: 700; letter-spacing: 0.08em; padding: 3px 10px;
    border-radius: 4px; text-transform: uppercase;
  }
  .badge-green  { background: rgba(34,197,94,.15);  color: var(--green); border: 1px solid rgba(34,197,94,.3); }
  .badge-yellow { background: rgba(245,158,11,.15); color: var(--yellow); border: 1px solid rgba(245,158,11,.3); }
  .badge-red    { background: rgba(239,68,68,.15);  color: var(--red);   border: 1px solid rgba(239,68,68,.3); }
  .badge-blue   { background: rgba(59,130,246,.15); color: var(--blue);  border: 1px solid rgba(59,130,246,.3); }
  .badge-muted  { background: rgba(100,116,139,.12); color: var(--muted); border: 1px solid rgba(100,116,139,.2); }

  #refresh-time { font-size: 11px; color: var(--muted); font-family: var(--font-mono); }

  main { padding: 20px 24px; display: grid; gap: 16px; grid-template-columns: 1fr 1fr 1fr; }

  .card {
    background: var(--surface); border: 1px solid var(--border); border-radius: 8px;
    padding: 16px;
  }
  .card-full   { grid-column: 1 / -1; }
  .card-half   { grid-column: span 2; }
  .card-third  { grid-column: span 1; }

  .card-title {
    font-size: 11px; font-weight: 600; letter-spacing: 0.1em;
    text-transform: uppercase; color: var(--muted); margin-bottom: 14px;
  }

  /* Stat row */
  .stat-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }
  .stat { background: var(--bg); border-radius: 6px; padding: 14px 16px; }
  .stat-label { font-size: 11px; color: var(--muted); margin-bottom: 4px; }
  .stat-value { font-size: 22px; font-weight: 700; font-family: var(--font-mono); }
  .stat-sub { font-size: 11px; color: var(--muted); margin-top: 2px; }
  .pos { color: var(--green); }
  .neg { color: var(--red); }
  .neu { color: var(--text); }

  /* Regime block */
  .regime-block { display: flex; align-items: center; gap: 12px; }
  .regime-label { font-size: 18px; font-weight: 700; }
  .regime-reason { font-size: 12px; color: var(--muted); margin-top: 2px; }
  .setups-active { display: flex; gap: 6px; margin-top: 10px; }

  /* SPY stats */
  .spy-grid { display: grid; grid-template-columns: repeat(3,1fr); gap: 8px; margin-top: 12px; }
  .spy-item { background: var(--bg); border-radius: 6px; padding: 10px; }
  .spy-item .label { font-size: 10px; color: var(--muted); }
  .spy-item .value { font-size: 14px; font-weight: 600; font-family: var(--font-mono); }

  /* Table */
  table { width: 100%; border-collapse: collapse; }
  th { text-align: left; font-size: 10px; font-weight: 600; letter-spacing: 0.08em;
       text-transform: uppercase; color: var(--muted); padding: 0 8px 10px; }
  td { padding: 9px 8px; border-top: 1px solid var(--border); font-family: var(--font-mono); font-size: 12px; }
  tr:hover td { background: rgba(255,255,255,.02); }
  .symbol-cell { font-weight: 700; font-size: 13px; color: var(--text); font-family: var(--font); }

  /* Confluence dots */
  .confluence { display: flex; gap: 4px; }
  .dot { width: 8px; height: 8px; border-radius: 50%; }
  .dot-green { background: var(--green); }
  .dot-red   { background: var(--red); opacity: 0.4; }

  /* Signal row for confluence */
  .signal-list { display: flex; flex-wrap: wrap; gap: 6px; }
  .signal-chip {
    font-size: 10px; padding: 2px 8px; border-radius: 3px;
    font-weight: 600; letter-spacing: 0.04em;
  }
  .signal-chip.green { background: rgba(34,197,94,.12); color: var(--green); }
  .signal-chip.red   { background: rgba(239,68,68,.12);  color: var(--red); }

  /* Position card */
  .position-row { background: var(--bg); border-radius: 6px; padding: 12px 14px; margin-bottom: 8px; }
  .position-row:last-child { margin-bottom: 0; }
  .pos-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
  .pos-symbol { font-size: 16px; font-weight: 700; }
  .pos-pnl { font-size: 14px; font-weight: 700; font-family: var(--font-mono); }
  .pos-meta { display: grid; grid-template-columns: repeat(4,1fr); gap: 8px; }
  .pos-meta-item .label { font-size: 10px; color: var(--muted); }
  .pos-meta-item .value { font-size: 12px; font-weight: 600; font-family: var(--font-mono); }

  /* Progress bar for R */
  .r-bar-wrap { margin-top: 8px; }
  .r-bar-label { font-size: 10px; color: var(--muted); margin-bottom: 4px; }
  .r-bar-track { background: var(--border); border-radius: 3px; height: 4px; overflow: hidden; }
  .r-bar-fill  { height: 100%; border-radius: 3px; transition: width 0.3s; }

  /* Proposal box */
  .proposal-card { background: var(--bg); border-radius: 6px; padding: 14px; margin-bottom: 10px; }
  .proposal-card:last-child { margin-bottom: 0; }
  .proposal-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 10px; }
  .proposal-symbol { font-size: 18px; font-weight: 700; }
  .proposal-setup { font-size: 11px; color: var(--muted); margin-top: 2px; }
  .proposal-section-title { font-size: 10px; font-weight: 600; text-transform: uppercase;
    letter-spacing: 0.08em; color: var(--muted); margin: 10px 0 5px; }
  .case-list { list-style: none; }
  .case-list li { font-size: 12px; padding: 3px 0; padding-left: 12px; position: relative; color: #94a3b8; }
  .case-list li::before { content: '–'; position: absolute; left: 0; color: var(--muted); }
  .risk-grid { display: grid; grid-template-columns: repeat(3,1fr); gap: 8px; margin-top: 8px; }
  .risk-item .label { font-size: 10px; color: var(--muted); }
  .risk-item .value { font-size: 13px; font-weight: 600; font-family: var(--font-mono); }
  .synthesis-box { font-size: 12px; color: #94a3b8; line-height: 1.6;
    background: rgba(59,130,246,.06); border-left: 2px solid var(--blue);
    padding: 8px 12px; border-radius: 0 4px 4px 0; margin-top: 10px; }

  /* Journal table */
  .exit-reason { font-size: 10px; padding: 2px 6px; border-radius: 3px; font-weight: 600; }

  /* Empty state */
  .empty { color: var(--muted); font-size: 13px; text-align: center; padding: 24px 0; }

  /* Halt banner */
  #halt-banner {
    display: none; background: rgba(239,68,68,.12); border: 1px solid rgba(239,68,68,.3);
    color: var(--red); padding: 10px 24px; font-size: 13px; font-weight: 600;
    text-align: center; letter-spacing: 0.02em;
  }

  @media (max-width: 900px) {
    main { grid-template-columns: 1fr; }
    .card-half, .card-third { grid-column: 1; }
    .stat-grid { grid-template-columns: repeat(2,1fr); }
  }
</style>
</head>
<body>

<div id="halt-banner">⚠ TRADING HALTED — Circuit breaker active. Manual reset required.</div>

<header>
  <h1>AI Swing Trader ·  Paper</h1>
  <div class="meta">
    <span id="regime-badge" class="badge badge-muted">—</span>
    <span id="account-value" style="font-family:var(--font-mono);font-weight:700;">$—</span>
    <span id="refresh-time">Refreshing…</span>
  </div>
</header>

<main>

  <!-- Performance stats -->
  <div class="card card-full">
    <div class="card-title">Performance</div>
    <div class="stat-grid" id="stats-grid">
      <div class="stat"><div class="stat-label">Net P&L</div><div class="stat-value neu" id="stat-pnl">—</div><div class="stat-sub">paper account</div></div>
      <div class="stat"><div class="stat-label">Win Rate</div><div class="stat-value neu" id="stat-winrate">—</div><div class="stat-sub">target ≥ 40%</div></div>
      <div class="stat"><div class="stat-label">Profit Factor</div><div class="stat-value neu" id="stat-pf">—</div><div class="stat-sub">target > 1.5</div></div>
      <div class="stat"><div class="stat-label">Avg R:R</div><div class="stat-value neu" id="stat-rr">—</div><div class="stat-sub">target ≥ 2.0</div></div>
    </div>
  </div>

  <!-- Market regime -->
  <div class="card card-third">
    <div class="card-title">Market Regime</div>
    <div id="regime-detail">
      <div class="regime-block">
        <div>
          <div class="regime-label" id="regime-name">—</div>
          <div class="regime-reason" id="regime-reason">—</div>
        </div>
      </div>
      <div class="setups-active" id="setups-active"></div>
      <div class="spy-grid" id="spy-grid"></div>
    </div>
  </div>

  <!-- Risk gate status -->
  <div class="card card-third">
    <div class="card-title">Risk Gate</div>
    <div id="risk-detail">
      <div class="spy-grid" id="risk-grid"></div>
    </div>
  </div>

  <!-- Account -->
  <div class="card card-third">
    <div class="card-title">Account</div>
    <div class="spy-grid" id="account-grid"></div>
  </div>

  <!-- Open positions -->
  <div class="card card-half">
    <div class="card-title">Open Positions</div>
    <div id="positions-list"><div class="empty">No open positions</div></div>
  </div>

  <!-- Today's proposal -->
  <div class="card card-third">
    <div class="card-title">Agent Proposal</div>
    <div id="proposal-list"><div class="empty">No proposal yet today</div></div>
  </div>

  <!-- Watchlist -->
  <div class="card card-full">
    <div class="card-title">Watchlist</div>
    <table>
      <thead>
        <tr>
          <th>Symbol</th><th>Price</th><th>Chg %</th>
          <th>RSI</th><th>EMA 20</th><th>EMA 50</th><th>EMA 200</th>
          <th>ATR</th><th>Vol Ratio</th><th>Setups</th>
        </tr>
      </thead>
      <tbody id="watchlist-tbody"></tbody>
    </table>
  </div>

  <!-- Recent trades -->
  <div class="card card-full">
    <div class="card-title">Recent Trades</div>
    <table>
      <thead>
        <tr>
          <th>ID</th><th>Symbol</th><th>Setup</th><th>Entry</th><th>Exit</th>
          <th>Shares</th><th>P&L $</th><th>R</th><th>Confluence</th><th>Result</th>
        </tr>
      </thead>
      <tbody id="journal-tbody"></tbody>
    </table>
    <div id="journal-empty" class="empty" style="display:none">No completed trades yet</div>
  </div>

</main>

<script>
const fmt = (n, dec=2) => n == null ? '—' : parseFloat(n).toFixed(dec)
const fmtDollar = n => n == null ? '—' : `$${parseFloat(n).toFixed(2)}`
const fmtPct = n => n == null ? '—' : `${parseFloat(n).toFixed(1)}%`

function colorClass(val, goodDir='pos') {
  if (val == null || val === '—') return 'neu'
  const v = parseFloat(val)
  if (isNaN(v) || v === 0) return 'neu'
  return (goodDir === 'pos' ? v > 0 : v < 0) ? 'pos' : 'neg'
}

function regimeBadgeClass(r) {
  if (!r) return 'badge-muted'
  if (r.includes('TRENDING')) return 'badge-green'
  if (r.includes('CHOPPY')) return 'badge-yellow'
  if (r.includes('NO_TRADE')) return 'badge-red'
  return 'badge-muted'
}

function setupBadge(name) {
  return `<span class="badge badge-blue" style="font-size:10px">${name}</span>`
}

function setupFlags(flags) {
  if (!flags) return '—'
  const active = Object.entries(flags).filter(([k,v]) => v).map(([k]) => k.replace('_',''))
  return active.length ? active.map(s => `<span class="badge badge-green" style="font-size:10px;padding:2px 6px">${s}</span>`).join(' ')
                       : '<span style="color:var(--muted)">—</span>'
}

function renderRegime(ctx) {
  const r = ctx.market_regime || {}
  const cls = regimeBadgeClass(r.classification)
  document.getElementById('regime-badge').className = `badge ${cls}`
  document.getElementById('regime-badge').textContent = (r.classification || '—').replace('_', ' ')
  document.getElementById('regime-name').textContent = (r.classification || '—').replace(/_/g,' ')
  document.getElementById('regime-reason').textContent = r.reason || ''

  const setups = document.getElementById('setups-active')
  setups.innerHTML = (r.setups_active || []).map(s => setupBadge('Setup ' + s)).join('')
  if (!r.setups_active?.length) setups.innerHTML = '<span class="badge badge-red" style="font-size:10px">NO TRADE</span>'

  document.getElementById('spy-grid').innerHTML = [
    ['SPY', fmtDollar(r.spy_price)],
    ['RSI', fmt(r.spy_rsi_14,1)],
    ['VIX', fmt(r.vix,1)],
    ['EMA 20', fmtDollar(r.spy_ema20)],
    ['EMA 50', fmtDollar(r.spy_ema50)],
    ['Day Chg', fmtPct(r.spy_daily_change_pct)],
  ].map(([l,v]) => `<div class="spy-item"><div class="label">${l}</div><div class="value">${v}</div></div>`).join('')
}

function renderAccount(ctx) {
  const a = ctx.account_state || {}
  document.getElementById('account-value').textContent = fmtDollar(a.paper_account_value)
  document.getElementById('account-grid').innerHTML = [
    ['Portfolio', fmtDollar(a.paper_account_value)],
    ['Cash', fmtDollar(a.cash_available)],
    ['Positions', `${a.open_positions ?? '—'} / 3`],
    ['Daily P&L', fmtPct(a.daily_pnl_pct)],
    ['Drawdown', `-${fmt(a.drawdown_from_peak_pct,1)}%`],
    ['Consec. Loss', a.consecutive_losses ?? '—'],
  ].map(([l,v]) => `<div class="spy-item"><div class="label">${l}</div><div class="value">${v}</div></div>`).join('')

  if (a.trading_halted) {
    document.getElementById('halt-banner').style.display = 'block'
  }
}

function renderRiskGate(risk) {
  document.getElementById('risk-grid').innerHTML = [
    ['Peak Value', fmtDollar(risk.peak_account_value)],
    ['Daily P&L', fmtDollar(risk.daily_pnl_dollars)],
    ['Consec. Loss', risk.consecutive_losses ?? 0],
    ['Trades/Wk', risk.trades_this_week ?? 0],
    ['Halted', risk.halt_until ? 'YES' : 'No'],
    ['Halt Until', risk.halt_until ? risk.halt_until.slice(0,16) : '—'],
  ].map(([l,v]) => `<div class="spy-item"><div class="label">${l}</div><div class="value">${v}</div></div>`).join('')
}

function renderPositions(ctx) {
  const positions = ctx.open_positions || []
  const el = document.getElementById('positions-list')
  if (!positions.length) { el.innerHTML = '<div class="empty">No open positions</div>'; return }

  el.innerHTML = positions.map(p => {
    const pnl = parseFloat(p.pnl_dollars || 0)
    const pnlClass = pnl > 0 ? 'pos' : pnl < 0 ? 'neg' : 'neu'
    const r = p.pnl_r ?? 0
    const rPct = Math.min(Math.max((r / 3) * 100, 0), 100)
    const rColor = r >= 1 ? 'var(--green)' : r >= 0 ? 'var(--yellow)' : 'var(--red)'
    return `
    <div class="position-row">
      <div class="pos-header">
        <div>
          <span class="pos-symbol">${p.symbol}</span>
          <span class="badge badge-blue" style="margin-left:8px;font-size:10px">${p.setup_type||'—'}</span>
        </div>
        <div class="pos-pnl ${pnlClass}">${fmtDollar(p.pnl_dollars)}</div>
      </div>
      <div class="pos-meta">
        <div class="pos-meta-item"><div class="label">Entry</div><div class="value">${fmtDollar(p.entry_price)}</div></div>
        <div class="pos-meta-item"><div class="label">Current</div><div class="value">${fmtDollar(p.current_price)}</div></div>
        <div class="pos-meta-item"><div class="label">Stop</div><div class="value neg">${fmtDollar(p.stop_level)}</div></div>
        <div class="pos-meta-item"><div class="label">Target</div><div class="value pos">${fmtDollar(p.target_level)}</div></div>
      </div>
      <div class="r-bar-wrap">
        <div class="r-bar-label">Progress: ${fmt(r,2)}R of 2R target</div>
        <div class="r-bar-track"><div class="r-bar-fill" style="width:${rPct}%;background:${rColor}"></div></div>
      </div>
      ${p.action_required && p.action_required !== 'None — let it run'
        ? `<div style="margin-top:8px;font-size:11px;color:var(--yellow)">⚠ ${p.action_required}</div>`
        : ''}
    </div>`
  }).join('')
}

function renderProposal(proposal) {
  const el = document.getElementById('proposal-list')
  if (!proposal || (!proposal.proposals?.length && !proposal.no_trade_reason)) {
    el.innerHTML = '<div class="empty">No proposal yet today</div>'; return
  }
  if (proposal.no_trade_reason) {
    el.innerHTML = `<div class="empty" style="color:var(--red)">NO TRADE — ${proposal.no_trade_reason}</div>`; return
  }

  el.innerHTML = proposal.proposals.map(p => {
    const conf = p.confluence || {}
    const signals = ['trend_ema_stack','momentum_rsi','macd_direction','volume_confirmation','setup_pattern_match']
    const confChips = signals.map(s => `<span class="signal-chip ${conf[s]==='GREEN'?'green':'red'}">${s.replace(/_/g,' ')}</span>`).join('')
    const rg = p.risk_gate || {}
    const confBadge = conf.count >= 5 ? 'badge-green' : conf.count >= 4 ? 'badge-blue' : 'badge-yellow'
    return `
    <div class="proposal-card">
      <div class="proposal-header">
        <div>
          <div class="proposal-symbol">${p.symbol}</div>
          <div class="proposal-setup">${p.setup_type} · ${p.hold_duration_est_days||'—'} days</div>
        </div>
        <div>
          <span class="badge ${confBadge}">${p.confidence||'—'}</span>
          <div style="font-size:10px;color:var(--muted);text-align:right;margin-top:4px">${conf.count||0}/5 signals</div>
        </div>
      </div>
      <div class="signal-list">${confChips}</div>
      <div class="proposal-section-title">Bull Case</div>
      <ul class="case-list">${(p.bull_case||[]).map(b=>`<li>${b}</li>`).join('')}</ul>
      <div class="proposal-section-title">Bear Case</div>
      <ul class="case-list">${(p.bear_case||[]).map(b=>`<li>${b}</li>`).join('')}</ul>
      <div class="risk-grid">
        <div class="risk-item"><div class="label">Entry</div><div class="value">${fmtDollar(rg.entry_price)}</div></div>
        <div class="risk-item"><div class="label">Stop</div><div class="value neg">${fmtDollar(rg.stop_price)}</div></div>
        <div class="risk-item"><div class="label">Target</div><div class="value pos">${fmtDollar(rg.target_price)}</div></div>
        <div class="risk-item"><div class="label">Shares</div><div class="value">${fmt(rg.shares,4)||'—'}</div></div>
        <div class="risk-item"><div class="label">$ Risk</div><div class="value">${fmtDollar(rg.dollar_risk)}</div></div>
        <div class="risk-item"><div class="label">Pos %</div><div class="value">${rg.position_pct_of_account ? fmtPct(rg.position_pct_of_account*100) : '—'}</div></div>
      </div>
      ${p.synthesis ? `<div class="synthesis-box">${p.synthesis}</div>` : ''}
    </div>`
  }).join('')
}

function renderWatchlist(ctx) {
  const rows = ctx.watchlist || []
  const tbody = document.getElementById('watchlist-tbody')
  if (!rows.length) { tbody.innerHTML = '<tr><td colspan="10" class="empty">No data</td></tr>'; return }

  tbody.innerHTML = rows.map(r => {
    const chgClass = parseFloat(r.daily_change_pct) > 0 ? 'pos' : parseFloat(r.daily_change_pct) < 0 ? 'neg' : 'neu'
    const rsiColor = r.rsi_14 > 70 ? 'color:var(--red)' : r.rsi_14 < 35 ? 'color:var(--green)' : ''
    const volColor = r.volume_ratio >= 1.5 ? 'color:var(--green)' : r.volume_ratio < 0.7 ? 'color:var(--muted)' : ''
    const emaAlign = r.ema20 > r.ema50 && r.ema50 > r.ema200
      ? '<span style="color:var(--green)">↑</span>' : '<span style="color:var(--red)">↓</span>'
    return `<tr>
      <td class="symbol-cell">${r.symbol}</td>
      <td>${fmtDollar(r.price)}</td>
      <td class="${chgClass}">${fmtPct(r.daily_change_pct)}</td>
      <td style="${rsiColor}">${fmt(r.rsi_14,1)}</td>
      <td>${fmtDollar(r.ema20)} ${emaAlign}</td>
      <td>${fmtDollar(r.ema50)}</td>
      <td>${fmtDollar(r.ema200)}</td>
      <td>${fmt(r.atr_14,2)}</td>
      <td style="${volColor}">${fmt(r.volume_ratio,2)}x</td>
      <td>${setupFlags(r.setup_flags)}</td>
    </tr>`
  }).join('')
}

function renderStats(stats) {
  const wr = stats.win_rate
  const pf = stats.profit_factor
  const rr = stats.avg_rr

  document.getElementById('stat-pnl').textContent = fmtDollar(stats.net_pnl)
  document.getElementById('stat-pnl').className = `stat-value ${colorClass(stats.net_pnl)}`

  document.getElementById('stat-winrate').textContent = wr != null ? `${wr}%` : '—'
  document.getElementById('stat-winrate').className = `stat-value ${wr == null ? 'neu' : wr >= 40 ? 'pos' : 'neg'}`

  document.getElementById('stat-pf').textContent = pf != null ? fmt(pf) : '—'
  document.getElementById('stat-pf').className = `stat-value ${pf == null ? 'neu' : pf >= 1.5 ? 'pos' : pf >= 1.0 ? 'neu' : 'neg'}`

  document.getElementById('stat-rr').textContent = rr != null ? fmt(rr) : '—'
  document.getElementById('stat-rr').className = `stat-value ${rr == null ? 'neu' : rr >= 2.0 ? 'pos' : rr >= 1.0 ? 'neu' : 'neg'}`
}

function renderJournal(stats) {
  const trades = stats.recent_trades || []
  const tbody = document.getElementById('journal-tbody')
  const empty = document.getElementById('journal-empty')

  if (!trades.length) {
    tbody.innerHTML = ''
    empty.style.display = 'block'
    return
  }
  empty.style.display = 'none'

  tbody.innerHTML = trades.map(t => {
    const pnl = parseFloat(t.gross_pnl || 0)
    const r = parseFloat(t.r_multiple || 0)
    const pnlClass = pnl > 0 ? 'pos' : pnl < 0 ? 'neg' : 'neu'
    const resultBadge = pnl > 0
      ? '<span class="badge badge-green" style="font-size:10px">WIN</span>'
      : '<span class="badge badge-red" style="font-size:10px">LOSS</span>'
    return `<tr>
      <td style="color:var(--muted);font-size:11px">${t.trade_id||'—'}</td>
      <td class="symbol-cell">${t.symbol}</td>
      <td><span class="badge badge-blue" style="font-size:10px">${t.setup_type||'—'}</span></td>
      <td>${t.entry_price ? fmtDollar(t.entry_price) : '—'}</td>
      <td>${t.exit_price ? fmtDollar(t.exit_price) : '—'}</td>
      <td>${fmt(t.shares,4)}</td>
      <td class="${pnlClass}">${fmtDollar(pnl)}</td>
      <td class="${r>0?'pos':r<0?'neg':'neu'}">${fmt(r,2)}R</td>
      <td><div class="confluence">${Array.from({length:5},(_,i)=>`<div class="dot ${i<parseInt(t.confluence_score||0)?'dot-green':'dot-red'}"></div>`).join('')}</div></td>
      <td>${resultBadge}</td>
    </tr>`
  }).join('')
}

async function fetchAll() {
  try {
    const [ctx, proposal, stats, risk] = await Promise.all([
      fetch('/api/context').then(r=>r.json()),
      fetch('/api/proposal').then(r=>r.json()),
      fetch('/api/stats').then(r=>r.json()),
      fetch('/api/risk').then(r=>r.json()),
    ])
    renderRegime(ctx)
    renderAccount(ctx)
    renderPositions(ctx)
    renderWatchlist(ctx)
    renderProposal(proposal)
    renderStats(stats)
    renderJournal(stats)
    renderRiskGate(risk)
    document.getElementById('refresh-time').textContent = `Updated ${new Date().toLocaleTimeString()}`
  } catch(e) {
    console.error('Refresh failed:', e)
    document.getElementById('refresh-time').textContent = `Error: ${e.message}`
  }
}

fetchAll()
setInterval(fetchAll, 60000)
</script>
</body>
</html>"""

if __name__ == "__main__":
    os.chdir(ROOT)
    print("Dashboard: http://localhost:5001")
    app.run(host="0.0.0.0", port=5001, debug=False)
