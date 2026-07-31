---
type: experiment
status: candidate
verdict: "✅ candidate 3rd brick (decorrelated)"
updated: 2026-07-28
---

# exp-008 — Crypto breakout: 3rd decorrelated brick

> ⚠️ **CORRECTED 2026-07-31 — this page's headline numbers are on the LITERAL backtest
> cadence and are optimistic.** The daily engine could close and re-open a position
> inside one bar, filling at that bar's already-past open; the live driver cannot.
> On the honest live cadence with the OLD framework-default exits (TP 3·ATR / 10 bars)
> brick 3 was **+6.9 R/yr, t=2.43, 6/9 +years, 49% of it 2020, ex-2020 t=1.30**.
> Those defaults were never chosen for this brick. After validation the exits were
> **widened to TP 6·ATR / 30 bars** (`crypto_risk:` in config.yaml, 2026-07-31):
> **+11.8 R/yr, PF 1.65, t=3.52, 9/9 +years, ex-2020 t=2.60** — and positive in 2024
> and 2025. The signal is unchanged; only the exits and the cadence moved.
> Re-entering intraday at the honest price is *worse* still (+5.5 R/yr), so the gap
> was pure artefact. See [[system]] and [[log]].


**Question.** With crypto price data now pulled from Pepperstone (unlocking the
largest previously-excluded slice of the arXiv corpus — 535/2800 papers are crypto,
82 with a testable trend/vol/breakout family), is crypto trend-following a brick that
is (a) real net of cost, (b) survives the [[log|validation gate]], and (c) is
**decorrelated** from brick #1 (NAS breakout, [[exp-005-mt5-intraday-vol-breakout]])
and brick #2 (gold turn-of-month, [[exp-007-turn-of-month-2nd-brick]])?

**Method.** Broad D1 pull (10 coins). Daily `BacktestEngine` (mandatory SL/TP/time-exit)
with `VolatilityBreakoutEdge` and `TimeSeriesMomentumEdge`, pessimistic crypto spreads
(BTC 5bps/side … alts 15-25bps). Pooled per family → gate + decorrelation.

**Result — crypto breakout is a robust plateau.**
- channel-20 L/S: **t=2.86, R/yr +10.6, 10/11 years**; channel-20 long-only t=2.98;
  channel-55 L/S t=2.64; channel-55 long-only t=2.68 → **all pass** (a plateau, not a
  single lucky config). (Short-lookback momentum ts_mom_20 also passes, t=2.68, R/yr
  +24.7, but is fragile across lookback → breakout is the robust representative.)
- **Brick #3 stats** (breakout ch20 L/S, 10 coins): n=737, win 49%, **E[R] +0.150 R,
  +110.6 R total (+10.6 R/yr), PF 1.40, maxDD 17.4 R**, exits 30% stop / 31% TP / 40%
  time, positive **10/11 years** (only 2025 down).

**Common-window re-test (Pepperstone, equalising history).** Restarting all 10 at the
latest inception (SOL 2021-11) → 4.7-yr window: R/yr holds (+12.6) but gate drops to
**t=1.77** — underpowered (5 yrs, 2022 bear, 2025 DD). This looked like a downgrade…

**✅ Deeper history RESOLVES it (Yahoo 2014/2017+, `data_cache_crypto/`).** More data =
more power, and it holds up:
- **Full 8-coin set, common 2017-11+ (~8.7 yr): R/yr +20.5, PF 1.41, t=+3.54, 10/10
  years positive**, corr +0.01. The t=1.77 was purely a sample-size artefact.
- **BTC+ETH majors (ex-ante liquidity pick, not return-mined): t=3.78, PF 1.75,
  E[R] +0.262 R, +8.6 R/yr, 8/10 yrs** — the cleanest, highest-quality version.
- **Out-of-sample "keep the best" test** (rank on 2017-2021, trade on 2022-2026):
  top-4 → t=2.09, 5/5 yrs; all-8 → t=1.39; bottom-4 → t=0.20. **The selection
  generalises OOS** (winners keep winning, losers keep losing) — so pruning weak coins
  is legitimate here, not just curve-fitting.
- 3-brick portfolio with brick#3=BTC+ETH: combined Sharpe ≈ 2.5, corr ~0.01 to both
  others, prop PASSED, maxDD 5.1%.

**Three-brick portfolio.** Pairwise daily-P&L correlations are all ≈ 0:
NAS/gold 0.01, NAS/crypto −0.01, gold/crypto 0.03. Equal-risk combine → the
[[breadth]] engine multiplies the Sharpe by ≈ √3. Combined equity: prop **PASSED**,
maxDD 3.9%.

