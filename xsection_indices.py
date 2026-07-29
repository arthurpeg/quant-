"""xsection_indices.py — cross-sectional sur les INDICES liquides prop uniquement (spread serre,
momentum qui trende, multi-regions). Derniere piste breadth non-testee (exp-003 follow-up).
Teste plusieurs signaux net du spread reel. Reutilise le panel cache par xsection_wide.py.

CAVEAT : closes D1 non-synchrones entre regions (US/EU/Asie ferment a des heures differentes)
-> le cross-section journalier compare des prix decales. Biais connu, a garder en tete.
"""
import os, numpy as np, pandas as pd
from scipy.stats import spearmanr

CACHE = os.path.join(os.path.dirname(__file__), "data_cache_mt5")
px = pd.read_parquet(f"{CACHE}/prop_universe_D1.parquet")
bps = pd.read_csv(f"{CACHE}/prop_universe_spread_bps.csv", index_col=0)["bps"]
IDX = [c for c in ["NAS100","US30","US500","US2000","GER40","FRA40","UK100","EU50","AUS200","HK50","JP225"] if c in px.columns]
P = px[IDX].copy()
print(f"Indices dans le panel: {len(IDX)} -> {IDX}")
cov = P.notna().sum()
print("Couverture (jours):", {k: int(v) for k, v in cov.items()})
print(f"Spread bps: {(bps[IDX]).round(2).to_dict()}")

ret = np.log(P).diff()
R = ret.dropna()
C = R.corr().values; w = np.linalg.eigvalsh(C); w = w[w > 1e-8]
neff = (w.sum()**2)/(w**2).sum()
print(f"\nN_eff indices = {neff:.1f}  (rho moyen = {C[~np.eye(len(C),dtype=bool)].mean():+.2f})\n")

def signal(P, kind):
    if kind == "mom3m":  return np.log(P.shift(5)/P.shift(63))
    if kind == "mom1m":  return np.log(P.shift(1)/P.shift(21))
    if kind == "mom6m":  return np.log(P.shift(5)/P.shift(126))
    if kind == "rev5d":  return -np.log(P/P.shift(5))          # reversal = -momentum court
    if kind == "rev1d":  return -np.log(P/P.shift(1))

def backtest(kind, ls=True):
    sig = signal(P, kind); fwd = np.log(P.shift(-5)/P)
    dates = P.index[126:-5:5]
    ics=[]; rets=[]; prev=pd.Series(0.0,index=IDX)
    for d in dates:
        m=sig.loc[d].dropna(); f=fwd.loc[d].reindex(m.index).dropna(); m=m[f.index]
        if len(m)<6: continue
        ics.append(spearmanr(m,f).correlation)
        k=max(1,len(m)//3)                          # tiercile (11 noms -> ~3/cote)
        wt=pd.Series(0.0,index=IDX)
        wt[m.nlargest(k).index]=1.0/k
        if ls: wt[m.nsmallest(k).index]=-1.0/k
        g=(wt.reindex(f.index).fillna(0)*f).sum()
        turn=(wt-prev.reindex(IDX).fillna(0)).abs()
        cost=(turn*(bps.reindex(IDX).fillna(bps.median())/1e4)).sum()
        rets.append(g-cost); prev=wt
    ics=np.array(ics); rets=pd.Series(rets)
    ict=ics.mean()/(ics.std()/np.sqrt(len(ics)))
    sh=rets.mean()/rets.std()*np.sqrt(52) if rets.std()>0 else np.nan
    print(f"{kind:6s} {'L/S' if ls else 'long':4s}: n={len(rets)} IC={ics.mean():+.4f} t={ict:+.2f} "
          f"net%/an={rets.mean()*52*100:+.2f} Sharpe={sh:+.2f}")

print(f"{'signal':13s} {'rebal':>5s} {'IC':>8s} {'t':>6s} {'net/an':>8s} {'Sharpe':>7s}")
for k in ["mom6m","mom3m","mom1m","rev5d","rev1d"]:
    backtest(k, ls=True)
print("--- long-only top tiercile (momentum) ---")
for k in ["mom3m","mom1m"]:
    backtest(k, ls=False)
