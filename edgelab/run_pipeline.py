"""End-to-end pipeline CLI.

Runs the example edges over the prop universe, computes metrics + prop verdicts,
does a walk-forward OOS check, builds a decorrelated portfolio, re-checks prop
rules at book level, and writes reports.

Usage (from repo root):
    python -m edgelab.run_pipeline               # all edges, full report
    python -m edgelab.run_pipeline --edges ts_momentum --symbols EURUSD
    python -m edgelab.run_pipeline --minimal     # 1 edge x 1 symbol smoke test
"""
from __future__ import annotations

import argparse
import logging

import pandas as pd

from edgelab.backtest.engine import BacktestEngine
from edgelab.backtest.walkforward import walk_forward_report
from edgelab.config import load_config
from edgelab.data import get_provider
from edgelab.edges import EDGE_REGISTRY
from edgelab.portfolio.combine import combine_returns
from edgelab.portfolio.correlation import correlation_matrix
from edgelab.portfolio.selection import select_decorrelated
from edgelab.reports import (
    format_metrics_line, plot_correlation, plot_equity_curves,
    save_json, save_metrics_table,
)
from edgelab.risk.propfirm import PropFirmRules, evaluate_equity_curve
from edgelab.runner import run_edge_over_universe


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.INFO if verbose else logging.WARNING,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )


def build_edges(names: list[str]):
    edges = []
    for n in names:
        if n not in EDGE_REGISTRY:
            raise SystemExit(f"Unknown edge {n!r}. Known: {sorted(EDGE_REGISTRY)}")
        edges.append(EDGE_REGISTRY[n]())
    return edges


def main() -> None:
    ap = argparse.ArgumentParser(description="edgelab end-to-end pipeline")
    ap.add_argument("--config", default=None, help="path to config.yaml")
    ap.add_argument("--edges", nargs="*", default=None, help="edge names (default: all)")
    ap.add_argument("--symbols", nargs="*", default=None, help="symbols (default: config universe)")
    ap.add_argument("--minimal", action="store_true", help="1 edge x 1 symbol smoke test")
    ap.add_argument("--no-plots", action="store_true", help="skip PNG charts")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    _setup_logging(args.verbose)
    cfg = load_config(args.config)

    provider = get_provider(cfg)
    engine = BacktestEngine(cfg)
    universe = args.symbols or cfg.data["universe"]

    if args.minimal:
        edge_names = ["ts_momentum"]
        universe = universe[:1]
    else:
        edge_names = args.edges or list(EDGE_REGISTRY.keys())
    edges = build_edges(edge_names)

    reports_dir = cfg.resolve_path(cfg["reports_dir"])

    print("=" * 90)
    print(f"edgelab pipeline | provider={provider.name} tf={cfg.data['timeframe']} "
          f"| {len(edges)} edge(s) x {len(universe)} symbol(s)")
    print(f"universe: {', '.join(universe)}")
    print("=" * 90)

    # ---- Step: run each edge over the universe -----------------------------
    edge_runs = {}
    returns_by_edge: dict[str, pd.Series] = {}
    sharpe_by_edge: dict[str, float] = {}
    metric_rows = []
    equity_curves = {}

    for edge in edges:
        run = run_edge_over_universe(cfg, provider, engine, edge, universe)
        if run.returns.empty:
            print(f"[skip] {edge.name}: no results")
            continue
        edge_runs[edge.name] = run
        returns_by_edge[edge.name] = run.returns
        sharpe_by_edge[edge.name] = run.metrics.get("sharpe", 0.0)
        equity_curves[edge.name] = run.equity

        print("\n" + format_metrics_line(f"[{run.family}] {edge.name}", run.metrics,
                                         run.prop["verdict"]))
        print(f"    prop: {run.prop['reason']}")

        # Walk-forward OOS on the first symbol (per-symbol OOS stability probe).
        wf_symbol = universe[0]
        try:
            data = provider.get_bars(wf_symbol, cfg.data["timeframe"],
                                     cfg.data.get("start"), cfg.data.get("end"))
            sig = edge.generate_signals(data)
            wf = walk_forward_report(engine, data, sig, wf_symbol, edge.name, cfg)
            run.walk_forward = wf
            pooled = wf.get("pooled_oos", {})
            if pooled:
                print(f"    walk-forward OOS ({wf_symbol}): pooled Sharpe "
                      f"{pooled.get('sharpe', 0):.2f}, {len(wf['folds'])} folds")
        except Exception as exc:  # pragma: no cover
            logging.warning("walk-forward failed for %s: %s", edge.name, exc)

        metric_rows.append({"edge": edge.name, "family": run.family,
                            **run.metrics, "prop_verdict": run.prop["verdict"]})

    if not returns_by_edge:
        raise SystemExit("No edge produced results — check data availability.")

    # ---- Step: correlation + decorrelated selection ------------------------
    corr = correlation_matrix(returns_by_edge)
    print("\n" + "-" * 90)
    print("Daily-return correlation between edges:")
    print(corr.round(3).to_string())

    selected, _ = select_decorrelated(
        returns_by_edge, sharpe_by_edge,
        corr_threshold=float(cfg.portfolio["corr_threshold"]),
        min_sharpe=float(cfg.portfolio["min_sharpe_to_admit"]),
    )
    print(f"\nDecorrelated selection (|rho| < {cfg.portfolio['corr_threshold']}, "
          f"Sharpe >= {cfg.portfolio['min_sharpe_to_admit']}): "
          f"{selected or '(none cleared the bar)'}")

    # ---- Step: combine + prop re-check at portfolio level ------------------
    portfolio_summary = {}
    if selected:
        port = combine_returns(returns_by_edge, selected,
                               method=str(cfg.portfolio["weighting"]),
                               initial_balance=float(cfg.propfirm["initial_balance"]))
        from edgelab.backtest.metrics import compute_metrics
        pm = compute_metrics(port.equity, port.returns, pd.DataFrame(),
                             int(cfg["trading_days_per_year"]))
        prop = evaluate_equity_curve(PropFirmRules.from_config(cfg.propfirm), port.equity)
        equity_curves["PORTFOLIO"] = port.equity
        print("\n" + "-" * 90)
        print(f"PORTFOLIO ({port.method}, weights="
              f"{ {k: round(v,3) for k,v in port.weights.items()} })")
        print(format_metrics_line("  combined", pm, prop["verdict"]))
        print(f"    prop: {prop['reason']}")
        portfolio_summary = {"weights": port.weights, "metrics": pm, "prop": prop,
                             "selected": selected}
    else:
        print("\nNo portfolio built (no edges cleared the admission bar).")

    # ---- Step: persist reports --------------------------------------------
    save_metrics_table(metric_rows, reports_dir / "edge_metrics.csv")
    save_json({
        "config_path": str(cfg.path),
        "provider": provider.name,
        "universe": universe,
        "edges": {n: {"metrics": r.metrics, "prop": r.prop,
                      "walk_forward": r.walk_forward,
                      "per_symbol_metrics": r.per_symbol_metrics}
                  for n, r in edge_runs.items()},
        "correlation": corr.round(4).to_dict(),
        "portfolio": portfolio_summary,
    }, reports_dir / "pipeline_report.json")

    if not args.no_plots:
        plot_equity_curves(equity_curves, reports_dir / "equity_curves.png")
        plot_correlation(corr, reports_dir / "correlation.png")

    print("\n" + "=" * 90)
    print(f"Reports written to {reports_dir}")
    print("=" * 90)


if __name__ == "__main__":
    main()