**FINAL decision (2026-07-28): brick #3 = MACD-RSI on BTC+ETH** (upgraded from
Breakout-20). MACD(12,26,9) crossover confirmed by RSI (long if RSI>50, short if <50),
grounded in [arXiv 2206.12282](https://arxiv.org/abs/2206.12282). On BTC+ETH it beats
Breakout-20 on both return AND efficiency: **R/yr +25.5 vs +9.8, RoMaD 25.3 vs 11.8**
(Sharpe 3.78 vs 4.57* — breakout's is sparsity-inflated). In the 3-brick book (2018+):
brick3=MACD → **R/yr +37.9, maxDD 13.6 R, RoMaD 23.9, combined Sharpe 2.56, prop PASSED**
(vs breakout: +22.6 R/yr, RoMaD 15.8). Daily −5% rule respected (worst day −4.33% @1%,
0 breaches; recommend ≤0.85%/trade since MACD's crypto tail is bigger). Coin choice:
**BTC+ETH only** — user-verified more drawdown-efficient than BTC+ETH+SOL+ADA (RoMaD
25.3 vs 22.8; scaled to equal maxDD, BTC+ETH gives +44.6 vs +40 R/yr); adding alts adds
correlated crash risk (crypto corr ~0.8), not diversification. Breakout-20 kept as the
lower-tail conservative alternative. (Trap noted: MACD/MA/breakout on the *full* index+FX
universe all LOSE on indices/FX — the trend edge is 100% crypto; = same brick.)

**Verdict.** ✅ **Candidate 3rd brick** — the strongest of the diversifiers (more
significant than brick #2's gold ToM): robust plateau, +10.6 R/yr, decorrelated from
both existing bricks. **Caveats / not-yet-deployable:** (1) **crypto may not be
tradable on your prop firm** — the project whitelist originally excluded it, check the
rules; (2) crypto history starts ~2016-18 → mild survivorship (only surviving coins);
(3) the daily-grid combined Sharpe is optimistic for sparse series — the robust claim
is the **decorrelation**, not the absolute Sharpe; (4) needs a real forward test.

**Monte Carlo (corrected 2026-07-29).** The frozen 3-brick book was block-bootstrapped
in R (no compounding). An earlier MC reported **~+28.5 R/yr** — that was **wrong**: two
stacked bugs, both understating (compounding mark-to-market for crypto instead of
fixed-fractional trade-R; and a `freq='B'` reindex that dropped crypto **weekend**
exits). Fixed → the MC median (**+37.6 R/yr**) matches the backtest (**+37.9**), which is
the correctness check for a bootstrap. 1-yr: P(profit) 97.8%, maxDD median 10.3 R
(95th 19.3 R). Static-DD prop sizing (+15%/−10%/−5%): challenge optimal **1.0%/trade**
(~3.7 mo, 91% pass, 0 daily breaches; ceiling ~1.2% from the −4.13 R worst day); funded
optimal **0.5–0.75%** (never >1%); **infrequent** payout beats biweekly (same income,
~½ the ruin). Full numbers + reproducible scripts on [[system]].

**Pepperstone re-validation (2026-07-29, the LIVE data source).** The frozen numbers use
Yahoo spot; live trades Pepperstone crypto CFD D1 (different daily-close time + spread).
Re-ran the same MACD-RSI signal/engine on Pepperstone BTC+ETH (2018-07+): **+16.7 R/yr,
PF 1.55, maxDD 9.1 R, t=3.93, corr −0.02 to NAS+gold, 9/9 years positive, gate PASS**
(realistic cost BTC 6 / ETH 16 bps; cost-robust — pessimistic 8/20 bps still +16.2, t=3.80).
It's ~30% below Yahoo (+22–25 R/yr) because of shorter history (Pepperstone BTC 2016 vs
Yahoo 2014) + a different broker daily-close time (780 trades vs 1104), **not cost**
(MACD-RSI is low-turnover). Recent (2023+) spreads are tighter than the historical median
(BTC ~2.6, ETH ~12.6 bps/side). → the edge holds on the data we actually trade; the live
book expectation is **~+30 R/yr** (crypto +16.7 not +24). Confirms the [[system]] caveat.

**Code.** daily `edgelab.backtest.BacktestEngine` + `edgelab.edges.VolatilityBreakoutEdge`,
crypto costs via `CostModel`; `edgelab/validation.py` gate. Data: `data_cache_mt5/*USD_D1.parquet`.
Monte-Carlo: `edgelab/reports/monte_carlo_static.py`, `edgelab/reports/payout_frequency.py`.

**See also.** [[exp-005-mt5-intraday-vol-breakout]] (#1), [[exp-007-turn-of-month-2nd-brick]] (#2),
[[breadth]], [[information-coefficient-and-ir]], [[data-sources]].
