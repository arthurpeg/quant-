"""
experiment_v3.py
================
L'expérience décisive : est-ce qu'une information d'une NATURE DIFFÉRENTE du prix crée
enfin du signal ? Et est-ce qu'une CIBLE différente (volatilité) est plus prévisible que
la direction ?

Deux tâches, mêmes folds walk-forward, mêmes actifs, base H4 (MT5, 2018+) :

  TÂCHE 1 — DIRECTION : triple-barrier (TP=2R, SL=−1R). Métrique : ROC-AUC.
  TÂCHE 2 — VOLATILITÉ : prédire la volatilité réalisée des N prochaines barres.
            Métrique : R² hors-échantillon + IC de Spearman.
            Référence naïve : la persistance (vol passée → vol future), régression linéaire.

Ablation des blocs de features :
  P = prix/technique (momentum, volatilité, structure, volume)
  S = saisonnalité / calendrier
  X = cross-asset / macro (DXY synthétique, VIXY, UST)

Si X et S n'améliorent ni l'AUC ni le R², c'est que l'information n'y est pas — et on le dira.
"""
from __future__ import annotations
import logging, warnings
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.metrics import roc_auc_score
from sklearn.linear_model import LinearRegression
from xgboost import XGBClassifier, XGBRegressor

import config
config.ENABLE_MTF = False
config.VOLUME_FEATURES_ENABLED = True

import data_loader, pipeline, labeling, mt5_loader
from features.volatility import atr
from features import seasonality, cross_asset

warnings.filterwarnings("ignore")
logging.disable(logging.INFO)

ASSETS = ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "US30"]
TF = "H4"
TIMEOUT = 24          # barres (≈4 jours en H4)
TP = 2.0
VOL_HORIZON = 24      # volatilité réalisée sur les 24 prochaines barres
N_FOLDS = 4
EMBARGO = TIMEOUT
SEED = config.SEED


def _clf():
    return XGBClassifier(n_estimators=200, max_depth=4, learning_rate=0.05, subsample=0.8,
                         colsample_bytree=0.8, min_child_weight=6, eval_metric="logloss",
                         tree_method="hist", random_state=SEED, n_jobs=-1)


def _reg():
    return XGBRegressor(n_estimators=300, max_depth=4, learning_rate=0.05, subsample=0.8,
                        colsample_bytree=0.8, min_child_weight=6, tree_method="hist",
                        random_state=SEED, n_jobs=-1)


def prepare(symbol: str) -> dict:
    config.PANDAS_FREQ = "4h"; config.TIMEFRAME = TF
    df = data_loader.clean(mt5_loader.fetch(symbol, TF), symbol,
                           do_resample=False, reindex_grid=False)

    XP = pipeline.build_features(df, symbol)
    XS = seasonality.compute(df)
    XX = cross_asset.compute(df, TF)
    for X in (XP, XS, XX):
        X.drop(columns=X.columns[X.isna().all()], inplace=True)

    # --- cible DIRECTION ---
    r_unit = config.R_ATR_MULT * atr(df, config.ATR_PERIOD)
    lab = labeling.triple_barrier(df, tp_mult=TP, sl_mult=config.SL_R_MULTIPLE,
                                  timeout=TIMEOUT, side=+1, r_unit=r_unit)
    y_dir = (lab["label"] == config.LABEL_MAP["tp"]).astype(float)
    y_dir[lab["label"].isna()] = np.nan

    # --- cible VOLATILITÉ : vol réalisée des N prochaines barres (futur → y uniquement) ---
    ret = np.log(df[config.COL_CLOSE] / df[config.COL_CLOSE].shift(1))
    sq = ret ** 2
    fwd_sum = sq.rolling(VOL_HORIZON).sum().shift(-VOL_HORIZON)   # somme de t+1 à t+N
    rv_fwd = np.sqrt(fwd_sum)
    rv_past = np.sqrt(sq.rolling(VOL_HORIZON).sum())              # persistance (connue à t)
    eps = 1e-12
    y_vol = np.log(rv_fwd + eps)
    x_naive = np.log(rv_past + eps)

    valid = (XP.notna().all(axis=1) & XS.notna().all(axis=1) & XX.notna().all(axis=1)
             & y_dir.notna() & y_vol.notna() & np.isfinite(x_naive))
    idx = XP.index[valid]
    return {"symbol": symbol, "P": XP.loc[idx], "S": XS.loc[idx], "X": XX.loc[idx],
            "y_dir": y_dir.loc[idx].astype(int).to_numpy(),
            "y_vol": y_vol.loc[idx].to_numpy(),
            "naive": x_naive.loc[idx].to_numpy().reshape(-1, 1), "n": len(idx)}


