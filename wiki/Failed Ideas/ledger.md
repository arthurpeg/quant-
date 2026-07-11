---
type: ledger
updated: 2026-07-11
---

# Failed Ideas — ledger

> **READ THIS BEFORE STARTING ANY NEW WORK.** This is the graveyard of ideas we
> have already tried and abandoned, each with the reason it failed. Its whole
> purpose is to stop us re-walking dead ends. If you're about to propose
> something, check it isn't already a row below. When you abandon an idea, add a
> row here (see [SCHEMA.md](../SCHEMA.md) §1g).

| Idea | When | Why it failed | Evidence / link |
|------|------|---------------|-----------------|
| Predict intraday **direction** of a single asset (1H triple-barrier) | 2026-07 | Classifier AUC ≈ 0.52; all P&L was directional drift, dies under 0.03–0.05 R/trade cost | [[exp-001-v1-single-tf-direction]] |
| **Cross-asset / macro** features (synthetic DXY, VIXY, UST) to predict direction | 2026-07 | Direction AUC 0.5034→0.5066 (negligible); actively *degraded* the vol target (R² 0.184→0.098) | [[exp-002-v3-mt5-four-angles]] |
| **Seasonality** features (month, hour-of-week, seasonal hourly vol) | 2026-07 | AUC +0.002 only; degraded vol target. Dated news calendar (the useful part) unavailable via MT5 API | [[exp-002-v3-mt5-four-angles]] |
| **Order flow** on MT5 CFD FX | 2026-07 | Impossible by construction: MT5 ticks are bid/ask quotes (`last=0`, `volume=0`), no real trades; no historical DOM/L2. Quote microstructure alone helps neither direction nor vol. Real order flow needs CME futures (6E/GC) | [[exp-002-v3-mt5-four-angles]], [[data-sources]] |
| Use the **volatility model as alpha** | 2026-07 | Vol IS predictable (IC≈0.47) but ML beats naive persistence by only ~0.014 R² → good for risk mgmt / sizing, not tradable edge | [[exp-002-v3-mt5-four-angles]] |
| Dropping **GBPUSD** from the universe (seen on synthetic data) | 2026-07 | Overfitting to synthetic quirks — GBPUSD is profitable on real data. Don't prune assets on synthetic backtests | quant-pipeline memory |
| Treat mono-asset **short-gold @1R (62% win)** as a real edge | 2026-07 | Single-asset artifact, not a repeatable edge; disappears out of that one series | quant-pipeline memory |
| Use broker **indices (^DJI etc.) from Yahoo** with the forex 24/5 calendar | 2026-07 | Yahoo indices only carry cash-session hours → incompatible with the forex market grid; would need a separate "index cash" session profile | [[data-sources]] |
| **ML ranker on the cross-section of ~11 prop-firm FX/metals** | 2026-07-11 | Universe too narrow: breadth ~11 correlated USD-leg names can't supply √N. ML overfits (IC −0.029, Sharpe net −1.29); even plain momentum is insignificant (t=1.19). Nothing significant net of cost | [[exp-003-xsection-fx]] |

_(Note the recurring theme: predicting **direction** of a single instrument is a
dead end here. The live threads deliberately avoid it — see [[lessons]].)_
