# edgelab — research & validation framework for decorrelated trading edges

A pipeline to **discover, implement, and honestly validate** trading edges, then
assemble a portfolio of **decorrelated** edges that respects **prop-firm rules**.
Every trade carries a stop-loss, a take-profit and a time-exit; every backtest is
costed and walk-forward split; the portfolio step keeps only edges whose daily
returns are genuinely uncorrelated.

Built to the discipline in this repo's `wiki/` — the framework's job is to
*measure* whether an edge survives realistic cost and prop constraints, not to
flatter it. (Spoiler consistent with the wiki: naive single-asset direction edges
do **not** survive here — and the pipeline says so.)

## Layout

```
edgelab/
├── config.yaml         # EVERY tunable lives here
├── research/           # arXiv scraping + edge-candidate extraction
├── data/               # DataProvider interface + MT5 / Yahoo backends + cache
├── edges/              # BaseEdge + example edges (momentum, mean-rev, vol breakout)
├── backtest/           # event-driven engine, cost model, metrics, walk-forward
├── risk/               # SL/TP/time-exit rules + prop-firm constraints
├── portfolio/          # correlation matrix, decorrelated selection, combination
├── reports/            # metrics tables, JSON report, PNG charts
├── runner.py           # run an edge across the universe
├── run_pipeline.py     # end-to-end backtest/portfolio CLI
├── run_research.py     # arXiv research CLI
└── tests/              # unit tests (risk engine, drawdown, no-lookahead)
```

## Install

```bash
pip install -r edgelab/requirements.txt
```

`matplotlib`, `yfinance` and `pyarrow` are optional — the pipeline degrades
gracefully without them. The arXiv research uses only the Python stdlib.

## Run (from the repo root)

**End-to-end backtest + portfolio** (uses the MT5 daily cache, the honest feed):

```bash
python -m edgelab.run_pipeline
```

Minimal smoke test (1 edge × 1 symbol):

```bash
python -m edgelab.run_pipeline --minimal
```

Pick edges/symbols:

```bash
python -m edgelab.run_pipeline --edges vol_breakout zscore_mean_reversion --symbols XAUUSD US30
```

**arXiv research → edge candidates** (network, no API key, rate-limited):

```bash
python -m edgelab.run_research --top 15
```

**Tests:**

```bash
python -m pytest edgelab/tests -q
```

Outputs land in `edgelab/reports/_out/` (metrics CSV, `pipeline_report.json`,
equity + correlation PNGs) and `edgelab/research/_out/` (papers + candidate fiches).

## How it works, step by step

1. **Research (`research/`)** — `search_arxiv` queries `q-fin.*` with editable
   keyword sets, scores abstracts for exploitable-edge vocabulary, dedupes, and
   saves JSON/parquet. `extract_candidate` turns top papers into structured fiches
   that **strictly separate the article's (unverified) claims from our
   reformulation-to-test**. We never invent results.

2. **Data (`data/`)** — one `DataProvider` interface; swap `mt5_csv` ↔ `yahoo` in
   `config.yaml` without touching anything downstream. Every provider returns the
   same UTC-indexed OHLCV contract.

3. **Edges (`edges/`)** — a `BaseEdge` maps OHLCV → a signal in `{-1,0,+1}`. Three
   families ship as examples: time-series **momentum**, z-score **mean-reversion**,
   ATR **volatility breakout**. Edges are causal by construction.

4. **Risk (`risk/`)** — *mandatory on every trade*: stop-loss, take-profit and
   time-exit (ATR-based, configurable). The first-touched barrier wins; ties within
   a bar resolve **pessimistically** (stop first). `PropFirmRules` enforces
   max daily loss, max total drawdown, profit target, min trading days, and an
   optional consistency rule — and returns a **PASSED / FAILED / IN_PROGRESS** verdict.

5. **Backtest (`backtest/`)** — event-driven, **no lookahead**: a signal on bar `t`
   fills at the **open of bar `t+1`**. Spread + slippage charged both sides.
   Walk-forward split with an embargo for an honest out-of-sample read. Metrics:
   CAGR, Sharpe, Sortino, max drawdown, win rate, profit factor, expectancy,
   exposure, trade count.

6. **Portfolio (`portfolio/`)** — correlation of the edges' **daily returns**, a
   greedy **decorrelated** selection (`|rho| < corr_threshold`, maximising Sharpe),
   equal-weight or **risk-parity** combination, and a prop-firm re-check at book level.

## Extending

- **New edge:** subclass `BaseEdge`, implement `generate_signals`, register it in
  `edges/__init__.py::EDGE_REGISTRY`.
- **New data source:** subclass `DataProvider`, wire it into `data/factory.py`.
- **New rule / cost / barrier:** it's a value in `config.yaml`.

## Honest-validation notes (from the wiki)

- Backtest on the feed you'll actually trade — the default is the **MT5 daily
  cache**, and daily bars tolerate a weak feed far better than intraday.
- **Overestimate** cost rather than tell yourself a story; thin edges die on cost.
- **Single-asset "wins" are usually artifacts.** Breadth (many independent bets),
  not signal strength, is the lever — see `wiki/lessons.md`.
