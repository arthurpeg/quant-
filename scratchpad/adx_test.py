"""ADX_System.mq4 — test d'admission du projet: RoMaD standalone PUIS apport au
livre A RISQUE EGAL, net de tous couts FTMO. C'est le test qui a fait tomber
TSM-Coil et remonter l'ORB GER40; on l'applique ici sans le raccourcir.

La sleeve est INTRADAY (0 nuit) et sur INDICES -> swap 0 et commission 0 chez FTMO.
"""
import sys, os, json, itertools, warnings
sys.path.insert(0, 'scratchpad'); sys.path.insert(0, '.')
warnings.filterwarnings('ignore')
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import numpy as np, pandas as pd, importlib.util
import kauf_lib as K, mql_transpile as MT
from corpus_run import TF, FLOOR, struct_dist, session_bars
sp = importlib.util.spec_from_file_location('fs', 'scratchpad/ftmo_swaps.py')
FS = importlib.util.module_from_spec(sp); sp.loader.exec_module(FS)
from edgelab.reports.monte_carlo_static import simulate
import edgelab.reports.monte_carlo_static as MC

SIG = json.load(open('scratchpad/_inx/mql_specs.json'))['424e77c1cd10']['sides']


def series(sym, bracket):
    b = K.Bars(sym, TF[sym], source='inx', min_bars=5000)
    sb = session_bars(b); win = np.asarray(b.in_window, bool)
    a = np.where(win, MT.run_compiled(SIG, b), 0).astype(np.int8)
    if bracket.startswith('atr'):
        tab = K.Table(b, float(bracket[3:]), None, sb + 1, session=True, floor_spread=FLOOR)
        dist = np.maximum(float(bracket[3:]) * b.atr, FLOOR * b.spread_px)
    else:
        d = struct_dist(b, int(bracket[3:]))
        tab = K.Table(b, None, None, sb + 1, session=True, floor_spread=FLOOR,
                      dist_override=d)
        dist = np.maximum(d, FLOOR * b.spread_px)
    idx = np.flatnonzero(a != 0); idx = idx[idx > K.WARMUP]
    R, xi, ei = tab.walk_idx(idx, a[idx])
    t = pd.DatetimeIndex(b.time[ei]).tz_convert(None)
    return b, R, ei, t, dist


print('=' * 96)
print('  1) STANDALONE  (barre du projet: IBS 1.59, crypto 0.95, NAS 0.79, or 0.73, GER40-ORB 0.45)')
print('=' * 96)
print(f"{'actif':7s} {'bracket':8s} {'n':>5s} {'n/an':>6s} {'R/an':>7s} {'maxDD':>7s} "
      f"{'RoMaD':>6s} {'Sharpe':>7s} {'ans+':>6s} {'pireAn':>7s}")
KEEP = {}
for sym, br in (('GER40', 'str10'), ('GER40', 'atr1.5'), ('NAS100', 'atr1.5'),
                ('US500', 'atr1.5')):
    b, R, ei, t, dist = series(sym, br)
    yrs = (t.max() - t.min()).days / 365.25
    cum = np.cumsum(R); dd = float(np.max(np.maximum.accumulate(cum) - cum))
    s = pd.Series(R, index=t); yr = s.groupby(s.index.year).sum()
    dly = s.groupby(s.index.normalize()).sum()
    sh = dly.mean() / dly.std() * np.sqrt(252)
    print(f'{sym:7s} {br:8s} {len(R):5d} {len(R)/yrs:6.0f} {R.sum()/yrs:+7.2f} {dd:7.1f} '
          f'{(R.sum()/yrs)/dd:6.2f} {sh:7.2f} {int((yr>0).sum()):3d}/{len(yr):<2d} {yr.min():7.1f}')
    KEEP[(sym, br)] = (b, R, ei, t, dist)

print('\n' + '=' * 96)
print('  2) CORRELATION MENSUELLE aux sleeves du livre')
print('=' * 96)
fr = FS.build()
b, R, ei, t, dist = KEEP[('GER40', 'str10')]
mm = pd.Series(R, index=t); mm = mm.groupby(mm.index.normalize()).sum().resample('MS').sum()
for nm in ('b1 NAS ORB', 'b2 XAU ToM', 'b3 BTCUSD MACD', 'b4 NAS IBS', 'KAER NAS'):
    f = fr[nm]; s2 = pd.Series(f['R'].values, index=f['exit_time'])
    m2 = s2.groupby(s2.index.normalize()).sum().resample('MS').sum()
    x, y = mm.align(m2, join='inner', fill_value=0.0)
    print(f'  vs {nm:14s} {x.corr(y):+.3f}')

print('\n' + '=' * 96)
print('  3) APPORT AU LIVRE A RISQUE EGAL, net de tous couts FTMO')
print('=' * 96)
FS.SLEEVE_DIR['ADX'] = 0
for s_ in ('GER40', 'NAS100'):
    FS.SWAP_ANNUAL_PCT[(s_, 1)] = 0.0; FS.SWAP_ANNUAL_PCT[(s_, -1)] = 0.0
    FS.TRIPLE_DAY[s_] = 4; FS.COMM[s_] = 0.0
A = {'b1 NAS ORB': 1.0, 'b2 XAU ToM': 1.0, 'b3 BTCUSD MACD': 1.0,
     'b3 ETHUSD MACD': 1.0, 'b4 NAS IBS': 1.0, 'KAER NAS': 0.5}
MC.RISKS = (0.002, 0.0025, 0.003, 0.0035, 0.004, 0.005, 0.006, 0.0075, 0.01)


def addbook(label, key, w):
    b, R, ei, t, dist = KEEP[key]
    k = t >= FS.START
    fr['ADX'] = pd.DataFrame({'exit_time': t[k], 'symbol': key[0], 'R': R[k],
                              'stop_pct': (dist[ei] / b.o[ei])[k], 'units': 0.0})
    tot = FS.book_daily(fr, {**A, 'ADX': w} if w else A, 'all')
    m = FS.dmetrics(tot); mc = simulate(tot.values, N=9000, seed=7)
    bst = None
    for f in mc['fund']:
        if f['p_ruin'] <= 0.02 and (bst is None or f['mean_wd'] > bst['mean_wd']):
            bst = f
    print(f'  {label:34s} R/an {m["Ryr"]:6.2f} maxDD {m["maxDD"]:6.2f} '
          f'RoMaD {m["RoMaD"]:5.2f} Sharpe {m["Sharpe"]:5.2f} -> '
          f'{bst["mean_wd"]:5.1f}%/an (ruine {bst["p_ruin"]*100:.1f}%)')


addbook('A actuel (reference)', ('GER40', 'str10'), 0)
addbook('A + ADX GER40@0.5R', ('GER40', 'str10'), 0.5)
addbook('A + ADX GER40@1R', ('GER40', 'str10'), 1.0)
addbook('A + ADX NAS100@0.5R', ('NAS100', 'atr1.5'), 0.5)
