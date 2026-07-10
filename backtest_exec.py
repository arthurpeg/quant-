"""
backtest_exec.py
================
Backtest EXÉCUTABLE sur données réelles : contrairement à backtest_real.py (qui évalue un
signal à chaque bougie → positions chevauchantes = mesure de qualité de signal, pas un P&L
réaliste), ici on simule une exécution réelle :

  • UNE position à la fois par actif. Tant qu'un trade est ouvert, on ignore les nouveaux
    signaux ; on ne peut ré-entrer qu'après sa sortie (TP / SL / timeout).
  • Trois modes : LONG seul, SHORT seul, LONG+SHORT (à chaque bougie libre, on prend la
    direction dont la proba dépasse son seuil ; si les deux, on prend la plus confiante).
  • Balayage du TP conservé pour voir si "cible large = mieux" survit à l'exécution réaliste.

Anti-fuite : walk-forward expanding ; modèle entraîné sur le passé ; seuil de proba calibré
sur le train ; le SL reste −1R ; features calculées une fois (indépendantes du label).

Métriques réalistes : nb de trades (bien plus faible), win rate, E[R], R total, profit factor,
max drawdown, exposition (part du temps investi), durée moyenne de détention.
"""
from __future__ import annotations
import logging, warnings
from typing import Dict, List

import numpy as np
import pandas as pd
from xgboost import XGBClassifier

import config
config.VOLUME_FEATURES_ENABLED = False

import data_loader
import pipeline
import labeling
import fetch_data
from features.volatility import atr

warnings.filterwarnings("ignore")
logging.disable(logging.INFO)

ASSETS = ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD"]
TP_GRID = [1.0, 1.5, 2.0, 2.5, 3.0]
N_FOLDS = 4
TAKE_QUANTILE = 0.70          # seuil = quantile 70% des probas de train (top ~30% confiance)
MODES = ["long", "short", "both"]


def make_model() -> XGBClassifier:
    return XGBClassifier(
        n_estimators=180, max_depth=4, learning_rate=0.05,
        subsample=0.8, colsample_bytree=0.8, min_child_weight=6, reg_lambda=1.0,
        eval_metric="mlogloss", tree_method="hist", random_state=config.SEED,
        n_jobs=1 if config.STRICT_DETERMINISM else -1,
    )


def prepare_asset(symbol: str) -> dict:
    """Features (1×) + labels/realized/barrier par (side, tp), alignés sur un index valide commun."""
    raw = fetch_data.fetch(symbol)
    df = data_loader.clean(raw, symbol, do_resample=False)
    X = pipeline.build_features(df, symbol)
    r_unit = config.R_ATR_MULT * atr(df, config.ATR_PERIOD)

    lab_by = {}   # (side, tp) -> dict of arrays
    valid = X.notna().all(axis=1)
    for side in (+1, -1):
        for tp in TP_GRID:
            lab = labeling.triple_barrier(df, tp_mult=tp, sl_mult=config.SL_R_MULTIPLE,
                                          timeout=config.TIMEOUT_BARS, side=side, r_unit=r_unit)
            lab_by[(side, tp)] = lab
            valid &= lab["label"].notna()

    idx = X.index[valid]
    out = {"symbol": symbol, "X": X.loc[idx], "n": int(valid.sum()),
           "span": (df.index[0], df.index[-1]), "lab": {}}
    for key, lab in lab_by.items():
        out["lab"][key] = {
            "y": lab["label"].loc[idx].astype(int).to_numpy(),
            "r": lab["realized_r"].loc[idx].to_numpy(),
            "bars": lab["barrier_bars"].loc[idx].fillna(1).astype(int).to_numpy(),
        }
    return out


def _folds(n: int):
    fs = n // (N_FOLDS + 1)
    for k in range(1, N_FOLDS + 1):
        tr_end = k * fs
        te_start = tr_end + config.EMBARGO_BARS
        te_end = min((k + 1) * fs, n)
        if te_start < te_end:
            yield slice(0, tr_end), slice(te_start, te_end)


TP_CLS = config.LABEL_MAP["tp"]


