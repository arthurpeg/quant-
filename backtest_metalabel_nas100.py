"""Meta-labeling du breakout NAS100 : predire quels trades gagnent, filtrer les autres.
Rigueur : features CAUSALES (connues a l'entree), evaluation 100% OUT-OF-SAMPLE walk-forward.
Cible = win (R>0). On juge : AUC OOS, et si filtrer par proba ameliore R/PF vs tout prendre."""
import numpy as np, pandas as pd, backtest_breakout_nas100 as B
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.metrics import roc_auc_score
from xgboost import XGBClassifier

m10, amap = B.load("NAS100")
d1 = pd.read_parquet("data_cache_mt5/NAS100_D1.parquet").sort_values("time").reset_index(drop=True)
# --- features D1 CAUSALES : tout est shift(1) -> connu la veille au close ---
c = d1["close"]
d1["atr14"] = B.wilder_atr(d1, 14); d1["atr3"] = B.wilder_atr(d1, 3); d1["atr20"] = B.wilder_atr(d1, 20)
for n in (1, 5, 10, 20): d1[f"ret{n}"] = c.pct_change(n)
d1["sma200"] = c.rolling(200).mean()
d1["dist_sma200"] = c / d1["sma200"] - 1
d1["rvol20"] = c.pct_change().rolling(20).std()
lo20 = d1["low"].rolling(20).min(); hi20 = d1["high"].rolling(20).max()
d1["rangepos"] = (c - lo20) / (hi20 - lo20)
d1["regime_str"] = d1["atr3"] / d1["atr20"]
FD1 = ["atr3","atr20","regime_str","ret1","ret5","ret10","ret20","dist_sma200","rvol20","rangepos"]
d1s = d1[["time"] + FD1 + ["atr14"]].copy()
for col in FD1 + ["atr14"]:
    d1s[col] = d1s[col].shift(1)            # <-- CAUSAL : valeurs de la veille
dmap = {t.date(): row for t, row in zip(d1s["time"], d1s[FD1 + ["atr14"]].itertuples(index=False))}

# --- reconstruit les trades du breakout AVEC features a l'entree ---
p = dict(B.DEF); e_min, mx_min, x_min = B.hm(p["entry"]), B.hm(p["max_entry"]), B.hm(p["exit"])
kb, ks, rr = p["k_break"], p["k_stop"], p["rr"]; sprd = 13 * 0.1
rows_all = []
for day, g in m10.groupby("date"):
    a = amap.get(day)
    if a is None or not np.isfinite(a[0]) or a[0] <= 0 or not (a[1] < a[2]): continue
    fd = dmap.get(day)
    if fd is None or not np.isfinite(fd.atr14): continue
    atr14 = a[0]; rows = list(g.sort_values("min").itertuples(index=False)); by = {r.min: r for r in rows}
    if e_min not in by: continue
    oref = by[e_min].open; up = oref + kb*atr14; lo = oref - kb*atr14; sd = ks*atr14; td = ks*rr*atr14
    entry = None
    for i, r in enumerate(rows):
        if r.min <= e_min: continue
        if r.min >= mx_min: break
        prev = rows[i-1]
        if prev.close >= up: entry = ("long", i, r.open+sprd, prev.close, up); break
        if prev.close <= lo: entry = ("short", i, r.open, prev.close, lo); break
    if entry is None: continue
    side, ei, epx, confclose, lvl = entry
    slp, tpp = (epx-sd, epx+td) if side == "long" else (epx+sd, epx-td)
    R = None
    for r in rows[ei:]:
        if r.min >= x_min and r is not rows[ei]:
            R = ((r.open-epx) if side == "long" else (epx-(r.open+sprd)))/sd; break
        res = B.resolve_bar(side, r.open if r is not rows[ei] else epx, r.high, r.low, r.close, slp, tpp, sprd)
        if res: R = (-1.0 if res[0] == "sl" else rr); break
    if R is None:
        last = rows[-1]; R = ((last.close-epx) if side == "long" else (epx-(last.close+sprd)))/sd
    # features intraday causales
    day_move = (rows[ei].open - oref)/atr14
    brk_str = (confclose - lvl)/atr14 if side == "long" else (lvl - confclose)/atr14
    ent_min = rows[ei].min - e_min
    feat = {f: getattr(fd, f) for f in FD1}
    feat.update(side=1 if side == "long" else 0, day_move=day_move, brk_str=brk_str,
                ent_min=ent_min, dow=pd.Timestamp(day).dayofweek, month=pd.Timestamp(day).month,
                date=pd.Timestamp(day), R=R, win=int(R > 0))
    rows_all.append(feat)

df = pd.DataFrame(rows_all).dropna().sort_values("date").reset_index(drop=True)
FEATS = [c for c in df.columns if c not in ("date", "R", "win")]
print(f"Trades avec features: {len(df)} | features: {len(FEATS)} | baseline win={df.win.mean():.1%} E[R]={df.R.mean():+.3f}")

# --- WALK-FORWARD : entraine sur le passe, predit l'annee suivante (OOS) ---
df["year"] = df.date.dt.year
oos = []
for ytest in range(2021, 2027):
    tr = df[df.year < ytest]; te = df[df.year == ytest]
    if len(te) == 0 or tr.win.nunique() < 2: continue
    Xtr, ytr, Xte = tr[FEATS], tr.win, te[FEATS]
    lr = make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000, C=0.3)).fit(Xtr, ytr)
    xgb = XGBClassifier(max_depth=2, n_estimators=120, learning_rate=0.05, subsample=0.8,
                        colsample_bytree=0.8, reg_lambda=2.0, eval_metric="logloss").fit(Xtr, ytr)
    t = te.copy(); t["p_lr"] = lr.predict_proba(Xte)[:, 1]; t["p_xgb"] = xgb.predict_proba(Xte)[:, 1]
    oos.append(t)
O = pd.concat(oos).reset_index(drop=True)
print(f"\nOOS 2021-2026: n={len(O)}  base win={O.win.mean():.1%}  base E[R]={O.R.mean():+.3f}  "
      f"base PF={O[O.R>0].R.sum()/-O[O.R<0].R.sum():.2f}")
for m in ("p_lr", "p_xgb"):
    print(f"\n--- modele {m} ---  AUC OOS = {roc_auc_score(O.win, O[m]):.3f}")
    # deciles de proba -> R realise (le modele separe-t-il ?)
    O["q"] = pd.qcut(O[m], 4, labels=False, duplicates="drop")
    g = O.groupby("q").agg(n=("R","size"), win=("win","mean"), ER=("R","mean"))
    print("  quartile proba -> ", {int(k): (int(v.n), round(v.win,2), round(v.ER,3)) for k,v in g.iterrows()})
    # filtre : ne garder que la moitie a plus forte proba
    thr = O[m].median(); keep = O[O[m] >= thr]
    pf = keep[keep.R>0].R.sum()/max(-keep[keep.R<0].R.sum(),1e-9)
    print(f"  filtre top-50%: n={len(keep)} win={keep.win.mean():.1%} E[R]={keep.R.mean():+.3f} PF={pf:.2f} "
          f"(vs base E[R]={O.R.mean():+.3f})")
