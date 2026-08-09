"""BATTERIE COMPLETE sur les 7 signaux retenus par la replication cross-actifs.

Choix de methode, declare: on evalue chaque signal sur UN SEUL bracket PRE-DECLARE
(SL 1.5 x ATR14, pas de cible, sortie forcee a la cloture, plancher 1R >= 25
spreads), identique pour les 7 et pour les 6 actifs. Prendre "le meilleur bracket
de chacun" reintroduirait exactement la selection que le classement par replication
venait d'eliminer.

Controles: Null A (derive/timing, 300 tirages), Null B (direction, 300), demi-
echantillons, pire annee civile, stress de cout, correlation mensuelle a la brique 1.
"""
import sys, os, json, warnings
sys.path.insert(0, 'scratchpad'); sys.path.insert(0, '.')
warnings.filterwarnings('ignore')
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import numpy as np, pandas as pd
import kauf_lib as K, inx_data as D
from corpus_run import TF, FLOOR, session_bars

SL, NDRAW = 1.5, 300
UNI = ['NAS100', 'US500', 'US30', 'GER40', 'FRA40', 'XAUUSD']
SIGS = [('pine', 'c8bfc91ba728', 'price-action pur'),
        ('pine', '40df7e9e367b', 'TrendFollow 52w/26w+Supertrend'),
        ('pine', '381cce4812bf', 'PUB_3Kjmk...'),
        ('pine', '8604779b1296', 'Bollinger+RSI+MA'),
        ('pine', 'c049a37ffeef', 'Stoch+EMA 25/50/100/200'),
        ('pine', '255f122d29a3', 'Volatility Breakout [Angel]'),
        ('mql', '424e77c1cd10', 'ADX_System.mq4')]

ps = json.load(open('scratchpad/_inx/pine_specs.json'))
ms = json.load(open('scratchpad/_inx/mql_specs.json'))
from tv_transpile import Spec
from tv_pine import F
import mql_transpile as MT

# brique 1 pour la correlation
from edgelab.intraday.atr_breakout import run_atr_breakout, ATRBreakParams
b1 = run_atr_breakout('NAS100', ATRBreakParams(regime_mode='low', direction='both'), 'M1').trades
b1s = pd.Series(b1['R'].values, index=pd.DatetimeIndex(pd.to_datetime(b1['exit_time'])).tz_localize(None))
b1m = b1s.groupby(b1s.index.normalize()).sum().resample('MS').sum()

print(f"{'signal':32s} {'actif':7s} {'n':>5s} {'t':>5s} {'A_p':>5s} {'B_p':>5s} "
      f"{'t_pre':>6s} {'t_rec':>6s} {'pireAn':>7s} {'t+10p':>6s} {'corrB1':>7s}")
res = []
for corp, sig, name in SIGS:
    for sym in UNI:
        try:
            b = K.Bars(sym, TF[sym], source='inx', min_bars=5000)
            win = np.asarray(b.in_window, bool)
            if corp == 'pine':
                df = b.d.copy(); df.index = df.index.tz_convert(D.SESSION[sym][0])
                L, S, *_ = Spec(ps[sig]['code'], {}).run(F(df, K.SPECS[sym]['point']))
                a = np.zeros(b.n, np.int8)
                a[np.asarray(L, bool) & win] = 1
                a[np.asarray(S, bool) & win & ~np.asarray(L, bool)] = -1
            else:
                a = np.where(win, MT.run_compiled(ms[sig]['sides'], b), 0).astype(np.int8)
            sb = session_bars(b)
            tab = K.Table(b, SL, None, sb + 1, session=True, floor_spread=FLOOR)
            idx = np.flatnonzero(a != 0); idx = idx[idx > K.WARMUP]
            if len(idx) < 40:
                continue
            R, xi, ei = tab.walk_idx(idx, a[idx])
            if len(R) < 40:
                continue
            t0 = K.tstat(R); lf = float((a[idx] > 0).mean()); h = len(R) // 2
            i = np.arange(b.n); pool = np.flatnonzero((i > K.WARMUP) & (i < b.n - 1) & win)
            nt = K.null_ts(tab, pool, len(R), lf, ndraw=NDRAW, rng=np.random.default_rng(7))
            pA = float((nt >= t0).mean())
            pB = np.nan
            if 0.02 < lf < 0.98:
                rng = np.random.default_rng(11); tb = []
                for _ in range(NDRAW):
                    Rb, _, _ = tab.walk_idx(idx, rng.permutation(a[idx]))
                    if len(Rb) > 20:
                        tb.append(K.tstat(Rb))
                pB = float((np.array(tb) >= t0).mean()) if tb else np.nan
            tt = pd.DatetimeIndex(b.time[ei]).tz_convert(None)
            s = pd.Series(R, index=tt)
            yr = s.groupby(s.index.year).sum()
            tb10 = K.Table(b, SL, None, sb + 1, rt=b.cost(extra_pts=10),
                           session=True, floor_spread=FLOOR)
            R10, _, _ = tb10.walk_idx(idx, a[idx])
            mm = s.groupby(s.index.normalize()).sum().resample('MS').sum()
            x, y = mm.align(b1m, join='inner', fill_value=0.0)
            c1 = x.corr(y)
            print(f'{name[:32]:32s} {sym:7s} {len(R):5d} {t0:5.2f} {pA:5.3f} '
                  f'{pB:5.3f} {K.tstat(R[:h]):6.2f} {K.tstat(R[h:]):6.2f} '
                  f'{yr.min():7.1f} {K.tstat(R10):6.2f} {c1:7.3f}', flush=True)
            res.append(dict(sig=sig, name=name, sym=sym, n=len(R), t=t0, pA=pA, pB=pB,
                            t_pre=K.tstat(R[:h]), t_rec=K.tstat(R[h:]),
                            worst_yr=float(yr.min()), t_cost10=K.tstat(R10), corr_b1=c1))
        except Exception as e:
            print(f'{name[:32]:32s} {sym:7s} ERREUR {type(e).__name__}', flush=True)
pd.DataFrame(res).to_csv('scratchpad/_inx/battery7.csv', index=False)
print('\n-> scratchpad/_inx/battery7.csv')
