"""The battery the two named H1 cells never had.

  BTCUSD  Keltner_break_1.5   SL 3.0xATR14, TP 2R, 96-bar cap   n=1477  +27.1 R/yr  t=4.26
  XAUUSD  Meyers_6            SL 3.0xATR14, TP 2R, 24-bar cap   n=1972  +23.8 R/yr  t=3.91

Both were flagged from a screen and nothing else. They are high-frequency (185 and 250
trades/yr), which makes the COST STRESS the decisive test — friction scales with trade
count, and every H1 result in this project has died there. The other gates: the two exact
nulls, the split half against its own sign-permutation null, the per-year table, 1R
against the spread, and the MONTHLY correlation to the live bricks (the daily one lies on
sparse sleeves — but these are not sparse, so both are reported and should agree).
"""
import sys, warnings
sys.path.insert(0, 'scratchpad'); sys.path.insert(0, '.')
warnings.filterwarnings('ignore')
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import numpy as np
import pandas as pd

import kauf_lib as K
import tsam_rules as T
from kauf_battery import null_sign

CAND = [('BTCUSD', 'Keltner_break_1.5', 3.0, 2.0, 96),
        ('XAUUSD', 'Meyers_6', 3.0, 2.0, 24)]
NDRAW = 400


def daily(b, R, xi):
    t = pd.DatetimeIndex(b.time[xi]).tz_convert('UTC').tz_localize(None).normalize()
    return pd.Series(R, index=t).groupby(level=0).sum()


def perf(s):
    span = max((s.index.max() - s.index.min()).days / 365.25, 1e-9)
    c = s.cumsum(); dd = float((c.cummax() - c).max())
    cal = pd.date_range(s.index.min(), s.index.max(), freq='D')
    f = s.reindex(cal, fill_value=0.0)
    return (s.sum() / span, dd, (s.sum() / span) / dd if dd else np.nan,
            f.mean() / f.std() * np.sqrt(365) if f.std() else np.nan)


def main():
    bricks = pd.read_parquet('scratchpad/bricks_daily.parquet')
    series = {}
    for sym, rule, sl, tp, mb in CAND:
        b = K.Bars(sym, 'H1', source='cache', min_bars=5000)
        rules = T.all_rules(b)
        sig = rules[rule]
        idx = np.flatnonzero(sig != 0)
        lf = float((sig[idx] > 0).mean())
        tab = K.Table(b, sl, tp, mb, session=False)
        R, xi, ei = tab.walk_idx(idx, sig[idx])
        st = K.cell_stats(b, R, xi)
        series[(sym, rule)] = daily(b, R, xi)

        print('=' * 96)
        print(f'{sym} H1 {rule}   SL {sl}xATR14  TP {tp}R  cap {mb} bars  (long frac {lf:.2f})')
        print('=' * 96)
        yrs = (b.time[-1] - b.time[0]).days / 365.25
        print(f"  n={st['n']}  {st['n']/yrs:.0f}/yr  win {st['win']:.1%}  E[R] {st['ER']:+.4f}  "
              f"R/yr {st['Ryr']:+.1f}  PF {st['PF']:.3f}  t {st['t']:+.2f}  "
              f"maxDD {st['maxDD']:.1f}R  RoMaD {st['RoMaD']:.2f}")

        i = np.arange(b.n)
        pool = np.flatnonzero((i > K.WARMUP) & (i < b.n - 1))
        nA = K.null_ts(tab, pool, len(idx), lf, ndraw=NDRAW, rng=np.random.default_rng(1))
        nB = null_sign(tab, idx, lf, NDRAW, seed=2)
        print(f"  NULL A (random entry)      median {np.median(nA):+.2f}   "
              f"p = {float((nA >= st['t']).mean()):.3f}")
        print(f"  NULL B (sign permutation)  median {np.median(nB):+.2f}   "
              f"p = {float((nB >= st['t']).mean()):.3f}   <- the decisive one")

        dist = sl * b.atr[ei - 1]
        ratio = dist / b.spread_px[ei - 1]
        print(f'  1R vs spread: median {np.median(ratio):.0f}x  5th pct '
              f'{np.percentile(ratio, 5):.0f}x  min {ratio.min():.0f}x')

        yr = pd.Series(R, index=pd.DatetimeIndex(b.time[xi]).year).groupby(level=0).sum()
        print('  per year: ' + '  '.join(f'{y}:{v:+.0f}' for y, v in yr.items())
              + f'   ({int((yr > 0).sum())}/{len(yr)} +)')

        mid = b.n // 2
        for nm, sel in (('early', ei < mid), ('late', ei >= mid)):
            Rh = R[sel]
            ih = idx[idx < mid] if nm == 'early' else idx[idx >= mid]
            if len(Rh) < 30:
                continue
            nb = null_sign(tab, ih, float((sig[ih] > 0).mean()), 250, seed=3)
            th = K.tstat(Rh)
            print(f'  split {nm:<5} n={len(Rh):<5} R/yr={Rh.sum()/(yrs/2):+6.1f} t={th:+5.2f}'
                  f'  nullB={np.median(nb):+5.2f}  p={float((nb >= th).mean()):.3f}')

        print('  COST STRESS (the decisive test at this trade count):')
        for extra in (0, 2, 5, 10, 20):
            t2 = K.Table(b, sl, tp, mb, rt=b.cost(extra), session=False)
            Rc, xc, _ = t2.walk_idx(idx, sig[idx])
            s2 = K.cell_stats(b, Rc, xc)
            print(f'    +{extra:<3} pts/side  R/yr {s2["Ryr"]:+7.1f}  t {s2["t"]:+5.2f}  '
                  f'PF {s2["PF"]:.3f}  E[R] {s2["ER"]:+.4f}')
        print()

    print('=' * 96)
    print('CORRELATION TO THE LIVE BOOK')
    print('=' * 96)
    j = bricks.copy()
    for (sym, rule), s in series.items():
        j[f'{sym}_{rule}'] = s
    j = j.fillna(0.0)
    j = j.loc[j.index >= '2018-07-01']
    print('\ndaily R:')
    print(j.corr().round(3).to_string())
    print('\nMONTHLY R (the honest horizon):')
    print(j.resample('ME').sum().corr().round(3).to_string())

    book = j[['brick1_NAS', 'brick2_gold', 'brick3_crypto']].sum(axis=1)
    combos = {'book (b1+b2+b3)': book}
    for (sym, rule) in series:
        nm = f'{sym}_{rule}'
        combos[f'book + {rule} @1R'] = book + j[nm]
        combos[f'book + {rule} @0.5R'] = book + 0.5 * j[nm]
    print(f"\n{'config':<44}{'R/yr':>9}{'maxDD':>9}{'RoMaD':>8}{'Sharpe':>8}{'%/yr':>9}")
    for nm, s in combos.items():
        r, dd, ro, sh = perf(s)
        print(f'{nm:<44}{r:>+9.1f}{dd:>9.1f}{ro:>8.2f}{sh:>8.2f}'
              f'{100*(0.10/(2*dd))*r:>8.1f}%')


if __name__ == '__main__':
    main()
