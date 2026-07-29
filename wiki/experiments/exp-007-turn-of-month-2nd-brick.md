---
type: experiment
status: candidate
verdict: "⚠️ candidate 2nd brick"
updated: 2026-07-28
---

# exp-007 — Turn-of-month (gold): first credible 2nd brick

**Question.** After a systematic 1000-paper arXiv search, is there a signal that is
(a) implementable on our OHLCV prop data, (b) survives the [[log|Mesfin validation
gate]] (t>2, net-of-cost, cross-year), and (c) is **decorrelated** from the NAS100
breakout brick ([[exp-005-mt5-intraday-vol-breakout]])?

**Method.** Pulled 1000 q-fin papers (`edgelab.research.fetch_corpus`), triaged by
family + backtestability (`edgelab/research/triage.py` → only 178/1000 usable on our
data). Batteried the under-explored *decorrelated* families through
`edgelab/validation.py`: calendar/seasonality and pairs/cointegration.

**Result.**
- **Pairs / cointegration: all dead** (gold-silver, index pairs, gold-crude negative
  net of cost). → [[ledger]].
- **Calendar sweep is a multiple-testing trap** (54 tests, 2 nominal passes ≈ chance).
- **Turn-of-month on XAUUSD survives** and is pre-registered (a documented anomaly):
  long the last trading day + first 2 of each month, **mandatory ATR stop (SL = 1.5·ATR14
  = −1R)**, time-exit at the window end. R-based stats: **113 trades, E[R] +0.176 R,
  +19.9 R total (+2.1 R/yr), PF 1.68, win 55%, maxDD 3.4 R, 14% stopped / 86% time-exit,
  8/10 years positive**. Gate: **t = 2.18, corr +0.01** to the NAS brick.
  (An earlier %-clip stop gave an optimistic t=3.77; the proper ATR-stop R number is t=2.18.)
- **2-brick portfolio** (NAS ATR-breakout + XAU turn-of-month, equal-risk): the
  bricks are uncorrelated (corr +0.01), so combining them improves risk-adjusted
  return and prop **PASSES**. Exact combined Sharpe is accounting-sensitive (the
  turn-of-month brick's honest annualised Sharpe ≈ 0.7 via trade-frequency; a
  daily-grid combine flatters it). The point stands: the [[breadth]] engine turns
  1 → 2 genuinely decorrelated bricks — but brick #2 is a **thin, low-activity
  diversifier** (~12 trades/yr, +2 R/yr), not a workhorse.

**Verdict.** ⚠️ **Candidate** 2nd brick — the first credible one in the project.
Clears the gate and diversifies. **Not yet deployable:** monthly / low-activity
(~11 trades/yr), Pepperstone-demo data, and the exact window + stop are choices →
needs a genuine **out-of-sample forward test** before sizing real risk.

**Code.** `edgelab/edges/turn_of_month.py`, `edgelab/validation.py`,
`edgelab/research/triage.py`, `edgelab/intraday/atr_breakout.py` (brick #1).

**See also.** [[exp-005-mt5-intraday-vol-breakout]] (brick #1), [[breadth]],
[[information-coefficient-and-ir]], [[ledger]].
