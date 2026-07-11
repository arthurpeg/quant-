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
- **Data source dictates what's even possible — and whether a backtest is real.**
  Three data walls hit so far: (1) Yahoo indices = cash-session hours only; (2) MT5
  CFD ticks are bid/ask quotes (`last=0`) → no order flow; (3) **MetaQuotes-Demo tick
  quality is poor** → M1 intraday backtests on it are untrustworthy (noise drowns any
  tiny edge). Don't design an experiment the data can't support, and don't trust an
  intraday backtest run on a synthetic feed. Backtest on the feed you'll actually
  trade. See [[data-sources]], [[exp-005-mt5-intraday-vol-breakout]].
