# Strategy Playbook — AI Swing Trading Agent
Version: 1.0 | Created: 2026-06-02

## Permitted Setups (Only These Three)

### Setup A: EMA-20 Pullback in an Uptrend
| Parameter | Rule |
|-----------|------|
| Regime required | TRENDING_UP |
| Entry trigger | Price pulls back within 1% of 20 EMA and closes back above it on daily candle, RSI 40–60 |
| Volume | ≥ 80% of 20-day average |
| Stop | 1.5× ATR(14) below entry candle low |
| Target | 2:1 R multiple or prior swing high, whichever first |
| Invalidation | Price closes below 50 EMA — exit immediately |

### Setup B: Breakout from Tight Consolidation
| Parameter | Rule |
|-----------|------|
| Regime required | TRENDING_UP or transitioning from Choppy to Trending |
| Entry trigger | Price breaks above range ≥ 5 bars wide, ≤ 8% height, on candle closing near its high |
| Volume | ≥ 150% of 20-day average (mandatory — no volume, no trade) |
| Stop | Below consolidation low or 1.5× ATR(14), whichever tighter |
| Target | 1.5× range height projected up or 3:1 R, whichever smaller |
| Invalidation | Any close back inside the consolidation range |

### Setup C: Mean Reversion on Oversold Strong Names
| Parameter | Rule |
|-----------|------|
| Regime required | CHOPPY only — never in strong downtrend |
| Entry trigger | RSI(14) drops below 30 on stock above 200 EMA; enter on first candle where RSI closes back above 30 |
| Volume | ≥ 100% of 20-day average |
| Stop | Below lowest low of oversold sequence or 2× ATR(14) |
| Target | Return to 20 EMA or 2:1 R, whichever first |
| Invalidation | New low below entry stop OR RSI re-enters oversold territory |

## Indicator Stack
| Indicator | Settings | Purpose |
|-----------|----------|---------|
| EMA | 20, 50, 200 (daily close) | Trend structure, dynamic support/resistance |
| RSI | 14 periods (daily close) | Momentum, overbought/oversold filter |
| MACD | 12/26/9 | Momentum confirmation (histogram direction) |
| ATR | 14 periods (daily true range) | Stop placement, position sizing |
| Volume | 20-period SMA overlay | Confirms breakouts, flags exhaustion |

## Confluence Rule: 3-of-5 Minimum
| Signal | GREEN Condition | RED Condition |
|--------|----------------|---------------|
| Trend (EMA stack) | 20 > 50 > 200 EMA | Crossed or wrong order |
| Momentum (RSI) | 40–65 pullback; < 30 recovering for reversion | > 75 overbought or < 20 broken |
| MACD | Histogram turning positive | Accelerating against trade |
| Volume | Meets setup threshold | Below threshold |
| Setup pattern | Exactly matches one permitted setup | Ambiguous or no match |

## Market Regime Detection
| Regime | Detection Rule | Setups Active |
|--------|---------------|---------------|
| TRENDING_UP | SPY EMA20 > EMA50 > EMA200 AND RSI > 50 AND within 5% of 52wk high | A (primary), B (secondary) |
| CHOPPY_RANGE | SPY oscillating between EMAs, RSI 40–60, no direction over 10 days | C (primary), B on clear breakouts |
| NO_TRADE_RISK_OFF | SPY below 200 EMA, OR drops > 3% in a day, OR VIX > 30 | None |

## Position Sizing
```
Dollar Risk (DR) = Account Value × 1.5%
Shares = DR ÷ (Entry − Stop)
Max position = 50% of account
```

## Hard Limits (in code, not prompt)
| Limit | Value |
|-------|-------|
| Max risk per trade | 1.5% of account |
| Max concurrent positions | 3 |
| Max daily loss | 3% of account (halts day) |
| Max drawdown circuit breaker | 15% from peak (requires manual reset) |
| Three consecutive losses | 48-hour halt |
| Max trades per week | 5 round trips |

## Watchlist
| Symbol | Name | Setups | Notes |
|--------|------|--------|-------|
| SPY | S&P 500 ETF | Regime only | Barometer, rarely trade |
| QQQ | Nasdaq-100 ETF | A, B | Tech proxy |
| AAPL | Apple | A, B | Liquid, clean EMA behavior |
| MSFT | Microsoft | A, B | Strong trend instrument |
| NVDA | Nvidia | B only | High ATR — use extra caution |
| AMD | AMD | All | Lower price than NVDA |
| JPM | JPMorgan | C | Mean reversion candidate |
| XLE | Energy ETF | C | Sector diversity |

## Changelog
| Date | Change | Reason |
|------|--------|--------|
| 2026-06-02 | v1.0 — initial | System launch |