def _proba_win(model, X, classes):
    p = model.predict_proba(X)
    return p[:, classes.index(TP_CLS)] if TP_CLS in classes else np.zeros(len(X))


def simulate_single(take: np.ndarray, r: np.ndarray, bars: np.ndarray) -> List[dict]:
    """Simulation non-chevauchante d'un seul sens. `take` booléen aligné sur le slice test."""
    n = len(take); i = 0; trades = []
    while i < n:
        if take[i] and np.isfinite(r[i]):
            trades.append({"r": float(r[i]), "hold": int(max(bars[i], 1))})
            i += int(max(bars[i], 1))       # bloqué jusqu'à la sortie du trade
        else:
            i += 1
    return trades


def simulate_both(pL, thrL, rL, barsL, pS, thrS, rS, barsS) -> List[dict]:
    """Non-chevauchant, choix long/short : la direction la plus au-dessus de son seuil gagne."""
    n = len(pL); i = 0; trades = []
    while i < n:
        okL = pL[i] >= thrL and np.isfinite(rL[i])
        okS = pS[i] >= thrS and np.isfinite(rS[i])
        if okL or okS:
            # marge de confiance relative au seuil pour départager
            take_long = okL and (not okS or (pL[i] - thrL) >= (pS[i] - thrS))
            if take_long:
                trades.append({"r": float(rL[i]), "hold": int(max(barsL[i], 1)), "dir": "L"})
                i += int(max(barsL[i], 1))
            else:
                trades.append({"r": float(rS[i]), "hold": int(max(barsS[i], 1)), "dir": "S"})
                i += int(max(barsS[i], 1))
        else:
            i += 1
    return trades


def backtest_asset_tp(a: dict, tp: float) -> Dict[str, List[dict]]:
    """Renvoie les trades exécutés par mode (long/short/both) pour un actif et un TP."""
    X = a["X"]; n = a["n"]
    trades = {m: [] for m in MODES}
    for tr, te in _folds(n):
        Xtr, Xte = X.iloc[tr], X.iloc[te]
        out = {}
        for side, tag in ((+1, "long"), (-1, "short")):
            d = a["lab"][(side, tp)]
            ytr = d["y"][tr]
            if len(np.unique(ytr)) < 2:
                out[tag] = None; continue
            m = make_model(); m.fit(Xtr, ytr)
            classes = list(m.classes_)
            ptr = _proba_win(m, Xtr, classes)
            pte = _proba_win(m, Xte, classes)
            thr = float(np.quantile(ptr, TAKE_QUANTILE))
            out[tag] = {"p": pte, "thr": thr, "r": d["r"][te], "bars": d["bars"][te]}
        # long / short seuls
        for tag in ("long", "short"):
            o = out.get(tag)
            if o:
                trades[tag] += simulate_single(o["p"] >= o["thr"], o["r"], o["bars"])
        # both
        if out.get("long") and out.get("short"):
            L, S = out["long"], out["short"]
            trades["both"] += simulate_both(L["p"], L["thr"], L["r"], L["bars"],
                                            S["p"], S["thr"], S["r"], S["bars"])
    return trades


def stats(trades: List[dict], n_bars_total: int | None = None) -> dict:
    if not trades:
        return dict(n=0, win=np.nan, exp=np.nan, tot=0.0, pf=np.nan, dd=0.0, hold=np.nan, expo=np.nan)
    r = np.array([t["r"] for t in trades]); hold = np.array([t["hold"] for t in trades])
    eq = np.cumsum(r); dd = float((eq - np.maximum.accumulate(eq)).min())
    g = r[r > 0].sum(); l = -r[r < 0].sum()
    return dict(n=int(len(r)), win=float((r > 0).mean()), exp=float(r.mean()),
                tot=float(r.sum()), pf=float(g / l) if l > 0 else float("inf"),
                dd=dd, hold=float(hold.mean()),
                expo=float(hold.sum() / n_bars_total) if n_bars_total else np.nan)


