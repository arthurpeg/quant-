"""
xsection_fx.py
==============
Cross-sectionnel FX + MÉTAUX dans l'univers prop-firm : au lieu de prédire la direction
absolue d'un actif (ce qui s'est révélé impossible, AUC ≈ 0.51), on CLASSE les actifs entre
eux et on prend long le haut du classement / short le bas.

  • Univers  : ~20 devises + métaux, orientés "vs USD" (fx_loader) → l'exposition USD
               s'annule dans le book long/short.
  • Features : momentum (12-1, 6-1, 3-1, 1m), reversal 5j, volatilité, distance au plus-haut
               52s, "value" (déviation à la moyenne long terme). Toutes causales.
               PAS de carry (swap historique indisponible → voir fx_loader).
  • Cible    : rendement 5j futur, EXCÉDENTAIRE vs la moyenne de l'univers à cette date.
  • Coûts    : spread réel MT5 par actif × turnover.

On compare le ML aux FACTEURS SIMPLES (tri momentum / value / reversal). Si le ML n'apporte
rien de plus qu'un tri par momentum, on le dit.
"""
from __future__ import annotations
import warnings
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from xgboost import XGBRegressor

import config
import fx_loader

warnings.filterwarnings("ignore")

HORIZON = 5
REBAL = 5
N_FOLDS = 4
QUANTILE = 0.20        # top/bottom quintile
# Panel "ragged" : on classe les actifs DISPONIBLES à chaque date, avec un minimum de noms
# pour garder de la breadth. Un seuil absolu (= tout l'univers) ferait dépendre chaque date
# de l'actif au démarrage le plus tardif (value_5y = fenêtre 5 ans) → échantillon dégénéré.
MIN_NAMES = 6          # nb minimum d'actifs valides pour retenir une date de rebalancement
SEED = config.SEED
PERIODS_PER_YEAR = 252 / REBAL

# Le spread instantané renvoyé par MT5 tombe parfois à 0 (snapshot hors marché) : on impose
# un plancher réaliste et un multiplicateur pour commission + slippage. Mieux vaut surestimer
# le coût que se raconter une histoire.
COST_FLOOR_BPS = 1.0
COST_MULT = 1.5


def _reg():
    return XGBRegressor(n_estimators=250, max_depth=3, learning_rate=0.05, subsample=0.8,
                        colsample_bytree=0.8, min_child_weight=20, reg_lambda=3.0,
                        tree_method="hist", random_state=SEED, n_jobs=-1)


def build_features(close: pd.DataFrame) -> dict:
    logp = np.log(close)
    ret = logp.diff()
    f = {}
    f["mom_12_1"] = logp.shift(21) - logp.shift(252)
    f["mom_6_1"] = logp.shift(21) - logp.shift(126)
    f["mom_3_1"] = logp.shift(21) - logp.shift(63)
    f["mom_1m"] = logp - logp.shift(21)
    f["rev_5"] = logp - logp.shift(5)
    f["vol_60"] = ret.rolling(60, min_periods=60).std()
    f["dist_52w_high"] = close / close.rolling(252, min_periods=252).max() - 1.0
    # "value" FX : déviation au niveau moyen long terme (proxy de retour à la moyenne)
    f["value_5y"] = -(logp - logp.rolling(1260, min_periods=756).mean())
    f["skew_60"] = ret.rolling(60, min_periods=60).skew()
    return f


def assemble(close: pd.DataFrame):
    feats = build_features(close)
    logp = np.log(close)
    fwd = logp.shift(-HORIZON) - logp
    fwd_excess = fwd.sub(fwd.mean(axis=1), axis=0)

    prepared = []
    for d in close.index[::REBAL]:
        x = pd.DataFrame({k: v.loc[d] for k, v in feats.items()})
        y = fwd_excess.loc[d]
        ok = x.notna().all(axis=1) & y.notna()
        if ok.sum() < MIN_NAMES:
            continue
        xr = x[ok].rank(pct=True) - 0.5          # rang cross-sectionnel (neutre au marché)
        prepared.append((d, xr, y[ok]))
    return prepared


def portfolio(preds, cost_bps: pd.Series):
    """Long/short quintile, poids égaux, gross exposure = 1. Renvoie R brut et net par période."""
    gross, net, prev_w = [], [], None
    for d, p, y in preds:
        k = max(int(round(len(p) * QUANTILE)), 2)
        longs, shorts = p.nlargest(k).index, p.nsmallest(k).index
        w = pd.Series(0.0, index=p.index)
        w[longs] = 0.5 / k
        w[shorts] = -0.5 / k
        r = float((w * y.reindex(w.index).fillna(0.0)).sum())
        if prev_w is None:
            dw = w.abs()
        else:
            dw = (w - prev_w.reindex(w.index).fillna(0.0)).abs()
        c = float((dw * cost_bps.reindex(w.index).fillna(cost_bps.median()) / 1e4).sum())
        gross.append(r); net.append(r - c); prev_w = w
    return np.array(gross), np.array(net)


