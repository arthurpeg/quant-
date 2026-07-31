---
type: system
updated: 2026-07-31
status: frozen (in-sample; forward-test pending)
---

# The 4-Brick System — current deployable book

> The synthesis of the whole project: four **decorrelated** edges ("bricks"), each
> with mandatory SL/TP/time-exit, on liquid OHLCV, prop-firm compliant, measured in
> **R** (SL = −1 R). This page links to the code that owns each rule — it does not
> restate the parameters (they live in the files and would rot here). See
> [[exp-009-ibs-reversion-4th-brick]], [[exp-008-crypto-breakout-3rd-brick]],
> [[exp-007-turn-of-month-2nd-brick]], [[exp-005-mt5-intraday-vol-breakout]].
> Numbers below are **findings**, not config.

## The four bricks

| # | Brick | Asset(s) | Mechanism | Code (source of truth) | Standalone |
|---|-------|----------|-----------|------------------------|-----------|
| 1 | **US-open ATR breakout**, low-vol regime (ATR3<ATR20 on D1) | NAS100 (real M1) | intraday breakout | [`edgelab/intraday/atr_breakout.py`](../edgelab/intraday/atr_breakout.py) — `run_atr_breakout('NAS100', regime_mode='low', direction='both')` | +11.6 R/yr, PF 1.27 |
| 2 | **Turn-of-month**, SL = 1.5·ATR14 | XAUUSD (D1) | seasonality | [`edgelab/edges/turn_of_month.py`](../edgelab/edges/turn_of_month.py) — `run_turn_of_month('XAUUSD', sl_atr=1.5)` | +2.2 R/yr, PF 1.68 |
| 3 | **MACD(12,26,9)+RSI** ([arXiv 2206.12282](https://arxiv.org/abs/2206.12282)) | BTC+ETH (D1) | crypto trend | daily `BacktestEngine` + `macd_rsi` signal; data `data_cache_crypto/` (Yahoo) | +24.0 R/yr (Yahoo) / **+16.7 R/yr (Pepperstone, live data)** |
| 4 | **IBS reversion**, SL = 2.5·ATR14 (buy IBS<0.2, exit IBS>0.8 / 30-bar) | NAS100 (D1) | intraday-position reversion | [`edgelab/edges/ibs.py`](../edgelab/edges/ibs.py) — `run_ibs('NAS100', IBSParams(sl_atr=2.5))` | **+5.2 R/yr, PF 1.94, t=4.68** |

Brick 4 (added 2026-07-31, [[exp-009-ibs-reversion-4th-brick]]) is the first brick-4
candidate to **improve the book on every axis**. US500 IBS is the same-asset-avoiding
alternative (weaker: split-half early t=1.45, cost-fragile). It is **long equity beta** —
size ≤1R, do not over-weight (tail co-moves in a secular bear).

Coin set for brick 3 = **BTC+ETH only** (user-verified more drawdown-efficient than
adding SOL/ADA — alts add correlated crash risk, not diversification).
Breakout-20 (`VolatilityBreakoutEdge(channel=20)`) is the lower-tail **conservative
alternative** to MACD-RSI. Single-MA-50 is the fallback if crypto is not prop-tradable.

## Why these edges (the finding — corrected 2026-07-31: three → four)

Across **9000 arXiv papers** and the full technical canon (MA/MACD/Bollinger/CCI/ADX/
SAR/Keltner/Aroon/Ichimoku, RSI2/z-score/Williams%R/Stochastic, VWAP, candlesticks,
OPR, TS/XS momentum, pairs, calendar), **every family converges to a small set of edges
or fails net of cost**. On liquid OHLCV: the trend edge exists **only in crypto** + the
**NAS opening breakout**; FX daily direction has no edge net of cost; seasonality =
turn-of-month.

⚠️ **The old claim "reversion is dead everywhere" was too strong and is CORRECTED.**
The reversion tests that failed were generic (index z-score/RSI2 t=1.23, lag-reversal =
bid-ask bounce, FX/crypto random-walk). But the **IBS** signal (where the close sits in
the day's range) **is a genuine reversion edge on US equity indices** — NAS100 t=4.68,
US500 t=3.36, US2000 t=2.70 (Europe/Asia ≈ 0), net of cost, robust to split-half + cost +
bootstrap → **brick 4** ([[exp-009-ibs-reversion-4th-brick]]). So a 4th decorrelated brick
did **not** need different data after all — it needed the *right* reversion signal on the
*right* (US-index) universe. Whether a 5th needs options-implied data (VRP/skew) is still
open. See [[ledger]] and [[lessons]].

## Decorrelation & combined backtest (equal 1 R/trade, 2018-07→2026-07, 8 yr)

Pairwise daily-P&L correlations all ≈ 0. Brick 4 (IBS NAS100) vs the others:
**+0.024 / −0.017 / −0.035** (NAS / gold / crypto) — same order as the existing
brick-brick corrs (NAS/gold +0.019, NAS/crypto −0.014, gold/crypto −0.007). (The
exploratory run reported +0.001/+0.016/−0.008 on a slightly different daily-R
construction; both say the same thing — max |corr| ≈ 0.03.)

| Metric | 3-brick | **4-brick (+ IBS NAS100)** |
|--------|---------|-----------|
| **Total (Pepperstone, canonical)** | +263 R (+32.5 R/yr) | **+308 R (+38.2 R/yr)**; NAS +12.9 + gold +2.5 + crypto +17.1 + IBS +5.6 |
| maxDD / RoMaD / Sharpe | 15.8 R / 2.06 / 2.42 | **13.4 R / 2.85 / 2.63** |
| worst day | −4.15 R | −4.15 R (IBS never trades the worst day) |
| MC median R/yr, P(profit) | +32.1, 96.5% | **+37.6, 98.2%** |
| MC 5th-pct year, median maxDD | +2.6 R, 10.5 R | **+7.7 R, 10.0 R** |

Adding brick 4 **raises return AND Sharpe AND lowers maxDD** — the first candidate to do
all three (the ⭐ [[ledger]] candidates lowered Sharpe or correlated to brick 1). Combined
maxDD stays **below the worst single brick** (NAS ~16.6 R) → decorrelation empties **risk**,
not return.

**HTML reports** (self-contained, in `edgelab/reports/`): `portfolio_backtest.html` (equity
curve, per-brick, correlation, annual R) and `monte_carlo.html` (percentile fan,
distributions, prop-firm odds by sizing). Both are **regenerated by one command** —
[`edgelab/reports/build_reports.py`](../edgelab/reports/build_reports.py), which recomputes
the book and re-runs the MC through `monte_carlo_static.simulate()` (the same function the
CLI prints from, so report and printout can't disagree) and re-injects the data blobs.
Run it after adding or changing a brick. Brick 3 is priced on the Pepperstone crypto feed
(the live-realistic book).

## Monte Carlo (block-bootstrap, no compounding, 1 R = risk% of **initial** balance)

⚠️ **Corrected 2026-07-29.** The earlier MC (~+28.5 R/yr) was wrong — two stacked bugs,
both understating: (a) it used the **compounding** engine mark-to-market for the crypto
brick instead of fixed-fractional trade-R; (b) it reindexed on business days
(`freq='B'`), silently **dropping crypto weekend exits**. Fixed = fixed-fractional
trade-R on a **calendar** index. The MC median matches the historical backtest to ~0.5 R/yr
— the correctness check for a block-bootstrap. Reproducible:
[`edgelab/reports/monte_carlo_static.py`](../edgelab/reports/monte_carlo_static.py).

**4-brick, 1-year distribution (40k sims, blocks of 14 d):** P(profitable year) = **98.2%**,
mean **+38.0 R** (historical +38.2).

| Pct | annual R | maxDD R |
|-----|---------:|--------:|
| 5th | +7.7 | 5.9 |
| 25th | +25.0 | 8.0 |
| **50th** | **+37.6** | **10.0** |
| 75th | +50.6 | 12.8 |
| 95th | +69.7 | 18.5 |

maxDD tail: 99th pct 24.0 R, worst 44.9 R.

## Prop sizing — firm with STATIC drawdown (target +15% / total −10% / daily −5%)

**Structural ceiling ≈ 1.2%/trade:** the worst historical day is −4.15 R, so above
~1.2% the −5% daily rule starts causing breaches.

**Challenge (time-to-pass, 4-brick):**
- **1.00%/trade = optimal** — **92.8%** pass in **~3.8 months** median, **0%** daily-rule breaches.
- 0.75% = 96.5% pass, ~5.4 months (max safety).
- ≥1.25% collapses pass rate (71.9%) as the daily rule bites (19.4% daily breaches).

**Funded (static −10% floor, monthly payout resets balance to initial):**
- **0.50%/trade** → ~**19.7%/yr** withdrawn, **1.8%** ruin/yr (keep-the-account choice).
- 0.75% → ~28.9%/yr, ~12% ruin/yr.
- **Never above 1%** — E[withdrawn] plateaus at 41–44% while ruin explodes past 49%.
- **Asymmetric plan:** pass the challenge at 1.0% (speed), drop to 0.5% once funded (protection).

**Payout cadence:** biweekly is **not** better. Annual income is ~flat across cadence,
but frequent payout strips the cushion (reset to 100% = always 10% from the static
floor) → **~2× the ruin risk** vs monthly/quarterly. Take payouts **as infrequently as
cashflow allows**; the only reason to withdraw often is **counterparty risk** (the firm
itself). If partial withdrawals are allowed, keep a **+4% cushion** (ruin 17.6% → 6.5%
for −3 pts of income). Reproducible: [`edgelab/reports/payout_frequency.py`](../edgelab/reports/payout_frequency.py).

## Independent verification (2026-07-30) — "are these good reproducible edges live?"

A full re-audit, run from scratch (not trusting these tables). Two separable claims:

**(a) Code reproducibility — PROVEN.** `python -m edgelab.live.verify` re-ran clean:
brick 1 **830/830** exact entries, brick 2 **124/126** (the only 2 misses are Good
Friday 2018-03-29 & 2024-03-28 — market closed, the live business-day calendar approx
skips them), brick 3 signal + barriers **identical**. → the live runner places the
trades the backtest predicts; no divergence.

**(b) Edge stats — reproduce to the decimal** (independently recomputed on the 2018-07+
live-realistic window; `scratchpad/verify_bricks.py`):

| Brick | n | R/yr | PF | t (per-trade) | +yrs |
|-------|---|-----:|---:|--------------:|------|
| 1 NAS ORB | 784 | +13.0 | 1.27 | **3.01** | 7/9 |
| 2 gold ToM | 96 | +2.5 | 1.86 | **2.35** | 7/9 |
| 3 crypto MACD-RSI | 721 | +17.2 | 1.57 | **5.25** | 8/9 |
| **combined** | — | **+32.5** | — | Sharpe **2.42** | 8/9 |

Decorrelation confirmed: NAS/gold +0.02, NAS/crypto −0.01, gold/crypto −0.01.
(This audit predates brick 4; **brick 4 IBS** n=300, +5.6 R/yr, t=4.68 was added and
re-run into the canonical reports on **2026-07-31** — corrs to the three all ≤|0.03|,
combined → +38.2 R/yr, Sharpe 2.63. See [[exp-009-ibs-reversion-4th-brick]].)

**(c) Robustness stress** (`scratchpad/robustness.py`) — the confidence order is
**brick 3 > brick 1 > brick 2**:
- **Brick 3 is not just 2020.** 2020 alone = +48.7 R = 35% of total; excluding it still
  **+12.7 R/yr, t=3.63**. The strongest, most robust brick.
- **Brick 1's vol-regime filter carries the edge:** regime=low t=2.80 → **regime=off
  t=1.66 (sub-threshold)** → high t=−0.46. Real, but conditional on a fitted (though
  mechanism-motivated) filter. Cost-robust to 8pt slippage on the bar model — **but**
  [[exp-005-mt5-intraday-vol-breakout]] shows bar-M1 **under-counts intrabar stops**
  (honest real-tick PF ~1.2–1.3 < 1.27) → live likely thinner.
- **Brick 2 is a thin diversifier** (~12 trades/yr, +2.5 R/yr); its value is the
  decorrelation, not the return, and it sits on the multiple-testing borderline (t=2.35).

**Bottom line.** In-sample the three are genuine and decorrelated; the code will
reproduce them live. What is **still unproven is out-of-sample persistence** — the
forward test holds **2 trades so far** (both brick 3), and the backtest is mildly
optimistic on all three (bar stops b1, ETH spread b3, holiday-calendar drift b2). The
only remaining judge is forward-test time; nothing in the code needs changing.

## Caveats (why this is "frozen candidate", not "deployed")

1. **All in-sample** on candidate bricks — no genuine forward test yet.
2. Brick 1 t≈3.0 is **regime-selected** (regime-off t=1.69); brick 2 is a **thin**
   diversifier (~12 trades/yr, t=2.18); brick 3 now **re-validated on Pepperstone live
   data** (t=3.93, +16.7 R/yr) but crypto **prop-tradability varies by firm** — verify
   your firm allows it before deploying; brick 4 is **long equity beta** (corr ~0
   understates tail co-movement in a secular bear).
2b. **Brick 4 live is thinner than its backtest by construction: +4.8 vs +5.6 R/yr.**
   `run_ibs` can re-enter on the **same daily bar a stop fired**, filling at that bar's
   *open* — a price already in the past by then. No live driver can take those (13 trades,
   −6.8 R over 2018-07→2026-07). The edge itself is unaffected (live-cadence **t=5.16**,
   PF 2.21, 8/9 +yrs — both *better* than the backtest's 4.77/1.99). The canonical reports
   still use `run_ibs`, so the book's **+38.2 R/yr reads ~0.8 R/yr optimistic**.
   `python -m edgelab.live.verify` prints this gap on every run.
3. Block-bootstrap **understates long crypto bear regimes** → real funded ruin likely
   a bit above the numbers above → argues for the conservative sizing end.

## Going live / forward-test (`edgelab/live/`)

Built 2026-07-29, **brick 4 added 2026-07-31**: **one Python process** on MT5/Pepperstone
runs all four bricks as strategy modules under **one shared risk manager** (the
architecture chosen for these low-frequency, bar-based bricks — Python reuses the exact
backtest math so live can't diverge; MQL5 was rejected to avoid re-implementation drift).
Proven with `python -m edgelab.live.verify` → brick1 **830/830** exact, brick3 identical,
brick2 ~98% (holiday-shifted month-ends), brick4 **314/314 trades exact** on signal math.
Start: `python -m edgelab.live.runner`.

**Brick 4 live wiring** (magic **105**, `NasIbsStrategy`): decides once per broker day at
the D1 rollover like bricks 2–3, long-only, **no TP** — exits are the broker-managed stop,
`IBS > 0.8` at a close, or 30 D1 bars (counted in *bars*, not calendar days, since NAS100
prints none at weekends). It shares NAS100 with brick 1 but holds a **separate position**
under its own magic. It waits for the day's bar to actually print before entering, so the
stop is never sized off a stale close. No config change was needed to deploy it
(`ibs_symbol`/`enable_ibs` default to NAS100/true).

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
