---
type: reference
updated: 2026-07-11
---

# Codebase map — router

> Router page: links to the authoritative code; does not restate it. If a file's
> behavior changes, the truth is the file — update the one-liner, not a copy.

## Core pipeline
- `config.py` — single source of all "magic" parameters (whitelist, windows,
  barriers, sessions, seeds). [[prop-firm-universe]], [[triple-barrier]].
- `data_loader.py` — clean / resample / market-grid alignment.
- `calendar_utils.py` — forex market calendar (session masks, market grid, holidays).
- `labeling.py` — [[triple-barrier]] labels.
- `pipeline.py` — orchestration: validate → clean → features → label → (X, y);
  `walk_forward_split`, `dataset_hash`. [[walk-forward-embargo]], [[leakage]].
- `features/` — `momentum, volatility, volume, structure, temporal, seasonality,
  cross_asset, mtf`. Ordered build → stable column order → reproducible hash.

## Data loaders
- `fetch_data.py` — Yahoo (yfinance) → `data_cache/*.csv`. [[data-sources]]
- `mt5_loader.py` — MetaTrader5 → `data_cache_mt5/`. [[data-sources]]
- `fx_loader.py` — FX + metals panel for cross-section. [[exp-003-xsection-fx]]
- `equity_loader.py` — ~200-stock equity panel (survivorship-biased). [[exp-004-xsection-breadth-poc]]
- `macro_loader.py` — cross-asset/macro series (DXY synthetic, VIXY, UST). [[exp-002-v3-mt5-four-angles]]

## Backtests & experiments
- `backtest.py`, `backtest_v2.py`, `backtest_real.py`, `backtest_exec.py`,
  `backtest_mtf_base.py` — direction backtests. [[exp-001-v1-single-tf-direction]]
- `experiment_v3.py`, `experiment_flow.py` — the four-angle study. [[exp-002-v3-mt5-four-angles]]
- `orderflow.py` — quote-microstructure probe (order flow dead end). [[ledger]]
- `analyze_gold.py`, `analyze_gold_mt5.py` — gold single-asset analysis.
- `xsection_fx.py` — cross-sectional FX/metals. [[exp-003-xsection-fx]]
- `xsection_poc.py` — breadth POC. [[exp-004-xsection-breadth-poc]]

## External strategies (MQL5)
- `mql5/IntradayVolatilityBreakout.mq5` — MT5 Expert Advisor, intraday Nasdaq
  (NAS100) US-open ATR breakout + vol-regime filter. Runs in the MT5 Strategy Tester,
  not the Python pipeline. [[exp-005-mt5-intraday-vol-breakout]]
