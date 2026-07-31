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

## edgelab framework (isolated package, 2026-07-28)
- `edgelab/` — a self-contained **research + validation framework** (distinct from
  the flat research scripts above). Subpackages: `research/` (arXiv q-fin scraper +
  candidate-edge fiches), `data/` (`DataProvider` ABC → MT5-csv / Yahoo, swappable),
  `edges/` (`BaseEdge` + momentum / mean-reversion / vol-breakout), `backtest/`
  (event-driven, no-lookahead, costs, walk-forward, metrics), `risk/` (mandatory
  SL/TP/time-exit + `PropFirmRules`), `portfolio/` (decorrelated selection + combine).
  Run: `python -m edgelab.run_pipeline`, `python -m edgelab.run_research`,
  `python -m pytest edgelab/tests`. All params in `edgelab/config.yaml`; see
  `edgelab/README.md`. Isolated to avoid shadowing the root `backtest.py`.
  [[prop-firm-universe]], [[cross-sectional-vs-directional]]
- `edgelab/edges/ibs.py` — brick 4: IBS reversion (`run_ibs`, `ibs_daily_R`), R-based with
  the mandatory ATR stop. [[exp-009-ibs-reversion-4th-brick]]
- `edgelab/reports/monte_carlo_static.py` — canonical Monte Carlo of the frozen
  **4-brick** book (no compounding, fixed-fractional trade-R on a calendar index):
  `build_daily_R()` (the book's daily-R series) + `simulate()` (block bootstrap) feed both
  the CLI printout and the HTML reports — 1-yr R distribution + static-DD challenge
  time-to-pass + funded optimal sizing. [[system]]
- `edgelab/reports/build_reports.py` — **rebuilds both HTML reports** from one run
  (`portfolio_backtest.html` + `monte_carlo.html`, plus `_out/` and root `RAPPORT_*.html`
  copies). Run after adding or changing a brick. [[system]]
- `edgelab/reports/payout_frequency.py` — funded payout-cadence study (biweekly vs
  monthly vs quarterly; buffer policy). Reuses the same corrected R series. [[system]]

## edgelab/live — live / forward-test runner (2026-07-29)
- `edgelab/live/` — one Python process runs the frozen **4-brick** book on MT5/Pepperstone
  (brick 4 wired 2026-07-31, magic 105), **dry-run by default** (pulls bars, logs would-be
  orders, paper-tallies R). Modules:
  `signals.py` (pure decisions reusing the exact backtest math), `broker.py` (MT5 conn +
  order routing + dry-run paper book), `risk.py` (1R sizing + shared static-DD prop gate),
  `strategies.py` (per-brick drivers), `runner.py` (event loop: `python -m edgelab.live.runner`),
  `verify.py` (proves live==backtest: brick1 830/830, brick3 identical, brick2 ~98%,
  brick4 314/314 trades + a printed live-vs-backtest R gap),
  `config_live.yaml` (symbol map + `live_trading` flag + risk%). See `edgelab/live/README.md`.
  Resilience: runner self-heals dropped MT5 conn (health-check + reconnect), rotating
  `_out/runner.log`, exit 42 on blown account; single-instance mutex in `runner.py`.
  `run_forever.ps1` = supervisor (restart on crash, resolves the real python not the Store
  alias, STOP-file to halt); `install_task.ps1` = auto-start at logon; `summary.py` =
  one-command forward-test readout of `_out/trades.csv` (R total/per-brick/per-month). [[system]]

## External strategies (MQL5)
- `mql5/IntradayVolatilityBreakout.mq5` — MT5 Expert Advisor, intraday Nasdaq
  (NAS100) US-open ATR breakout + vol-regime filter. Runs in the MT5 Strategy Tester,
  not the Python pipeline. [[exp-005-mt5-intraday-vol-breakout]]
