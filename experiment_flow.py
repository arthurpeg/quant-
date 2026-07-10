"""
experiment_flow.py
==================
Apport marginal du bloc MICROSTRUCTURE DE COTATION (orderflow.py) sur les deux cibles.

⚠️ Ce n'est PAS de l'order flow au sens strict : les ticks CFD FX de MT5 n'ont ni prix ni
   volume de transaction (last=0, volume=0), et le carnet L2 historique n'existe pas.
   On mesure donc ce qui est réellement disponible : intensité de cotation, spread,
   volatilité réalisée haute fréquence, déséquilibre des upticks du mid.

Fenêtre limitée à ~1 an (profondeur des ticks) → échantillon plus petit, résultats plus
bruités que l'expérience V3. On le dit plutôt que de le cacher.
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
config.PANDAS_FREQ = "1h"; config.TIMEFRAME = "H1"

import data_loader, pipeline, labeling, mt5_loader, orderflow
from features.volatility import atr

warnings.filterwarnings("ignore")
logging.disable(logging.INFO)

ASSETS = ["EURUSD", "XAUUSD"]
TIMEOUT = 24
TP = 2.0
VOL_HORIZON = 24
N_FOLDS = 3
SEED = config.SEED


def _clf():
    return XGBClassifier(n_estimators=200, max_depth=4, learning_rate=0.05, subsample=0.8,
                         colsample_bytree=0.8, min_child_weight=6, eval_metric="logloss",
                         tree_method="hist", random_state=SEED, n_jobs=-1)


def _reg():
    return XGBRegressor(n_estimators=300, max_depth=4, learning_rate=0.05, subsample=0.8,
                        colsample_bytree=0.8, min_child_weight=6, tree_method="hist",
                        random_state=SEED, n_jobs=-1)


def prepare(symbol):
    df = data_loader.clean(mt5_loader.fetch(symbol, "H1"), symbol,
                           do_resample=False, reindex_grid=False)
    flow = orderflow.build(symbol, months=12, freq="1h")
    df = df.loc[df.index.isin(flow.index)]          # restreint à la fenêtre tick
    flow = flow.reindex(df.index)

    XP = pipeline.build_features(df, symbol)
    XF = flow.copy()
    for X in (XP, XF):
        X.drop(columns=X.columns[X.isna().all()], inplace=True)

    r_unit = config.R_ATR_MULT * atr(df, config.ATR_PERIOD)
    lab = labeling.triple_barrier(df, tp_mult=TP, sl_mult=config.SL_R_MULTIPLE,
                                  timeout=TIMEOUT, side=+1, r_unit=r_unit)
    y_dir = (lab["label"] == config.LABEL_MAP["tp"]).astype(float)
    y_dir[lab["label"].isna()] = np.nan

    ret = np.log(df[config.COL_CLOSE] / df[config.COL_CLOSE].shift(1))
    sq = ret ** 2
    rv_fwd = np.sqrt(sq.rolling(VOL_HORIZON).sum().shift(-VOL_HORIZON))
    rv_past = np.sqrt(sq.rolling(VOL_HORIZON).sum())
    y_vol = np.log(rv_fwd + 1e-12)
    x_naive = np.log(rv_past + 1e-12)

    valid = (XP.notna().all(axis=1) & XF.notna().all(axis=1) & y_dir.notna()
             & y_vol.notna() & np.isfinite(x_naive))
    idx = XP.index[valid]
    return {"P": XP.loc[idx], "F": XF.loc[idx],
            "y_dir": y_dir.loc[idx].astype(int).to_numpy(),
            "y_vol": y_vol.loc[idx].to_numpy(),
            "naive": x_naive.loc[idx].to_numpy().reshape(-1, 1), "n": len(idx)}


def folds(n):
    fs = n // (N_FOLDS + 1)
    for k in range(1, N_FOLDS + 1):
        tr_end = k * fs
        te_s = tr_end + TIMEOUT
        te_e = min((k + 1) * fs, n)
        if te_s < te_e:
            yield slice(0, tr_end), slice(te_s, te_e)


def r2_oos(y, p):
    ssr = np.sum((y - p) ** 2); sst = np.sum((y - y.mean()) ** 2)
    return 1 - ssr / sst if sst > 0 else np.nan


def run():
    import sys
    for s in (sys.stdout, sys.stderr):
        try: s.reconfigure(encoding="utf-8")
        except Exception: pass
    np.random.seed(SEED)
    print("═" * 88)
    print(" MICROSTRUCTURE DE COTATION — apport marginal (fenêtre tick ~1 an, base H1)")
    print("═" * 88)
    print(" NB : pas d'order flow réel (ticks sans transaction/volume ; L2 historique inexistant)")
    print("═" * 88)

    prep = {s: prepare(s) for s in ASSETS}
    for s in ASSETS:
        print(f"  {s:7s} n={prep[s]['n']:5d} | P={prep[s]['P'].shape[1]} F={prep[s]['F'].shape[1]}")

    SPECS = {"P": ["P"], "P+F": ["P", "F"], "F seul": ["F"]}

    print("\n" + "─" * 88)
    print(" TÂCHE 1 — DIRECTION · ROC-AUC")
    for name, spec in SPECS.items():
        aucs = []
        for s in ASSETS:
            a = prep[s]; X = pd.concat([a[b] for b in spec], axis=1); y = a["y_dir"]
            for tr, te in folds(a["n"]):
                if len(np.unique(y[tr])) < 2 or len(np.unique(y[te])) < 2:
                    continue
                m = _clf(); m.fit(X.iloc[tr], y[tr])
                aucs.append(roc_auc_score(y[te], m.predict_proba(X.iloc[te])[:, 1]))
        print(f"   {name:>7} : AUC = {np.mean(aucs):.4f}")

    print("\n" + "─" * 88)
    print(" TÂCHE 2 — VOLATILITÉ (24 barres) · R² OOS + IC")
    r2s, ics = [], []
    for s in ASSETS:
        a = prep[s]; y = a["y_vol"]; Xn = a["naive"]
        for tr, te in folds(a["n"]):
            lr = LinearRegression().fit(Xn[tr], y[tr]); p = lr.predict(Xn[te])
            r2s.append(r2_oos(y[te], p)); ics.append(spearmanr(y[te], p).statistic)
    print(f"   {'NAÏF':>7} : R² = {np.mean(r2s):+.4f}   IC = {np.mean(ics):+.4f}")

    for name, spec in SPECS.items():
        r2s, ics = [], []
        for s in ASSETS:
            a = prep[s]; X = pd.concat([a[b] for b in spec], axis=1); y = a["y_vol"]
            for tr, te in folds(a["n"]):
                m = _reg(); m.fit(X.iloc[tr], y[tr]); p = m.predict(X.iloc[te])
                r2s.append(r2_oos(y[te], p)); ics.append(spearmanr(y[te], p).statistic)
        print(f"   {name:>7} : R² = {np.mean(r2s):+.4f}   IC = {np.mean(ics):+.4f}")
    print("═" * 88)


if __name__ == "__main__":
    run()
