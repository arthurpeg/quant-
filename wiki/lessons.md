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
