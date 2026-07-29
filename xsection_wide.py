"""xsection_wide.py — teste si l'univers prop ELARGI (Pepperstone : majors + crosses FX + metaux
+ indices multi-region + energie) donne assez de breadth pour un momentum cross-sectionnel
DEPLOYABLE, net de cout. Reponse a la question ouverte exp-003/exp-004 : "comment obtenir de la
breadth dans l'univers tradable ?". Compare majors-seuls (~exp-003) vs elargi.

Pull D1 via MetaTrader5 (une fois -> cache), signal momentum 3m (skip 5j), rebalance hebdo,
book long/short top/bottom quintile, cout = spread reel par paire (bps) x turnover.
"""
import os, datetime as dt, numpy as np, pandas as pd
from scipy.stats import spearmanr

CACHE = os.path.join(os.path.dirname(__file__), "data_cache_mt5")
PANEL = f"{CACHE}/prop_universe_D1.parquet"; SPR = f"{CACHE}/prop_universe_spread_bps.csv"

def pull():
    import MetaTrader5 as mt5
    mt5.initialize()
    FIAT = set("USD EUR GBP JPY AUD NZD CAD CHF CNH SGD HKD SEK NOK DKK PLN HUF CZK MXN ZAR TRY BRL CLP COP ILS INR KRW THB TWD RON".split())
    alls = [s.name for s in mt5.symbols_get()]
    FX = [n for n in alls if len(n) == 6 and n[:3] in FIAT and n[3:] in FIAT]
    UNIV = FX + [n for n in ["XAUUSD","XAGUSD","XPTUSD","XPDUSD"] if n in alls] \
              + [n for n in ["NAS100","US30","US500","US2000","GER40","FRA40","UK100","EU50","AUS200","HK50","JP225"] if n in alls] \
              + [n for n in ["SpotCrude","SpotBrent","NatGas"] if n in alls]
    cl = {}; bps = {}
    for n in UNIV:
        mt5.symbol_select(n, True); info = mt5.symbol_info(n)
        r = mt5.copy_rates_range(n, mt5.TIMEFRAME_D1, dt.datetime(2015,1,1), dt.datetime(2026,7,1))
        if r is not None and len(r) > 500 and info and info.bid > 0:
            s = pd.DataFrame(r); s["time"] = pd.to_datetime(s["time"], unit="s")
            cl[n] = s.set_index("time")["close"]
            bps[n] = (info.spread * info.point) / info.bid * 1e4      # spread aller simple en bps
    mt5.shutdown()
    px = pd.DataFrame(cl); px.to_parquet(PANEL)
    pd.Series(bps, name="bps").to_csv(SPR)
    return px, pd.Series(bps)

if os.path.exists(PANEL):
    px = pd.read_parquet(PANEL); bps = pd.read_csv(SPR, index_col=0)["bps"]
else:
    px, bps = pull()

ret = np.log(px).diff()
FX_maj = ["EURUSD","GBPUSD","USDJPY","USDCHF","AUDUSD","NZDUSD","USDCAD"]
MAJORS = [c for c in FX_maj + ["XAUUSD","XAGUSD","US30","US500"] if c in px.columns]
WIDE = list(px.columns)

def backtest(cols, label):
    P = px[cols].copy()
    mom = np.log(P.shift(5) / P.shift(63))              # momentum 3m, skip 5j (causal)
    fwd = np.log(P.shift(-5) / P)                        # rendement 5j forward
    dates = P.index[63:-5:5]                             # rebalance hebdo
    ics = []; rets = []; prev_w = pd.Series(0.0, index=cols)
    for d in dates:
        m = mom.loc[d].dropna(); f = fwd.loc[d].reindex(m.index)
        ok = f.dropna().index; m = m[ok]; f = f[ok]
        if len(m) < 6: continue
        ics.append(spearmanr(m, f).correlation)
        z = (m - m.mean()) / (m.std() + 1e-9)
        k = max(1, len(m) // 5)
        w = pd.Series(0.0, index=cols)
        w[m.nlargest(k).index] = 1.0 / k; w[m.nsmallest(k).index] = -1.0 / k
        gross = (w.reindex(f.index).fillna(0) * f).sum()
        turn = (w - prev_w.reindex(cols).fillna(0)).abs()
        cost = (turn * (bps.reindex(cols).fillna(bps.median()) / 1e4)).sum()
        rets.append(gross - cost); prev_w = w
    ics = np.array(ics); rets = pd.Series(rets)
    ic_t = ics.mean() / (ics.std() / np.sqrt(len(ics)))
    ann = 52 / 5 * 5                                     # ~52 rebalances/an (hebdo)
    sh = rets.mean() / rets.std() * np.sqrt(52) if rets.std() > 0 else np.nan
    print(f"{label:24s}: rebal={len(rets)} IC={ics.mean():+.4f} t(IC)={ic_t:+.2f} "
          f"net%/an={rets.mean()*52*100:+.2f} Sharpe_net={sh:+.2f}")

print(f"Panel: {px.shape[1]} instruments, {px.index.min().date()}->{px.index.max().date()}")
print(f"Spread median bps={bps.median():.1f} (majors ~{bps[MAJORS].median():.1f}, tout ~{bps.median():.1f})\n")
backtest(MAJORS, "MAJORS seuls (~exp-003)")
backtest(WIDE,   "UNIVERS ELARGI")