def stats(g, n, ics, label):
    ics = np.asarray([i for i in ics if np.isfinite(i)])
    mean_ic, std_ic = ics.mean(), ics.std(ddof=1)
    t_ic = mean_ic / std_ic * np.sqrt(len(ics))
    ic_ir = mean_ic / std_ic * np.sqrt(PERIODS_PER_YEAR)

    def sh(x):
        return x.mean() / x.std(ddof=1) * np.sqrt(PERIODS_PER_YEAR) if x.std(ddof=1) > 0 else np.nan
    eq = np.cumsum(n)
    dd = float((eq - np.maximum.accumulate(eq)).min())
    return {"label": label, "mean_ic": mean_ic, "t_ic": t_ic, "ic_ir": ic_ir,
            "gross_ann": g.mean() * PERIODS_PER_YEAR, "net_ann": n.mean() * PERIODS_PER_YEAR,
            "sharpe_gross": sh(g), "sharpe_net": sh(n), "max_dd": dd,
            "hit": float((n > 0).mean()), "n_periods": len(n)}


def run_ml(prepared, cost_bps):
    n = len(prepared)
    fs = n // (N_FOLDS + 1)
    preds, ics = [], []
    for k in range(1, N_FOLDS + 1):
        tr = prepared[: k * fs]
        te = prepared[k * fs + 1 : (k + 1) * fs]        # 1 période d'embargo
        if not te:
            continue
        Xtr = pd.concat([p[1] for p in tr]); ytr = pd.concat([p[2] for p in tr])
        m = _reg(); m.fit(Xtr, ytr)
        for d, xr, y in te:
            p = pd.Series(m.predict(xr), index=xr.index)
            ics.append(spearmanr(p, y).statistic)
            preds.append((d, p, y))
    g, nn = portfolio(preds, cost_bps)
    return stats(g, nn, ics, "ML (XGBoost)"), preds


def run_factor(prepared, cost_bps, feature, sign, label, skip):
    """Tri par un facteur simple, sur les MÊMES périodes de test que le ML."""
    preds, ics = [], []
    for d, xr, y in prepared[skip:]:
        p = sign * xr[feature]
        ics.append(spearmanr(p, y).statistic)
        preds.append((d, p, y))
    g, nn = portfolio(preds, cost_bps)
    return stats(g, nn, ics, label)


def run():
    import sys
    for s in (sys.stdout, sys.stderr):
        try: s.reconfigure(encoding="utf-8")
        except Exception: pass
    np.random.seed(SEED)

    panel = fx_loader.build_panel()
    sp = pd.Series(fx_loader.spreads_bps())

    # filtres : liquidité + couverture d'historique
    liquid = sp[sp <= fx_loader.MAX_SPREAD_BPS].index
    cover = panel.notna().mean()
    keep = [c for c in panel.columns if c in liquid and cover[c] >= 0.8]
    close = panel[keep].dropna(how="all")
    cost_bps = sp[keep].clip(lower=COST_FLOOR_BPS) * COST_MULT

    print("═" * 88)
    print(" CROSS-SECTIONNEL FX + MÉTAUX — univers prop-firm · long/short quintile")
    print("═" * 88)
    print(f" Actifs retenus ({len(keep)}) : {', '.join(keep)}")
    print(f" Période {close.index[0].date()} → {close.index[-1].date()} · rebal {REBAL}j · horizon {HORIZON}j")
    print(f" Coût = spread réel MT5 × turnover (médiane {cost_bps.median():.1f} bps)")
    print(" PAS de carry (swap historique indisponible → look-ahead évité)")
    print("═" * 88)

    prepared = assemble(close)
    print(f" {len(prepared)} rebalancements · ~{int(np.mean([len(p[1]) for p in prepared]))} actifs/date")

    ml, preds = run_ml(prepared, cost_bps)
    skip = len(prepared) - ml["n_periods"]              # aligner les facteurs sur le test ML

    rows = [ml]
    rows.append(run_factor(prepared, cost_bps, "mom_12_1", +1, "Momentum 12-1", skip))
    rows.append(run_factor(prepared, cost_bps, "value_5y", +1, "Value (5y)", skip))
    rows.append(run_factor(prepared, cost_bps, "rev_5", -1, "Reversal 5j", skip))

    print("\n" + "─" * 88)
    print(f"   {'stratégie':>16} | {'IC':>8} | {'t(IC)':>6} | {'IC-IR':>6} | {'brut%/an':>9} | "
          f"{'net%/an':>8} | {'Sh brut':>7} | {'Sh net':>7} | {'maxDD':>7}")
    for r in rows:
        print(f"   {r['label']:>16} | {r['mean_ic']:>+8.4f} | {r['t_ic']:>6.2f} | {r['ic_ir']:>+6.2f} | "
              f"{r['gross_ann']*100:>+9.2f} | {r['net_ann']*100:>+8.2f} | {r['sharpe_gross']:>7.2f} | "
              f"{r['sharpe_net']:>7.2f} | {r['max_dd']*100:>6.1f}%")

    print("\n" + "─" * 88)
    b = max(rows, key=lambda r: r["sharpe_net"])
    print(f" Meilleure stratégie nette : {b['label']}  (Sharpe net {b['sharpe_net']:.2f}, "
          f"{b['net_ann']*100:+.2f}%/an)")
    print(f" Significativité de l'IC : t = {b['t_ic']:.2f} "
          f"({'significatif' if abs(b['t_ic'])>1.96 else 'NON significatif à 5%'})")
    print(f" Breadth : ~{int(np.mean([len(p[1]) for p in prepared]))} actifs × {int(PERIODS_PER_YEAR)} rebal/an")
    print("═" * 88)


if __name__ == "__main__":
    run()