def run():
    import sys
    for s in (sys.stdout, sys.stderr):
        try: s.reconfigure(encoding="utf-8")
        except Exception: pass
    pipeline.set_seeds()

    print("═" * 88)
    print(" BACKTEST EXÉCUTABLE (non-chevauchant) — LONG / SHORT / LONG+SHORT · données réelles")
    print("═" * 88)
    print(f" Actifs : {', '.join(ASSETS)} | 1 position à la fois/actif | SL=−1R | walk-forward {N_FOLDS} folds")
    print("═" * 88)

    prepared = {s: prepare_asset(s) for s in ASSETS}
    total_test_bars = 0
    for s in ASSETS:
        a = prepared[s]
        # nb de bougies test cumulées (pour l'exposition)
        tb = sum(te.stop - te.start for _, te in _folds(a["n"]))
        prepared[s]["test_bars"] = tb
        total_test_bars += tb
        print(f"  {s:7s} : {a['n']:6d} lignes  [{a['span'][0].date()} → {a['span'][1].date()}]  test={tb}")

    # Balayage TP × mode (portefeuille agrégé)
    results = {}   # tp -> mode -> stats  (+ per-asset au meilleur tp both)
    all_trades = {}  # (tp,mode) -> list
    print("\n" + "─" * 88)
    print(" PORTEFEUILLE PAR TP ET PAR MODE (trades réels non-chevauchants)")
    print(f"   {'TP':>4} {'mode':>6} | {'trades':>6} | {'win%':>6} | {'E[R]':>7} | {'Rtot':>7} | {'PF':>5} | {'maxDD':>7} | {'expo':>5}")
    for tp in TP_GRID:
        agg = {m: [] for m in MODES}
        for s in ASSETS:
            tr = backtest_asset_tp(prepared[s], tp)
            for m in MODES:
                agg[m] += tr[m]
        results[tp] = {}
        for m in MODES:
            st = stats(agg[m], total_test_bars)
            results[tp][m] = st
            all_trades[(tp, m)] = agg[m]
            pf = "inf" if st["pf"] == float("inf") else f"{st['pf']:.2f}"
            expo = f"{st['expo']*100:.0f}%" if st['expo']==st['expo'] else "—"
            print(f"   {tp:>4} {m:>6} | {st['n']:>6} | {st['win']*100:>5.1f}% | {st['exp']:>+7.3f} | "
                  f"{st['tot']:>+7.1f} | {pf:>5} | {st['dd']:>7.1f} | {expo:>5}")
        print("   " + "·" * 80)

    # meilleur (tp, mode) par R total
    best = max(((tp, m) for tp in TP_GRID for m in MODES),
               key=lambda km: results[km[0]][km[1]]["tot"])
    bt, bm = best
    print(f"\n → MEILLEURE COMBINAISON : {bm.upper()} @ TP={bt}R  "
          f"(R tot {results[bt][bm]['tot']:+.1f}, E[R] {results[bt][bm]['exp']:+.3f}, "
          f"win {results[bt][bm]['win']*100:.1f}%, {results[bt][bm]['n']} trades)")

    # détail par actif au meilleur (tp, mode)
    print("\n" + "─" * 88)
    print(f" DÉTAIL PAR ACTIF — {bm.upper()} @ TP={bt}R")
    per_asset = {}
    for s in ASSETS:
        tr = backtest_asset_tp(prepared[s], bt)[bm]
        st = stats(tr, prepared[s]["test_bars"])
        per_asset[s] = st
        pf = "inf" if st["pf"] == float("inf") else f"{st['pf']:.2f}"
        print(f"   {s:7s} : trades={st['n']:4d}  win={st['win']*100:5.1f}%  E[R]={st['exp']:+.3f}  "
              f"Rtot={st['tot']:+7.1f}  PF={pf}  hold≈{st['hold']:.0f}h  expo={st['expo']*100:.0f}%")
    print("═" * 88)

    return {"results": results, "best": [bt, bm], "per_asset": per_asset,
            "spans": {s: [str(prepared[s]['span'][0].date()), str(prepared[s]['span'][1].date())] for s in ASSETS},
            "tp_grid": TP_GRID, "modes": MODES, "assets": ASSETS,
            "total_test_bars": total_test_bars}


if __name__ == "__main__":
    run()
