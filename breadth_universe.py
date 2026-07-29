"""Mesure la BREADTH EFFECTIVE (N_eff) de l'univers prop Pepperstone elargi.
N_eff = paris independants = (Somme lambda)^2 / Somme(lambda^2) sur les valeurs propres de la
matrice de correlation des rendements D1 (participation ratio). Compare des sous-univers pour
voir si elargir (crosses FX, indices multi-region, metaux, energie) casse le mur du USD-only."""
import MetaTrader5 as mt5, datetime as dt, numpy as np, pandas as pd
mt5.initialize()
FIAT = set("USD EUR GBP JPY AUD NZD CAD CHF CNH SGD HKD SEK NOK DKK PLN HUF CZK MXN ZAR TRY BRL CLP COP ILS INR KRW THB TWD RON".split())
allsyms = [s.name for s in mt5.symbols_get()]
FX = [n for n in allsyms if len(n) == 6 and n[:3] in FIAT and n[3:] in FIAT]
METALS = [n for n in ["XAUUSD","XAGUSD","XPTUSD","XPDUSD"] if n in allsyms]
INDICES = [n for n in ["NAS100","US30","US500","US2000","GER40","FRA40","UK100","EU50","AUS200","HK50","JP225"] if n in allsyms]
ENERGY = [n for n in ["SpotCrude","SpotBrent","NatGas"] if n in allsyms]
UNIV = FX + METALS + INDICES + ENERGY
print(f"Univers prop: FX={len(FX)} metaux={len(METALS)} indices={len(INDICES)} energie={len(ENERGY)} | total={len(UNIV)}")

# pull D1 close
closes = {}
for n in UNIV:
    mt5.symbol_select(n, True)
    r = mt5.copy_rates_range(n, mt5.TIMEFRAME_D1, dt.datetime(2018,1,1), dt.datetime(2026,7,1))
    if r is not None and len(r) > 500:
        s = pd.DataFrame(r); s["time"] = pd.to_datetime(s["time"], unit="s")
        closes[n] = s.set_index("time")["close"]
mt5.shutdown()
px = pd.DataFrame(closes)
ret = np.log(px).diff()
# garde les colonnes avec assez d'historique commun
ret = ret.dropna(axis=1, thresh=int(0.6*len(ret)))
print(f"Instruments avec historique suffisant: {ret.shape[1]}")

def n_eff(cols):
    R = ret[cols].dropna()
    if R.shape[1] < 2: return len(cols), np.nan, np.nan
    C = R.corr().values
    w = np.linalg.eigvalsh(C)
    w = w[w > 1e-8]
    neff = (w.sum()**2) / (w**2).sum()          # participation ratio
    rho = (C[~np.eye(len(C), dtype=bool)]).mean()
    return len(cols), neff, rho

def present(cols): return [c for c in cols if c in ret.columns]
USD_MAJ = present(["EURUSD","GBPUSD","USDJPY","USDCHF","AUDUSD","NZDUSD","USDCAD","XAUUSD","XAGUSD","US30","US500"])
CROSSES = present([c for c in FX if "USD" not in c])
EM = present([c for c in FX if any(x in c for x in ["MXN","ZAR","TRY","BRL","CLP","COP","PLN","HUF","CZK","NOK","SEK","INR","KRW","THB","TWD","RON","SGD","HKD","DKK","CNH"])])

print(f"\n{'sous-univers':42s} {'N':>4s} {'N_eff':>6s} {'rho_moy':>8s}  IR@IC=0.01")
for name, cols in [
    ("USD majors + metaux + 2 indices (~exp-003)", USD_MAJ),
    ("+ crosses FX (EURJPY, GBPAUD...)", present(USD_MAJ+CROSSES)),
    ("+ EM FX (MXN,ZAR,TRY,PLN...)", present(USD_MAJ+CROSSES+EM)),
    ("+ indices multi-region (11)", present(USD_MAJ+CROSSES+EM+INDICES)),
    ("UNIVERS PROP COMPLET", list(ret.columns)),
]:
    N, neff, rho = n_eff(present(cols))
    ir = 0.01*np.sqrt(neff) if np.isfinite(neff) else np.nan
    print(f"{name:42s} {N:>4d} {neff:>6.1f} {rho:>8.2f}     {ir:.2f}")
print("\nN_eff = nb de paris INDEPENDANTS (participation ratio). IR@IC=0.01 = IR annuel atteignable")
print("avec une IC/pari de 0.01 (niveau exp-004). Cible pour un bon algo: IR ~1.5-2.")
