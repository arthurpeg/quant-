---
type: system
updated: 2026-07-29
status: frozen (in-sample; forward-test pending)
---

# The Frozen 3-Brick System — current deployable book

> The synthesis of the whole project: three **decorrelated** edges ("bricks"), each
> with mandatory SL/TP/time-exit, on liquid OHLCV, prop-firm compliant, measured in
> **R** (SL = −1 R). This page links to the code that owns each rule — it does not
> restate the parameters (they live in the files and would rot here). See
> [[exp-008-crypto-breakout-3rd-brick]], [[exp-007-turn-of-month-2nd-brick]],
> [[exp-005-mt5-intraday-vol-breakout]]. Numbers below are **findings**, not config.

## The three bricks

| # | Brick | Asset(s) | Mechanism | Code (source of truth) | Standalone |
|---|-------|----------|-----------|------------------------|-----------|
| 1 | **US-open ATR breakout**, low-vol regime (ATR3<ATR20 on D1) | NAS100 (real M1) | intraday breakout | [`edgelab/intraday/atr_breakout.py`](../edgelab/intraday/atr_breakout.py) — `run_atr_breakout('NAS100', regime_mode='low', direction='both')` | +11.6 R/yr, PF 1.27 |
| 2 | **Turn-of-month**, SL = 1.5·ATR14 | XAUUSD (D1) | seasonality | [`edgelab/edges/turn_of_month.py`](../edgelab/edges/turn_of_month.py) — `run_turn_of_month('XAUUSD', sl_atr=1.5)` | +2.2 R/yr, PF 1.68 |
| 3 | **MACD(12,26,9)+RSI** ([arXiv 2206.12282](https://arxiv.org/abs/2206.12282)) | BTC+ETH (D1) | crypto trend | daily `BacktestEngine` + `macd_rsi` signal; data `data_cache_crypto/` (Yahoo) | +24.0 R/yr (Yahoo) / **+16.7 R/yr (Pepperstone, live data)** |

Coin set for brick 3 = **BTC+ETH only** (user-verified more drawdown-efficient than
adding SOL/ADA — alts add correlated crash risk, not diversification).
Breakout-20 (`VolatilityBreakoutEdge(channel=20)`) is the lower-tail **conservative
alternative** to MACD-RSI. Single-MA-50 is the fallback if crypto is not prop-tradable.

## Why exactly three (the ironclad finding)

Across **9000 arXiv papers** and the full technical canon (MA/MACD/Bollinger/CCI/ADX/
SAR/Keltner/Aroon/Ichimoku, RSI2/z-score/Williams%R/Stochastic, VWAP, candlesticks,
OPR, TS/XS momentum, pairs, calendar), **every family converges to these same three
edges or fails net of cost**. On liquid OHLCV the trend edge exists **only in crypto**
(the one liquid asset that trends hard enough to beat its spread) + the **NAS opening
breakout**; indices/FX daily direction has no edge net of cost; reversion is dead
everywhere; seasonality = turn-of-month. A 4th decorrelated brick needs **different
data** (options-implied: VRP/skew) — not more OHLCV. See [[ledger]] and [[lessons]].

## Decorrelation & combined backtest (equal 1 R/trade, 2018→2026, 8.6 yr)

Pairwise daily-P&L correlations ≈ 0: **NAS/gold +0.02, NAS/crypto 0.00, gold/crypto −0.03**.

| Metric | Value |
|--------|-------|
| Total (Yahoo crypto) | +325 R (**+37.9 R/yr**) |
| Total (Pepperstone crypto, live data) | **~+30.5 R/yr** (NAS +11.6 + gold +2.2 + crypto +16.7) |
| maxDD (historical) | **13.6 R** |
| RoMaD (R/yr ÷ maxDD) | **2.78** |
| Sharpe (annualised, active days) | **2.63** |
| Worst day / best day | −4.13 R / +7.87 R |
| Combined maxDD < worst single brick | 13.6 R < 16.6 R (NAS) → decorrelation empties **risk**, not return |

## Monte Carlo (block-bootstrap, no compounding, 1 R = risk% of **initial** balance)

⚠️ **Corrected 2026-07-29.** The earlier MC (~+28.5 R/yr) was wrong — two stacked bugs,
both understating: (a) it used the **compounding** engine mark-to-market for the crypto
brick instead of fixed-fractional trade-R; (b) it reindexed on business days
(`freq='B'`), silently **dropping crypto weekend exits**. Fixed = fixed-fractional
trade-R on a **calendar** index. The corrected MC median (**+37.6 R/yr**) now matches
the backtest (+37.9) — the correctness check for a block-bootstrap. Reproducible:
[`edgelab/reports/monte_carlo_static.py`](../edgelab/reports/monte_carlo_static.py).

**1-year distribution (40k sims):** P(profitable year) = **97.8%**.

| Pct | annual R | maxDD R |
|-----|---------:|--------:|
| 5th | +6.5 | 6.1 |
| 25th | +24.5 | 8.2 |
| **50th** | **+37.5** | **10.3** |
| 75th | +51.1 | 13.2 |
| 95th | +71.0 | 19.3 |

maxDD tail: 99th pct 25.3 R, worst 44.5 R.

## Prop sizing — firm with STATIC drawdown (target +15% / total −10% / daily −5%)

**Structural ceiling ≈ 1.2%/trade:** the worst historical day is −4.13 R, so above
~1.2% the −5% daily rule starts causing breaches.

**Challenge (time-to-pass):**
- **1.00%/trade = optimal** — 91% pass in **~3.7 months** median, **0%** daily-rule breaches.
- 0.75% = 96% pass, ~5.4 months (max safety).
- ≥1.25% collapses pass rate (72%) as the daily rule bites.

**Funded (static −10% floor, monthly payout resets balance to initial):**
- **0.50%/trade** → ~**20%/yr** withdrawn, **2.4%** ruin/yr (keep-the-account choice).
- 0.75% → ~29%/yr, ~15% ruin/yr.
- **Never above 1%** — E[withdrawn] plateaus at 40–43% while ruin explodes past 50%.
- **Asymmetric plan:** pass the challenge at 1.0% (speed), drop to 0.5% once funded (protection).

**Payout cadence:** biweekly is **not** better. Annual income is ~flat across cadence,
but frequent payout strips the cushion (reset to 100% = always 10% from the static
floor) → **~2× the ruin risk** vs monthly/quarterly. Take payouts **as infrequently as
cashflow allows**; the only reason to withdraw often is **counterparty risk** (the firm
itself). If partial withdrawals are allowed, keep a **+4% cushion** (ruin 17.6% → 6.5%
for −3 pts of income). Reproducible: [`edgelab/reports/payout_frequency.py`](../edgelab/reports/payout_frequency.py).

## Caveats (why this is "frozen candidate", not "deployed")

1. **All in-sample** on candidate bricks — no genuine forward test yet.
2. Brick 1 t≈3.0 is **regime-selected** (regime-off t=1.69); brick 2 is a **thin**
   diversifier (~12 trades/yr, t=2.18); brick 3 now **re-validated on Pepperstone live
   data** (t=3.93, +16.7 R/yr) but crypto **prop-tradability varies by firm** — verify
   your firm allows it before deploying.
3. Block-bootstrap **understates long crypto bear regimes** → real funded ruin likely
   a bit above the numbers above → argues for the conservative sizing end.

## Going live / forward-test (`edgelab/live/`)

Built 2026-07-29: **one Python process** on MT5/Pepperstone runs all three bricks as
three strategy modules under **one shared risk manager** (the architecture chosen for
these low-frequency, bar-based bricks — Python reuses the exact backtest math so live
can't diverge; MQL5 was rejected to avoid re-implementation drift). Proven with
`python -m edgelab.live.verify` → brick1 **830/830** exact, brick3 identical, brick2
~98% (holiday-shifted month-ends). Start: `python -m edgelab.live.runner`.

**Order sending is ENABLED (`live_trading: true`) — safe because the Pepperstone account
is a DEMO.** A hard gate (`allow_real_account: false`) refuses to send orders if the
connected account is not a demo (fails loudly rather than trading real money). The live
path attaches SL/TP to the position, picks a supported filling mode, clears the broker's
min-stop distance, clamps lots, retries on requotes, and journals every fill to
`edgelab/live/_out/trades.csv`. See `edgelab/live/README.md`.

**Brick 3 re-validated on Pepperstone (2026-07-29): ✅ holds.** Same signal/engine on
Pepperstone BTC+ETH D1 (2018-07+): **+16.7 R/yr, PF 1.55, maxDD 9.1R, t=3.93, corr −0.02,
9/9 years positive, gate PASS** (realistic cost BTC 6 / ETH 16 bps; cost-robust — even
pessimistic 8/20 bps → +16.2 R/yr, t=3.80). Lower than Yahoo (+22–25) because of shorter
history + a different broker daily-close time (not cost). Recent (2023+) spreads are
tighter than the historical median. So the live book expectation is **~+30 R/yr**, and
brick 3 trades the exact same signal live.

**Next action:** run the live (demo) forward test on Pepperstone; confirm the first
tickets risk ~1R with the broker's real tick value, and that the prop firm allows crypto.

**See also.** [[exp-005-mt5-intraday-vol-breakout]], [[exp-007-turn-of-month-2nd-brick]],
[[exp-008-crypto-breakout-3rd-brick]], [[breadth]], [[ledger]], [[data-sources]], [[codebase-map]].
</content>
</invoke>