def folds(n):
    fs = n // (N_FOLDS + 1)
    for k in range(1, N_FOLDS + 1):
        tr_end = k * fs
        te_s = tr_end + EMBARGO
        te_e = min((k + 1) * fs, n)
        if te_s < te_e:
            yield slice(0, tr_end), slice(te_s, te_e)


def blocks(a, spec):
    parts = [a[b] for b in spec]
    return pd.concat(parts, axis=1)


def r2_oos(y_true, y_pred):
    ss_res = np.sum((y_true - y_pred) ** 2)
    ss_tot = np.sum((y_true - y_true.mean()) ** 2)
    return 1 - ss_res / ss_tot if ss_tot > 0 else np.nan


def run():
    import sys
    for s in (sys.stdout, sys.stderr):
        try: s.reconfigure(encoding="utf-8")
        except Exception: pass
    np.random.seed(SEED)
    print("═" * 90)
    print(" EXPÉRIENCE V3 — information d'une autre nature (macro/saisonnalité) & autre cible (vol)")
    print("═" * 90)
    print(f" Base {TF} MT5 · actifs {', '.join(ASSETS)} · walk-forward {N_FOLDS} folds")
    print("═" * 90)

    prep = {}
    for s in ASSETS:
        prep[s] = prepare(s)
        a = prep[s]
        print(f"  {s:7s} n={a['n']:6d} | features P={a['P'].shape[1]} S={a['S'].shape[1]} X={a['X'].shape[1]}")

    SPECS = {"P": ["P"], "P+S": ["P", "S"], "P+X": ["P", "X"], "P+S+X": ["P", "S", "X"]}

    # ── TÂCHE 1 : DIRECTION (AUC) ──
    print("\n" + "─" * 90)
    print(" TÂCHE 1 — DIRECTION (triple-barrier TP=2R) · métrique : ROC-AUC (0.50 = hasard)")
    dir_res = {}
    for name, spec in SPECS.items():
        aucs = []
        for s in ASSETS:
            a = prep[s]; X = blocks(a, spec); y = a["y_dir"]
            for tr, te in folds(a["n"]):
                if len(np.unique(y[tr])) < 2 or len(np.unique(y[te])) < 2:
                    continue
                m = _clf(); m.fit(X.iloc[tr], y[tr])
                p = m.predict_proba(X.iloc[te])[:, 1]
                aucs.append(roc_auc_score(y[te], p))
        dir_res[name] = float(np.mean(aucs))
        print(f"   {name:>7} : AUC = {dir_res[name]:.4f}")

    # ── TÂCHE 2 : VOLATILITÉ (R² OOS + IC) ──
    print("\n" + "─" * 90)
    print(" TÂCHE 2 — VOLATILITÉ réalisée à 24 barres · R² hors-échantillon + IC de Spearman")
    # référence naïve : persistance (vol passée), régression linéaire ajustée sur le train
    r2s, ics = [], []
    for s in ASSETS:
        a = prep[s]; y = a["y_vol"]; Xn = a["naive"]
        for tr, te in folds(a["n"]):
            lr = LinearRegression().fit(Xn[tr], y[tr])
            p = lr.predict(Xn[te])
            r2s.append(r2_oos(y[te], p)); ics.append(spearmanr(y[te], p).statistic)
    print(f"   {'NAÏF':>7} : R² = {np.mean(r2s):+.4f}   IC = {np.mean(ics):+.4f}   (persistance seule)")
    vol_res = {"NAÏF": (float(np.mean(r2s)), float(np.mean(ics)))}

    for name, spec in SPECS.items():
        r2s, ics = [], []
        for s in ASSETS:
            a = prep[s]; X = blocks(a, spec); y = a["y_vol"]
            for tr, te in folds(a["n"]):
                m = _reg(); m.fit(X.iloc[tr], y[tr])
                p = m.predict(X.iloc[te])
                r2s.append(r2_oos(y[te], p)); ics.append(spearmanr(y[te], p).statistic)
        vol_res[name] = (float(np.mean(r2s)), float(np.mean(ics)))
        print(f"   {name:>7} : R² = {vol_res[name][0]:+.4f}   IC = {vol_res[name][1]:+.4f}")

    print("\n" + "═" * 90)
    print(" SYNTHÈSE")
    print(f"   Direction : meilleure AUC = {max(dir_res.values()):.4f} "
          f"({max(dir_res, key=dir_res.get)})  → {'signal' if max(dir_res.values())>0.55 else 'PAS de signal exploitable'}")
    best_vol = max(vol_res, key=lambda k: vol_res[k][0])
    print(f"   Volatilité: meilleur R² = {vol_res[best_vol][0]:+.4f} ({best_vol}) "
          f"vs naïf {vol_res['NAÏF'][0]:+.4f}  → gain {vol_res[best_vol][0]-vol_res['NAÏF'][0]:+.4f}")
    print("═" * 90)
    return {"direction": dir_res, "vol": vol_res}


if __name__ == "__main__":
    run()
