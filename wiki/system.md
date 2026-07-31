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
| 3 | **MACD(12,26,9)+RSI** ([arXiv 2206.12282](https://arxiv.org/abs/2206.12282)) | BTC+ETH (D1) | crypto trend | daily `BacktestEngine(cadence='live')` + `macd_rsi`; data `data_cache_mt5/` (Pepperstone) | **+6.9 R/yr, PF 1.27, t=2.43** (live cadence) |
| 4 | **IBS reversion**, SL = 2.5·ATR14 (buy IBS<0.2, exit IBS>0.8 / 30-bar) | NAS100 (D1) | intraday-position reversion | [`edgelab/edges/ibs.py`](../edgelab/edges/ibs.py) — `run_ibs('NAS100', IBSParams(sl_atr=2.5))` (live cadence) | **+4.8 R/yr, PF 2.21, t=5.16** |

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
**−0.00 / −0.03 / −0.01** (NAS / gold / crypto) — same order as the existing
brick-brick corrs (NAS/gold +0.02, NAS/crypto −0.01, gold/crypto −0.01). Max |corr|
across the whole 4×4 matrix is **0.03**.

| Metric | 3-brick | **4-brick (+ IBS NAS100)** |
|--------|---------|-----------|
| **Total (Pepperstone + live cadence, canonical)** | — | **+219 R (+27.1 R/yr)**; NAS +12.9 + gold +2.5 + crypto +6.9 + IBS +4.8 |
| maxDD / RoMaD / Sharpe | — | **14.1 R / 1.92 / 2.15** |
| Profit factor (pooled trades) | — | **1.34** (1737 trades, 53% win); per brick NAS 1.27 / gold 1.86 / crypto 1.27 / IBS 2.21 |
| Activity | — | **~215 trades/yr**: NAS ~95, crypto ~70, IBS ~35, gold 12 |
| worst day | −4.15 R | **−3.08 R** (crypto no longer books 4 same-day stops) |
| MC median R/yr, P(profit) | — | **+26.9, 96.3%** |
| MC 5th-pct year, median maxDD | — | **+2.1 R, 9.5 R** |

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

**4-brick, 1-year distribution (40k sims, blocks of 14 d):** P(profitable year) = **96.3%**,
mean **+27.1 R** (historical +27.1).

| Pct | annual R | maxDD R |
|-----|---------:|--------:|
| 5th | +2.1 | 5.6 |
| 25th | +16.5 | 7.5 |
| **50th** | **+26.9** | **9.5** |
| 75th | +37.5 | 12.2 |
| 95th | +52.6 | 17.8 |

maxDD tail: 99th pct 23.1 R, worst 44.4 R.

## Prop sizing — firm with STATIC drawdown (target +15% / total −10% / daily −5%)

**No daily-rule ceiling any more:** the worst historical day is **−3.08 R** (the crypto
brick no longer books four same-day stops), so the −5% daily rule is not breached at any
sizing tested up to 1.5%. The binding limit is now the **−10% static floor**.

**Challenge (time-to-pass, 4-brick):**
- **0.75%/trade = best pass rate** — **94.4%** in ~7.3 months; 1.00% = **91.6%** in **~5.1 months**.
- **0%** daily-rule breaches at every sizing; failures are now all total-DD.
- 1.25-1.5% still passes 83-87% but fails DD 13-17% — the trade-off is speed vs ruin.

**Funded (static −10% floor, monthly payout resets balance to initial):**
- **0.50%/trade** → ~**14.4%/yr** withdrawn, **1.6%** ruin/yr (keep-the-account choice).
- 0.75% → ~21.3%/yr, ~11% ruin/yr.
- **Never above 1%** — E[withdrawn] plateaus at 31–34% while ruin explodes past 45%.
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

⚠️ **This whole table is on the LITERAL cadence and is now known to be optimistic for
brick 3** — see the cadence correction below. Live-cadence brick 3 is n=570, **+6.9 R/yr,
PF 1.27, t=2.43, 6/9 +yrs**.

Decorrelation confirmed: NAS/gold +0.02, NAS/crypto −0.01, gold/crypto −0.01.
(This audit predates brick 4; **brick 4 IBS** was added and re-run into the canonical
reports on **2026-07-31**: on the live cadence n=287, **+4.8 R/yr, t=5.16**, corrs to the
three all ≤|0.03|. Canonical live-cadence book → **+27.1 R/yr, Sharpe 2.15**.
See [[exp-009-ibs-reversion-4th-brick]].)

**(c) Robustness stress** (`scratchpad/robustness.py`) — ⚠️ **the confidence order is
REVERSED by the cadence correction: brick 4 > brick 1 > brick 2 > brick 3.**
- ⚠️ **Brick 3 IS mostly 2020, on the honest cadence.** The old claim ("not just 2020,
  ex-2020 still +12.7 R/yr t=3.63, the strongest most robust brick") was measured on the
  literal cadence and is **WITHDRAWN**. Live cadence: 2020 alone = +27.4 R = **49% of the
  total**, and **ex-2020 it is +3.5 R/yr, t=1.30 — sub-threshold**. Worse, **2024 (−1.0 R)
  and 2025 (−6.9 R) are both negative**. Brick 3 is now the book's weakest link, not its
  workhorse.
- **Brick 1's vol-regime filter carries the edge:** regime=low t=2.80 → **regime=off
  t=1.66 (sub-threshold)** → high t=−0.46. Real, but conditional on a fitted (though
  mechanism-motivated) filter. Cost-robust to 8pt slippage on the bar model — **but**
  [[exp-005-mt5-intraday-vol-breakout]] shows bar-M1 **under-counts intrabar stops**
  (honest real-tick PF ~1.2–1.3 < 1.27) → live likely thinner.
- **Brick 2 is a thin diversifier** (~12 trades/yr, +2.5 R/yr); its value is the
  decorrelation, not the return, and it sits on the multiple-testing borderline (t=2.35).
  It is nonetheless the **2nd most efficient sleeve** (Sharpe 3.83) — do not drop it.
- **Brick 4 is now the most robust** (t=5.16 on the live cadence, PF 2.21, 8/9 +yrs,
  split-half stable) — and the only one whose t *rose* under the cadence correction.

**Bottom line (revised 2026-07-31).** The edges are genuine and decorrelated and the code
reproduces them live — but the *sizes* were not what the literal backtests said. After the
cadence correction the book is **+27.1 R/yr, not +37.3**, and the ranking is inverted:
bricks 1, 2, 4 hold up, **brick 3 is thin and 2020-dependent**. Out-of-sample persistence
remains unproven (forward test: 2 trades). Nothing in the *live* code needed changing —
the driver was already right; it was the backtest that was optimistic.

## Admission test for a 5th brick (measured 2026-07-31, `scratchpad/sleeve_swap.py`)

**Decorrelation is necessary but NOT sufficient.** Compared at *equal risk* (each config
sized to its own binding prop ceiling — which is the **−10% static floor**, not the daily
rule): adding the ⭐ [[ledger]] GER40 candidate *costs* 1.4 pts/yr and deepens maxDD
13.8→17.9 R **despite |corr| ≤ 0.045 to all four bricks**, because its standalone Sharpe
(1.63) is the lowest of the set. A sleeve with brick 4's efficiency, independent, instead
gives RoMaD 2.71→**3.12**, Sharpe 2.59→2.74, maxDD **13.8→13.6** and **+4.1 pts/yr**.
(Measured before the brick-3 cadence fix, so the *levels* moved; the *ordering* — which is
the finding — is unchanged, and crypto has since dropped to the bottom of the table.)

| Sleeve | R/yr | daily vol | **standalone Sharpe** |
|---|---|---|---|
| IBS (b4) | +4.8 | 0.442 | **4.84** |
| gold ToM (b2) | +2.5 | 0.868 | **3.83** |
| crypto (b3) | +6.9 | 1.320 | 1.14 |
| NAS ORB (b1) | +12.9 | 1.238 | 1.71 |
| *GER40 (candidate)* | *+8.6* | *1.368* | *1.63* |

Two consequences. **Never drop brick 2 to make room**: its small R/yr is a *frequency*
artefact (12 trades/yr), it is the 2nd most efficient sleeve, and removing it costs
−1.2 pts/yr at equal risk. And **there is no slot scarcity** — adding beats swapping,
because the daily ceiling was set by one sleeve's own tail, not by the number of sleeves
(and after the cadence fix there is no daily-rule ceiling at all). So: admit a 5th brick
only if its **standalone Sharpe is at the top of this table**, and then *add* it rather
than swap.

## Caveats (why this is "frozen candidate", not "deployed")

1. **All in-sample** on candidate bricks — no genuine forward test yet.
2. Brick 1 t≈3.0 is **regime-selected** (regime-off t=1.69); brick 2 is a **thin**
   diversifier (~12 trades/yr, t=2.18); **brick 3 is the weak link** (live cadence
   +6.9 R/yr, t=2.43, ex-2020 t=1.30, negative in 2024 and 2025) and crypto
   **prop-tradability varies by firm** — verify your firm allows it before deploying;
   brick 4 is **long equity beta** (corr ~0 understates tail co-movement in a secular bear).
2b. **The whole book is now priced on the LIVE cadence** (recut 2026-07-31, in two
   passes). Both daily-bar bricks were affected by the same defect: the loop could **close
   and re-open inside one bar**, filling the new trade at that bar's **already-past open**.
   No once-per-bar driver can do that. Brick 4: **+5.6 → +4.8 R/yr**. Brick 3: **+17.2 →
   +6.9 R/yr** (t 5.25 → 2.43). Book: **+38.2 → +27.1 R/yr**. Decisive check — letting the
   engine re-enter intraday at the *honest* price (the barrier it just filled at,
   `cadence="live_reentry"`) gives **+5.5 R/yr, WORSE than not re-entering at all**. So the
   missing +10.3 R/yr was pure stale-price artefact, not a missed opportunity, and the
   deployed driver needs no change. `cadence="live"` is the tradeable book;
   `cadence="literal"` reproduces the historical runs and is used **only**
   by `verify` to prove the live signal math matches it. The edge is *stronger* on the live
   cadence (**t 4.77 → 5.16**, PF 1.99 → 2.21) — it is the R/yr that was optimistic, not
   the edge. Bricks 1–3 were already live-cadence.
3. Block-bootstrap **understates long crypto bear regimes** → real funded ruin likely
   a bit above the numbers above → argues for the conservative sizing end.
4. ✅ **The brick-3 cadence gap is CONFIRMED, fixed and re-cut** (was "suspected" earlier
   the same day). It cost **−10.3 R/yr** — by far the largest correction in the project.
   `verify` now guards it on every run (it asserts the live cadence re-opens inside a bar
   **0** times and prints the live-vs-literal R/yr gap). The favourable side predicted
   earlier did materialise: the worst day improved **−4.43 → −3.08 R**, so the −5% daily
   rule no longer binds at any tested sizing. Bricks 1 and 2 are structurally immune (one
   trade per session / per month), so all four are now on the live cadence.

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
