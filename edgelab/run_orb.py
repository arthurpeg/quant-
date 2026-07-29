"""Run the Opening Range Breakout across intraday assets, reported in R (SL = -1R).

Usage (from repo root):
    python -m edgelab.run_orb                      # canonical ORB, all M10 assets
    python -m edgelab.run_orb --symbols NAS100 US30
    python -m edgelab.run_orb --or-minutes 15 --tp-r 3 --direction long
    python -m edgelab.run_orb --grid               # small robustness sweep on NAS100
"""
from __future__ import annotations

import argparse

import pandas as pd

from edgelab.intraday.orb import POINT_SIZE, ORBParams, load_m10, run_orb
from edgelab.reports import save_json

ALL_SYMBOLS = ["NAS100", "US30", "XAUUSD", "XAGUSD", "SpotCrude", "NatGas"]


def _fmt(m: dict) -> str:
    if m.get("n_trades", 0) == 0:
        return "no trades"
    pf = m["profit_factor"]
    pf_s = "inf" if pf == float("inf") else f"{pf:.2f}"
    return (f"n={m['n_trades']:>4} | win {m['win_rate']:>5.1%} | "
            f"E[R] {m['expectancy_R']:>+6.3f} | totR {m['total_R']:>+7.1f} | "
            f"R/yr {m['R_per_year']:>+6.1f} | PF {pf_s:>5} | maxDD {m['max_dd_R']:>5.1f}R | "
            f"stop/tp/time {m['pct_stop']:.0%}/{m['pct_take']:.0%}/{m['pct_timeexit']:.0%}")


def run_all(symbols, params: ORBParams) -> dict:
    rows, results = [], {}
    for sym in symbols:
        try:
            df = load_m10(sym)
        except FileNotFoundError:
            print(f"{sym:9} (no M10 data)")
            continue
        res = run_orb(df, sym, params)
        results[sym] = res
        print(f"{sym:9} {_fmt(res.metrics)}")
        rows.append({"symbol": sym, **res.metrics})
    return {"rows": rows, "results": results}


def main() -> None:
    ap = argparse.ArgumentParser(description="Opening Range Breakout in R")
    ap.add_argument("--symbols", nargs="*", default=ALL_SYMBOLS)
    ap.add_argument("--or-minutes", type=int, default=30)
    ap.add_argument("--tp-r", type=float, default=2.0)
    ap.add_argument("--direction", choices=["both", "long", "short"], default="both")
    ap.add_argument("--session-open", default="09:30")
    ap.add_argument("--session-close", default="15:55")
    ap.add_argument("--slippage-points", type=float, default=1.0)
    ap.add_argument("--min-or-frac", type=float, default=0.0)
    ap.add_argument("--grid", action="store_true", help="robustness sweep on the first symbol")
    args = ap.parse_args()

    params = ORBParams(
        or_minutes=args.or_minutes, tp_R=args.tp_r, direction=args.direction,
        session_open=args.session_open, session_close=args.session_close,
        slippage_points=args.slippage_points, min_or_frac=args.min_or_frac,
    )

    print("=" * 100)
    print(f"Opening Range Breakout | OR={params.or_minutes}min @ {params.session_open} "
          f"{params.tz} | TP={params.tp_R}R | dir={params.direction} | "
          f"cost = 0.5*bar_spread + {params.slippage_points}pt/side | SL = -1R by construction")
    print("=" * 100)

    out = run_all(args.symbols, params)
    save_json([r for r in out["rows"]],
              "edgelab/reports/_out/orb_metrics.json")

    if args.grid:
        sym = args.symbols[0]
        df = load_m10(sym)
        print("\n" + "-" * 100)
        print(f"ROBUSTNESS SWEEP on {sym} (is the edge a plateau or a spike?)")
        print("-" * 100)
        for orm in (15, 30, 60):
            for tp in (1.0, 2.0, 3.0):
                for d in ("both", "long", "short"):
                    pr = ORBParams(or_minutes=orm, tp_R=tp, direction=d)
                    m = run_orb(df, sym, pr).metrics
                    if m.get("n_trades", 0):
                        print(f"OR{orm:>2} TP{tp:.0f}R {d:>5} | {_fmt(m)}")

    print("\n" + "=" * 100)
    print("R = entry-to-stop distance; a full stop-out = -1R (minus real cost).")
    print("NOTE (wiki/exp-005): demo M10 flatters breakouts. Tick-validated honest")
    print("estimate for the one real edge (NAS100 US-open breakout) is PF ~1.2-1.3.")
    print("=" * 100)


if __name__ == "__main__":
    main()
