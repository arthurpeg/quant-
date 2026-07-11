---
type: reference
updated: 2026-07-11
---

# Data sources — router

> Router page: links to the raw caches and their loaders; does not restate their
> contents. The caches are immutable source-of-truth data.

## Sources
- **Yahoo (yfinance)** → `data_cache/*.csv`, built by `fetch_data.py`.
  FX majors + gold (GC=F). **FX volume = 0** on Yahoo → volume features OFF.
  Indices (^DJI…) carry **cash-session hours only** → incompatible with the forex
  24/5 calendar (would need an "index cash" session profile). [[prop-firm-universe]]
- **MetaTrader5** → `data_cache_mt5/`, built by `mt5_loader.py`. H4 bars 2018+.
  ⚠️ CFD FX ticks are **bid/ask quotes** (`last=0`, `volume=0`); no real trades, no
  historical DOM/L2 → order flow impossible ([[exp-002-v3-mt5-four-angles]],
  [[ledger]]). `data_cache_mt5/spreads.json` holds per-asset spreads used for costs.
- **FX + metals panel** → `data_cache_mt5/fx_panel.parquet` + `fx_*.csv`, built by
  `fx_loader.py`. ~20 USD-oriented pairs + metals. **No historical swap/carry.**
  [[exp-003-xsection-fx]]
- **Equity panel** → `data_cache_mt5/equity_panel.parquet`, built by
  `equity_loader.py`. ~200 stocks. ⚠️ **Survivorship bias present** — POC-only, not
  prop-tradable. [[exp-004-xsection-breadth-poc]]

## ⚠️ MT5 data QUALITY (not just availability)
- **MetaQuotes-Demo is a weak feed** — synthetic/aggregated ticks, unrealistic
  spreads, gaps. For **minute-level intraday** strategies this alone can invalidate a
  backtest: the tiny/zero edge is drowned by data noise (can hide a real edge OR
  manufacture a fake one). Confirmed by user 2026-07-12 ([[exp-005-mt5-intraday-vol-breakout]]).
- **Rule:** backtest on the feed you will actually **trade** (your real prop-firm's
  MT5 server), or on research-grade data (CME futures / a tick provider), not on
  MetaQuotes-Demo. Check the Strategy Tester "modelling quality" %.
- Higher timeframes (H4/D1) tolerate weak feeds far better than M1 — the project's
  daily/H4 FX work is less exposed than an M1 index breakout.

## Cross-cutting caveats
- Never ffill across weekends / holidays / maintenance gaps (forex is Sun 22:00 →
  Fri 22:00 UTC). Enforced via `calendar_utils.py`.
- Tick volume is a **proxy**, not real volume, for FX/CFD.
- Repro data pins are in `requirements.txt`; local env runs newer libs (see
  project memory).
