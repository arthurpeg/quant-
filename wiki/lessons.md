---
type: lessons
updated: 2026-07-11
---

# Lessons — cross-cutting synthesis

What we've actually learned, distilled across experiments. Update this when the
big picture shifts; keep details in the experiment pages and link to them.

## The central finding so far

**Intraday direction is not predictable in this universe.** Across every angle
tried (raw price/vol features, cross-asset macro, seasonality, quote
microstructure), the classifier's AUC sits at **0.51–0.52** — i.e. ~nothing. All
apparent P&L came from directional drift (a bull-market long bias), and it dies
once realistic costs (0.03–0.05 R/trade) are applied. See
[[exp-001-v1-single-tf-direction]] and [[exp-002-v3-mt5-four-angles]].

## What DOES carry signal

- **Volatility is predictable; direction is not.** A volatility target reaches IC
  ≈ 0.47 / R² OOS ≈ 0.18. But ML beats naive persistence by only ~0.014 R² → it's
  useful for **risk management** (sizing, adaptive barriers, regime filter), **not
  as alpha**. See [[exp-002-v3-mt5-four-angles]].
- **Kaufman's noise law: right sign, wrong order of magnitude intraday.** *Trading
  Systems and Methods* ch.1/ch.20 claims that low noise (a high efficiency ratio) favours
  trend continuation and high noise favours reversion. Tested cleanly on 405 intraday
  cells — one trigger, same direction in both states, so drift cancels — the effect is
  **+0.010 R/trade with a median law-t of +0.26 and 28/45 asset medians positive
  (p = 0.135)**, against a **measured M15 friction of 0.079 R/trade**. So the law is
  ~8× too small to trade on this timeframe. His own evidence is *daily* bars *across*
  markets; it does not transfer to intraday bars *within* one. What does survive on US
  indices is a **move-QUALITY filter** (buy an efficient one-way break, not a whipsaw) —
  ER read at the signal bar, not as a regime read beforehand. `RESEARCH_LOG_KAUFMAN.md`.

## The strategic pivot — and its wall

- **Breadth is the lever.** [[information-coefficient-and-ir]]: IR ≈ IC · √(number
  of independent bets). A weak-but-real IC on *one* index is worthless; the same IC
  spread over hundreds of simultaneous [[cross-sectional-vs-directional]] bets can
  be a strategy. Confirmed empirically in [[exp-004-xsection-breadth-poc]]: the same
  data gives **IR +0.58** over ~138 weekly stock bets vs **IR ≈ 0** predicting one
  index. Breadth, not signal strength, is the differentiator.
- **But the prop-firm universe is too narrow for it.** [[exp-003-xsection-fx]] ran
  the same cross-sectional recipe on the ~11 tradable FX/metal names and found
  **nothing significant**: the ML ranker overfits (IC −0.029, Sharpe −1.29) and even
  plain momentum is insignificant (t = 1.19). ~11 correlated USD-leg instruments
  cannot supply the √N. **This is the current wall:** the mechanism that works needs
  many independent names; the [[prop-firm-universe]] doesn't offer them. The open
  strategic question is *how to get breadth inside the tradable universe* (widen with
  indices/energy? treat FX cross-section as diversification, not alpha?).
- **Corollary — ML needs breadth too.** On the wide equity panel ML/factors carry a
  small positive IC; on the narrow FX panel ML *destroys* value by overfitting. More
  regularization won't fix a universe that's simply too small.

## Methodological discipline (hard-won)

- **Anti-leakage is non-negotiable.** Causal features (`center=False`), rolling
  z-scores, temporal walk-forward split with an embargo of `TIMEOUT_BARS`. See
  [[leakage]] and [[walk-forward-embargo]].
- **Always compare ML to the dumb baseline.** Momentum sort, naive vol persistence,
  buy-and-hold drift. Several "wins" were the baseline in disguise.
- **Cost the strategy honestly.** Overestimate spread/slippage rather than tell
  yourself a story. Thin edges (E[R] +0.02…+0.05) do not survive round-trip cost.
- **Single-asset "wins" are usually artifacts.** The short-gold @1R win-rate of 62%
  was mono-asset overfitting, not an edge.
- **Measure the null before reading the number — the bracket alone pays.** `t > 0` is
  the wrong hypothesis for any stop/target system: a **long-only 1×ATR/2×ATR bracket
  entered at RANDOM on XAUUSD D1 returns t = +2.07**, so the nominal significance bar is
  cleared by no rule at all (NAS100 +1.45, US500 +1.58; USDCHF ≈+0.25 — and the
  both-directions null is ≈0 everywhere, so the premium is pure directional drift
  collected by a long bias). Across 38 (asset × tf) pairs this geometry baseline
  correlates **r = +0.485** with where a 5656-cell corpus sweep's t>2 hits actually land.
  **Always calibrate against random entries with the same bracket and holding
  distribution, per asset.** Corollary, same measurement: the H1 null is **negative on
  all 19 assets** while D1's is positive, which is why the same rules score 1.84× chance
  on D1 and 0.74× on H1 — friction, quantified. `scratchpad/tv_geometry.py`,
  [[Failed Ideas/ledger]], `RESEARCH_LOG_TV2.md`.
- **One null is not enough: the random-entry null can be beaten by TIMING, not direction.**
  The geometry null above randomises *which bars* fire, so it also randomises *when* — and
  a signal bar is systematically a cheaper moment to trade than an average one (a breakout
  bar carries a higher ATR relative to the spread, so the same bracket costs less in R).
  Measured: on the 2026-08-07 Kaufman intraday grid the random-entry null sits at
  **−0.5…−2.0** for exactly that reason, so "beats its null" there can mean nothing more
  than "pays less friction". Pair it with a **sign-permutation null** — the cell's OWN
  signal bars, signs shuffled at the same long fraction — which holds timing, volatility
  and friction fixed and tests the only thing a directional rule claims. It is a far harder
  bar, and often strongly *positive* where the other is negative (NAS100 **+1.24**, the
  drift a long-biased breakout set collects). `scratchpad/kauf_battery.py::null_sign`.
