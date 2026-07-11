---
type: experiment
id: exp-002
updated: 2026-07-11
status: done
verdict: risk-mgmt-only
horizon: H4, 2018+
universe: 5 assets (MT5), walk-forward
code: [experiment_v3.py, experiment_flow.py, macro_loader.py, orderflow.py, features/cross_asset.py, features/seasonality.py]
---

# exp-002 — V3 MT5: four "new nature of information" angles

**Hypothesis.** If plain price features can't predict direction ([[exp-001]]),
maybe a *fundamentally different* kind of information can. Test four angles on H4
MT5 data (2018+, 5 assets, walk-forward): volatility target, cross-asset/macro,
seasonality, order flow.

**Setup.** H4 bars from MT5 cache (see [[data-sources]]). Targets: direction (AUC)
and volatility (Spearman IC, R² OOS). Baselines: naive vol persistence, plain
direction. Code: `experiment_v3.py`, `macro_loader.py`, `orderflow.py`,
`features/cross_asset.py`, `features/seasonality.py`.

**Result — angle by angle.**
- **Volatility target — the only thing that works.** IC Spearman ≈ **0.47**, R² OOS
  ≈ **0.18** (vs direction AUC ≈ 0.51). BUT ML beats naive persistence by only
  **+0.014 R²**.
- **Cross-asset / macro** (synthetic DXY per ICE formula, VIXY, UST): direction AUC
  0.5034→0.5066 (negligible); **degraded** vol (R² 0.184→0.098).
- **Seasonality** (month / hour-of-week / seasonal hourly vol): AUC +0.002;
  degraded vol. The genuinely useful piece — a **dated news calendar** — is not
  available through the MT5 API.
- **Order flow — impossible on MT5 CFD FX.** Ticks are bid/ask **quotes**
  (`last=0`, `volume=0`, no transactions); no historical DOM/L2 (live only). Only
  quote microstructure is extractable, and it helps neither direction nor vol. Real
  order flow would need **CME futures (6E/GC)** with trade prints + L2.

**Verdict.** ⚠️ **Risk-management only.** Direction stays unpredictable (AUC ≤ 0.51)
across all four angles. Volatility is predictable but not tradable as alpha — use it
for sizing, adaptive barriers, and regime filtering. **Do not re-attempt direction
without a fundamentally new data source.**

**Why it matters / next.** Closes the "just add exotic features" line of attack and
forces the strategic pivot to [[breadth]] / [[cross-sectional-vs-directional]]
(exp-003, exp-004).

**Links.** [[exp-001-v1-single-tf-direction]], [[data-sources]], [[lessons]].
Four ledger rows come from this experiment ([[ledger]]).
