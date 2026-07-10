"""
analyze_gold.py
===============
Bilan détaillé XAUUSD (or) : faut-il ne trader QUE l'or ?

Réutilise la préparation et le walk-forward exécutable (non-chevauchant) de backtest_exec,
mais capture les TIMESTAMPS des trades pour ventiler le rendement en R par ANNÉE et calculer
le drawdown maximum (en R) sur la courbe d'equity réelle.

On analyse plusieurs configs (short@1R = le "meilleur" suspect, long@2.5R, long@3R) afin de
juger la ROBUSTESSE : un edge concentré sur une seule année / un seul régime n'est pas un edge.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

import config
import backtest_exec as BE
from backtest_exec import prepare_asset, _folds, make_model, _proba_win, TP_CLS, TAKE_QUANTILE

SYMBOL = "XAUUSD"


def simulate_with_time(index: pd.DatetimeIndex, take: np.ndarray, r: np.ndarray,
                       bars: np.ndarray, start_pos: int) -> list:
    """Simulation non-chevauchante renvoyant (timestamp, R) de chaque trade."""
    n = len(take); i = 0; out = []
    while i < n:
        if take[i] and np.isfinite(r[i]):
            out.append((index[start_pos + i], float(r[i])))
            i += int(max(bars[i], 1))
        else:
            i += 1
    return out


def run_config(a: dict, side: int, tp: float) -> pd.DataFrame:
    """Trades (timestamp, R) pour un sens et un TP donnés, en walk-forward exécutable."""
    X = a["X"]; n = a["n"]; idx = X.index
    d = a["lab"][(side, tp)]
    trades = []
    for tr, te in _folds(n):
        ytr = d["y"][tr]
        if len(np.unique(ytr)) < 2:
            continue
        m = make_model(); m.fit(X.iloc[tr], ytr)
        classes = list(m.classes_)
        thr = float(np.quantile(_proba_win(m, X.iloc[tr], classes), TAKE_QUANTILE))
        pte = _proba_win(m, X.iloc[te], classes)
        trades += simulate_with_time(idx, pte >= thr, d["r"][te], d["bars"][te], te.start)
    df = pd.DataFrame(trades, columns=["time", "r"]).set_index("time").sort_index()
    return df


def max_drawdown_R(r: np.ndarray) -> float:
    if len(r) == 0:
        return 0.0
    eq = np.cumsum(r)
    return float((eq - np.maximum.accumulate(eq)).min())


def summarize(df: pd.DataFrame, label: str, cost: float = 0.0) -> dict:
    r = df["r"].to_numpy() - cost
    if len(r) == 0:
        return {"label": label, "n": 0}
    years = df.index.year
    per_year = {}
    for y in sorted(set(years)):
        ry = r[years == y]
        per_year[int(y)] = {
            "R": round(float(ry.sum()), 1), "n": int(len(ry)),
            "win": round(float((ry > 0).mean()) * 100, 1),
            "dd": round(max_drawdown_R(ry), 1),
        }
    g = r[r > 0].sum(); l = -r[r < 0].sum()
    span_days = (df.index[-1] - df.index[0]).days or 1
    return {
        "label": label, "cost": cost, "n": int(len(r)),
        "total_R": round(float(r.sum()), 1),
        "exp_R": round(float(r.mean()), 4),
        "win": round(float((r > 0).mean()) * 100, 1),
        "pf": round(float(g / l), 2) if l > 0 else float("inf"),
        "max_dd_R": round(max_drawdown_R(r), 1),
        "R_per_year": round(float(r.sum()) / (span_days / 365.25), 1),
        "per_year": per_year,
        "span": (str(df.index[0].date()), str(df.index[-1].date())),
    }


def run():
    import sys
    for s in (sys.stdout, sys.stderr):
        try: s.reconfigure(encoding="utf-8")
        except Exception: pass
    import pipeline; pipeline.set_seeds()

    print("═" * 82)
    print(" BILAN DÉTAILLÉ — XAUUSD (or) · faut-il trader l'or uniquement ?")
    print("═" * 82)
    a = prepare_asset(SYMBOL)
    print(f" Données : {a['n']} bougies 1H  [{a['span'][0].date()} → {a['span'][1].date()}]")
    print(f" Exécution non-chevauchante · SL=−1R · walk-forward {BE.N_FOLDS} folds\n")

    configs = [(-1, 1.0, "SHORT @1R (le 'meilleur' suspect)"),
               (+1, 2.5, "LONG @2.5R"),
               (+1, 3.0, "LONG @3R")]
    summaries = {}
    for side, tp, name in configs:
        df = run_config(a, side, tp)
        s0 = summarize(df, name, cost=0.0)
        s_cost = summarize(df, name, cost=0.04)      # coût réaliste or ~0.04R (spread large)
        summaries[name] = {"gross": s0, "net": s_cost, "trades": df}
        print("─" * 82)
        print(f" {name}")
        print(f"   Trades={s0['n']}  win={s0['win']}%  E[R]={s0['exp_R']:+}  "
              f"PF={s0['pf']}  R total={s0['total_R']:+}  maxDD={s0['max_dd_R']}R")
        print(f"   Rendement ≈ {s0['R_per_year']:+} R/an  (période {s0['span'][0]}→{s0['span'][1]})")
        print(f"   Ventilation par année (brut) :")
        for y, v in s0["per_year"].items():
            print(f"      {y} : {v['R']:+7} R   ({v['n']:4d} trades, win {v['win']}%, DD {v['dd']}R)")
        print(f"   Avec coût 0.04R/trade → R total {s_cost['total_R']:+} "
              f"({s_cost['R_per_year']:+} R/an), E[R] {s_cost['exp_R']:+}")

    print("═" * 82)
    return summaries


if __name__ == "__main__":
    run()