- **Calibrate the whole FUNNEL, not just the cell — run a placebo pipeline.** A matched
  null per cell is necessary and **not sufficient**: a screen that measures thousands of
  rules across a bracket grid and keeps each rule's best point has a false-positive rate
  no closed-form correction covers (the brackets are heavily correlated, so Bonferroni and
  a binomial test on "share of grid beating the null" are both invalid). **Measure it
  instead**: replace every rule with a RANDOM rule matched on signal count and direction
  mix, push it through the identical code path, and divide the candidate count through. On
  the 2026-08-03 gold sweep the funnel produced **68 candidates from the real corpus and
  54 from pure noise (1.25×)** — and the placebo *beat* the corpus at every statistical
  stage. A leak-free walk-forward (rule **and** bracket chosen out of sample) gave real
  median OOS excess **+0.05** vs placebo **+0.41**. Two corollaries: **(a)** any
  sub-period test must draw its null from **that sub-period's bars** — a whole-sample null
  against a half-sample t is biased toward the strategy; **(b)** re-picking a *parameter*
  out of sample is not a walk-forward if the *rule* was chosen on the full sample, and the
  difference is large (noise passes at 38%, not 5%). `scratchpad/gold_placebo.py`,
  `gold_truewf.py`, `RESEARCH_LOG_GOLD2.md`.
- **A candidate COUNT at the chance rate does not mean no individual is real — but the
  fix is more tests, not a lower bar, and it must be measured on a THIRD window.**
  (User challenge, 2026-08-05: *"si il y a une excellente strategie dans un echantillon de
  100 strategies pourries, si le nombre de bonnes strat ne depasse pas le nombre qu'on
  aurait eu par chance alors tu n'y pretes pas attention"* — correct, and it exposed real
  errors.) A placebo COUNT tests the *global* null; it cannot separate "all noise" from
  "99 noise + 1 gem", so triaging whole assets on it discards individuals never examined.
  **It did exactly that here:** gold was dropped at 0.93× on the count, yet showed the
  strongest ratio of the first four assets tested (**103 real vs 32 placebo = 3.22×**) once
  every rule went through nine out-of-sample tests. **Stacking tests appeared to work** —
  the ratio *rose* 1.42 → 1.62 as tests accumulated, and real survivors clustered
  (**N_eff 17.8 of 173**) where placebo survivors stayed independent (58.4 of 107).
  **⚠️ BUT THAT 1.62× WAS ITSELF ASSET-LEVEL SELECTION — MY OWN.** Those four assets were
  chosen because they had already looked interesting. Completing the universe reverses it:
  the other **15 assets give 145 real vs 247 placebo = 0.59×**, and **all 19 pooled = 318 vs
  354 = 0.90×, i.e. BELOW chance.** Per-asset ratios span 3.22× to 0.10×, exactly the
  dispersion 19 noisy draws produce around 0.90. **Deciding which assets to subject to a
  test, on the basis of earlier results, is the same error one level up — and it
  manufactured the entire effect.** Always complete the universe before reading a ratio.
  **BUT none of it is tradable, and the reason is a trap worth naming: selecting on a
  window and then scoring on that same window is circular.** A basket of **107 pure-noise
  strategies that passed the identical nine tests returned +5.29 R/yr at Sharpe 4.41** —
  a *better* Sharpe than the real basket (+6.60, 3.07). The decisive design uses **three**
  windows: **A** choose the bracket, **B** run the gauntlet and pick survivors, **C**
  measure — C never used to choose anything. On C: **real +1.292 R/yr vs placebo +1.265,
  an honest edge of +0.027**, with the placebo ahead on t, Sharpe and RoMaD. Both baskets
  fall ~80% (≈+6 → ≈+1.3 R/yr) the moment the measurement window is clean — **that drop is
  the selection premium, quantified.** `scratchpad/gold_gemhunt.py`, `gold_gauntlet.py`,
  `gold_basket.py`, `gold_threeway.py`.
- **A rejected strategy may be a rejected BRACKET.** Testing a published rule at its
  published SL/TP falsifies it *as published*, which is correct — but it conflates "is the
  entry informative" with "did the author pick a workable stop". Point-denominated stops
  ($0.30 on BTC), mid-line trailing exits, targets on a moving average and fixed-dollar
  brackets are bracket failures that never measure the entry at all; requiring a published
  hard SL+TP was discarding **1150 of 5759** Pine scripts outright. Compiling the entry
  alone and supplying a swept ATR bracket took distinct testable rules from **375 → 1405**.
  Worth doing — but on gold it changed no conclusion: median excess over the matched null
  was **+0.01** across 300k cells. Keep the tooling
  (`tv_transpile.compile_script(require_bracket=False)`); don't expect the space to be
  where the edge is hiding.
- **Data source dictates what's even possible — and whether a backtest is real.**
  Three data walls hit so far: (1) Yahoo indices = cash-session hours only; (2) MT5
  CFD ticks are bid/ask quotes (`last=0`) → no order flow; (3) **MetaQuotes-Demo tick
  quality is poor** → M1 intraday backtests on it are untrustworthy (noise drowns any
  tiny edge). Don't design an experiment the data can't support, and don't trust an
  intraday backtest run on a synthetic feed. Backtest on the feed you'll actually
  trade. See [[data-sources]], [[exp-005-mt5-intraday-vol-breakout]].
