---
type: experiment
id: exp-001
updated: 2026-07-11
status: done
verdict: no-edge
horizon: 1H direction (triple-barrier)
universe: FX majors + gold (real data via Yahoo cache)
code: [pipeline.py, labeling.py, backtest_real.py, backtest_exec.py]
---

# exp-001 — V1 single-timeframe direction baseline

**Hypothesis.** A gradient-boosted classifier on 1H causal features can predict
whether a long trade hits `+X R` (TP) before `-1 R` (SL) — i.e. trade direction —
well enough to beat costs.

**Setup.** Single asset, single timeframe (1H). Features from
`features/{momentum,volatility,volume,structure,temporal}`; labels from
[[triple-barrier]] (`labeling.py`); temporal [[walk-forward-embargo]] split.
Backtests in `backtest_real.py` (TP sweep) and `backtest_exec.py` (non-overlapping
long/short executable). Real data via Yahoo `data_cache/*.csv` — see
[[data-sources]]. Don't restate config here; see `config.py`.

**Result.** ML **AUC ≈ 0.52** → the model predicts almost nothing. All apparent
P&L traced to directional drift (persistent slight long bias in a bull market).
Executable non-overlapping edge is thin (E[R] +0.02…+0.05 R) and **dies under a
realistic 0.03–0.05 R/trade cost**.

**Verdict.** ❌ **No edge.** Direction of a single instrument at 1H is not
predictable from these features.

**Why it matters / next.** Motivated exp-002 (try fundamentally *different* kinds
of information) and, after that also failed for direction, the pivot to
[[cross-sectional-vs-directional]] ranking. Candidate next steps recorded at the
time: multi-timeframe, meta-labeling, costs inside the labeling.

**Links.** [[triple-barrier]], [[walk-forward-embargo]], [[leakage]],
[[exp-002-v3-mt5-four-angles]]. Ledger: single-asset direction is a dead end
([[ledger]]).
