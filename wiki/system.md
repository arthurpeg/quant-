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
| 3 | **MACD(12,26,9)+RSI** ([arXiv 2206.12282](https://arxiv.org/abs/2206.12282)), exits TP 6·ATR / 30 bars (`crypto_risk:`) | BTC+ETH (D1) | crypto trend | daily `BacktestEngine(cadence='live')` + `macd_rsi`; data `data_cache_mt5/` (Pepperstone) | **+11.8 R/yr, PF 1.65, t=3.52** |
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
| **Total (Pepperstone + live cadence, canonical)** | — | **+258 R (+32.0 R/yr)**; NAS +12.9 + gold +2.5 + crypto +11.8 + IBS +4.8 |
| maxDD / RoMaD / Sharpe | — | **14.3 R / 2.24 / 2.57** |
| Profit factor (pooled trades) | — | **1.44** (1446 trades, 53% win); per brick NAS 1.27 / gold 1.86 / crypto 1.65 / IBS 2.21 |
| Activity | — | **~180 trades/yr**: NAS ~95, crypto ~35, IBS ~35, gold 12 |
| worst day | −4.15 R | **−3.07 R** (crypto no longer books 4 same-day stops) |
| MC median R/yr, P(profit) | — | **+31.6, 97.2%** |
| MC 5th-pct year, median maxDD | — | **+4.3 R, 9.5 R** |

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

**4-brick, 1-year distribution (40k sims, blocks of 14 d):** P(profitable year) = **97.2%**,
mean **+31.8 R** (historical +32.0).

| Pct | annual R | maxDD R |
|-----|---------:|--------:|
| 5th | +4.3 | 5.4 |
| 25th | +20.4 | 7.4 |
| **50th** | **+31.6** | **9.5** |
| 75th | +43.2 | 12.2 |
| 95th | +59.7 | 18.0 |

maxDD tail: 99th pct 23.6 R, worst 41.6 R.

## Prop sizing — firm with STATIC drawdown (target +15% / total −10% / daily −5%)

**No daily-rule ceiling any more:** the worst historical day is **−3.07 R** (the crypto
brick no longer books four same-day stops), so the −5% daily rule is not breached at any
sizing tested up to 1.5%. The binding limit is now the **−10% static floor**.

**Challenge (time-to-pass, 4-brick):**
- **0.75%/trade = best pass rate** — **95.8%** in ~6.4 months; 1.00% = **92.3%** in **~4.5 months**.
- **0%** daily-rule breaches at every sizing; failures are now all total-DD.
- 1.25-1.5% still passes 84-88% but fails DD 12-16% — the trade-off is speed vs ruin.

**Funded (static −10% floor, monthly payout resets balance to initial):**
- **0.50%/trade** → ~**16.7%/yr** withdrawn, **1.8%** ruin/yr (keep-the-account choice).
- 0.75% → ~24.6%/yr, ~12% ruin/yr.
- **Never above 1%** — E[withdrawn] plateaus at 35–38% while ruin explodes past 47%.
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
- **Brick 3, after the exit fix, is healthy again** (but the old "strongest brick" claim
  stays withdrawn). With the framework-default exits it was 49% 2020 and **ex-2020
  t=1.30**, negative in 2024 and 2025. With the **validated** exits (TP 6·ATR / 30 bars)
  it is **+11.8 R/yr, t=3.52, 9/9 positive years**, ex-2020 t=2.60, and positive in 2024
  (+3.0) and 2025 (+0.8). The fragility was in the arbitrary defaults, not the signal.
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
sized to its own binding prop ceiling — the **−10% static floor**, since after the cadence
fix the daily rule never binds). Re-run 2026-07-31 on the final book:

| Config | R/yr | maxDD | RoMaD | **%/yr at equal risk** |
|---|---|---|---|---|
| **A — the book (4 bricks)** | +32.0 | 14.3 R | 2.24 | **22.4%** |
| B — A − gold | +29.5 | 13.6 | 2.17 | 21.7 (−0.6) |
| C — A − gold **+ GER40** | +38.1 | 20.5 | 1.86 | 18.6 (**−3.8**) |
| D — A **+ GER40** (add) | +40.5 | 21.1 | 1.93 | 19.3 (**−3.1**) |
| G — A − NAS **+ GER40** | +27.6 | 19.2 | 1.43 | 14.3 (**−8.0**) |
| H — A − IBS **+ GER40** | +35.8 | 22.4 | 1.60 | 16.0 (**−6.4**) |
| **E — A + IBS US500** | +34.9 | 14.2 | 2.46 | **24.6 (+2.3)** |
| F — A + an IBS-calibre independent sleeve | +36.8 | 13.5 | 2.75 | **27.5 (+5.1)** |

**Every GER40 configuration loses at equal risk**, and swapping is worse than adding. The
cause is not correlation (|corr| ≤ 0.02 to all four) but its **path**: GER40's standalone
maxDD is **22.6 R for +8.6 R/yr → RoMaD 0.38**, i.e. it carries more drawdown on its own
than the entire book (14.3 R). Note config G has the *highest* Sharpe of the lot (2.68)
yet the worst %/yr — Sharpe measures daily vol, RoMaD measures the path, and GER40's
losses cluster. **On a static-DD prop account the path is what you are paid on.**

Standalone RoMaD is the cleanest admission test: IBS **1.59**, crypto 0.95, NAS 0.79,
gold 0.73, **GER40 0.38**.

| Sleeve | R/yr | daily vol | **standalone Sharpe** |
|---|---|---|---|
| IBS (b4) | +4.8 | 0.442 | **4.84** |
| gold ToM (b2) | +2.5 | 0.868 | **3.83** |
| crypto (b3) | +11.8 | 1.774 | 3.36 |
| NAS ORB (b1) | +12.9 | 1.238 | 1.71 |
| *GER40 (candidate)* | *+8.6* | *1.368* | *1.63* |

Three consequences. **Never drop brick 2 to make room** — its small R/yr is a *frequency*
artefact (12 trades/yr) and removing it costs −0.6 pts/yr at equal risk. **There is no
slot scarcity**: adding always beats swapping, and after the cadence fix there is no
daily-rule ceiling at all. And **GER40 is closed** — it lost on the old book (−1.4 pts)
and loses by more on the better one (−3.1), because the bar rose with it.

**The open candidate is [[exp-009-ibs-reversion-4th-brick|IBS on US500]]** (config E,
**+2.3 pts/yr at equal risk**, RoMaD +0.23, Sharpe +0.11, maxDD flat) — the only real
strategy tested that improves the book. It is already coded (`run_ibs('US500')`). It has
NOT had the validation battery (exp-009 flags it as weaker: split-half early t=1.45,
cost-fragile past 4pt) and it is correlated to brick 4 by construction. Validate before
adding. Admission test: **standalone RoMaD near the top of the table**, then *add*.

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
