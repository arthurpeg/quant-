"""Re-evaluate EVERY t>2 candidate from the three screens on the criterion that matters.

Correction of method (user, 2026-07-31), on two counts:
  1. A family already used by a brick is NOT disqualified. The criterion is decorrelation
     from the CURRENT bricks + book improvement, not novelty of the indicator.
  2. The multiple-testing bar (t~2.9-3.3) is a FLAG, not a filter. The project's gate is
     t>2 for a pre-registered test; a sweep candidate at t>2 must be VALIDATED, not binned.
     Screening it out was the wrong call.

So: take every (strategy x asset) pair that reached t>2 in the quantifiedstrategies screen,
the quantocracy screen and the code-corpus screen, and ask the real questions —
    * what is its max |corr| to the four bricks?
    * what does it do to the book at EQUAL RISK?
Ranked by book impact. Anything that survives then goes through the full battery.

    python scratchpad/candidates_eval.py
"""
import sys; sys.path.insert(0, '.'); sys.path.insert(0, 'scratchpad')
sys.stdout.reconfigure(encoding='utf-8')

import numpy as np
import pandas as pd

from edgelab.reports.monte_carlo_static import build_daily_R, START
from qs_backtest import load, atr, ibs, run_rule, stats

DAILY_LIMIT, TOTAL_DD = 0.05, 0.10


def ma(c, n):   return c.rolling(n).mean()
def ema(c, n):  return c.ewm(span=n, adjust=False).mean()
def wr(d, n=14):
    hh, ll = d['high'].rolling(n).max(), d['low'].rolling(n).min()
    return -100 * (hh - d['close']) / (hh - ll)


def supertrend(d, per=10, mult=3.0):
    a = atr(d, per); hl2 = (d['high'] + d['low']) / 2
    u = (hl2 - mult * a).to_numpy().copy(); l = (hl2 + mult * a).to_numpy().copy()
    c = d['close'].to_numpy(); dirn = np.ones(len(d))
    for i in range(1, len(d)):
        if c[i - 1] > u[i - 1]: u[i] = max(u[i], u[i - 1])
        if c[i - 1] < l[i - 1]: l[i] = min(l[i], l[i - 1])
        dirn[i] = 1 if c[i] > l[i - 1] else (-1 if c[i] < u[i - 1] else dirn[i - 1])
    return pd.Series(dirn, index=d.index)


def psar(d, af0=0.02, afmax=0.2):
    h = d['high'].to_numpy(); l = d['low'].to_numpy(); n = len(d)
    dirn = np.ones(n); af = af0; ep = h[0]; sar = l[0]
    for i in range(1, n):
        sar = sar + af * (ep - sar)
        if dirn[i - 1] > 0:
            if l[i] < sar: dirn[i] = -1; sar = ep; ep = l[i]; af = af0
            else:
                dirn[i] = 1
                if h[i] > ep: ep = h[i]; af = min(af + af0, afmax)
        else:
            if h[i] > sar: dirn[i] = 1; sar = ep; ep = h[i]; af = af0
            else:
                dirn[i] = -1
                if l[i] < ep: ep = l[i]; af = min(af + af0, afmax)
    return pd.Series(dirn, index=d.index)


def heikin(d):
    hc = (d['open'] + d['high'] + d['low'] + d['close']) / 4
    ho = (d['open'].shift(1) + d['close'].shift(1)) / 2
    return (hc > ho).astype(int)


def bb(d, n=20, k=2):
    m = ma(d['close'], n); s = d['close'].rolling(n).std()
    return m - k * s, m, m + k * s


# every (name, asset, entry, exit, kwargs) that reached t>2 in a screen
CAND = [
    ('IBS US500',            'US500',  lambda d: ibs(d) < 0.2, lambda d: ibs(d) > 0.8, {}),
    ('IBS US2000',           'US2000', lambda d: ibs(d) < 0.2, lambda d: ibs(d) > 0.8, {}),
    ('IBS US30',             'US30',   lambda d: ibs(d) < 0.2, lambda d: ibs(d) > 0.8, {}),
    ('IBS GER40',            'GER40',  lambda d: ibs(d) < 0.2, lambda d: ibs(d) > 0.8, {}),
    ('Turnaround Tuesday',   'NAS100', lambda d: (d.index.dayofweek == 0) & (d['close'] <= d['close'].shift(1) * .99),
                                       lambda d: pd.Series(True, d.index), {'max_hold': 1}),
    ('Keltner bande basse',  'NETH25', lambda d: d['close'] < ema(d['close'], 20) - 2 * atr(d, 20),
                                       lambda d: d['close'] > ema(d['close'], 20), {}),
    ('Keltner bande basse',  'UK100',  lambda d: d['close'] < ema(d['close'], 20) - 2 * atr(d, 20),
                                       lambda d: d['close'] > ema(d['close'], 20), {}),
    ('ROC(12) zero',         'US30',   lambda d: d['close'].pct_change(12) > 0,
                                       lambda d: d['close'].pct_change(12) < 0, {'max_hold': 250}),
    ('Overnight + MA200',    'XAUUSD', lambda d: d['close'] > ma(d['close'], 200),
                                       lambda d: pd.Series(True, d.index), {}),
    ('Overnight nu',         'XAUUSD', lambda d: pd.Series(True, d.index),
                                       lambda d: pd.Series(True, d.index), {}),
    ('MACD croisement',      'BTCUSD', lambda d: (ema(d['close'], 12) - ema(d['close'], 26)) > (ema(d['close'], 12) - ema(d['close'], 26)).ewm(span=9, adjust=False).mean(),
                                       lambda d: (ema(d['close'], 12) - ema(d['close'], 26)) < (ema(d['close'], 12) - ema(d['close'], 26)).ewm(span=9, adjust=False).mean(), {'max_hold': 250}),
    ('20 EMA',               'US500',  lambda d: d['close'] > ema(d['close'], 20),
                                       lambda d: d['close'] < ema(d['close'], 20), {'max_hold': 250}),
    ('Donchian20 + 80j',     'NAS100', lambda d: d['close'] > d['high'].rolling(20).max().shift(1),
                                       lambda d: pd.Series(False, d.index), {'max_hold': 80}),
    ('Bollinger breakout',   'ETHUSD', lambda d: d['close'] > bb(d)[2],
                                       lambda d: d['close'] < bb(d)[1], {'max_hold': 250}),
    ('Semaine expiration',   'US500',  lambda d: pd.Series((d.index.tz_localize(None).dayofweek == 4) & (d.index.tz_localize(None).day > 14) & (d.index.tz_localize(None).day <= 21), d.index),
                                       lambda d: pd.Series(False, d.index), {'max_hold': 5}),
    ('PSAR',                 'XAUUSD', lambda d: psar(d) > 0, lambda d: psar(d) < 0, {'max_hold': 250}),
    ('PSAR',                 'BTCUSD', lambda d: psar(d) > 0, lambda d: psar(d) < 0, {'max_hold': 250}),
    ('Ichimoku > nuage',     'XAUUSD', lambda d: (d['close'] > ((d['high'].rolling(9).max() + d['low'].rolling(9).min()) / 2).shift(26)) & (d['close'] > ((d['high'].rolling(26).max() + d['low'].rolling(26).min()) / 2).shift(26)),
                                       lambda d: d['close'] < ((d['high'].rolling(9).max() + d['low'].rolling(9).min()) / 2).shift(26), {'max_hold': 250}),
    ('Heikin-Ashi',          'BTCUSD', lambda d: heikin(d) > 0, lambda d: heikin(d) == 0, {'max_hold': 250}),
    ('Heikin-Ashi',          'XAUUSD', lambda d: heikin(d) > 0, lambda d: heikin(d) == 0, {'max_hold': 250}),
    ('Pivot classique',      'BTCUSD', lambda d: d['close'] > ((d['high'] + d['low'] + d['close']) / 3).shift(1),
                                       lambda d: d['close'] < ((d['high'] + d['low'] + d['close']) / 3).shift(1), {'max_hold': 250}),
    ('Williams %R',          'GER40',  lambda d: wr(d) < -80, lambda d: wr(d) > -20, {}),
    ('Supertrend',           'XAUUSD', lambda d: supertrend(d) > 0, lambda d: supertrend(d) < 0, {'max_hold': 250}),
]


def book_stats(parts, years):
    R = sum(parts).to_numpy(); cum = np.cumsum(R)
    mdd = float((np.maximum.accumulate(cum) - cum).max()); act = R[R != 0]
    ryr = R.sum() / years
    r_max = min(DAILY_LIMIT / abs(R.min()), TOTAL_DD / mdd)
    return ryr, mdd, ryr / mdd, act.mean() / act.std() * np.sqrt(252), ryr * r_max * 100


def main():
    R, parts, (s0, e0), _ = build_daily_R()
    years = (e0 - s0).days / 365.25
    idx = pd.date_range(s0, e0, freq='D')
    base_ryr, base_mdd, base_romad, base_sh, base_pct = book_stats(parts, years)
    print(f"  BOOK ACTUEL: {base_ryr:+.1f} R/an | maxDD {base_mdd:.1f} | RoMaD {base_romad:.2f} "
          f"| Sharpe {base_sh:.2f} | {base_pct:.1f} %/an a risque egal\n")
    names = ['NAS(b1)', 'or(b2)', 'crypto(b3)', 'IBS-NAS(b4)']

    rows = []
    for nm, sym, efn, xfn, kw in CAND:
        try:
            d = load(sym)
        except FileNotFoundError:
            continue
        t = run_rule(d, efn(d), xfn(d), sym=sym, sl_atr=2.5, **kw)
        st = stats(t, f'{nm} {sym}')
        if st['n'] < 15 or not np.isfinite(st['t']):
            continue
        ix = pd.DatetimeIndex(pd.to_datetime(t['exit_dt']))
        ix = (ix.tz_localize(None) if ix.tz is not None else ix).normalize()
        s = pd.Series(t['R'].to_numpy(), index=ix).groupby(level=0).sum()
        s = s[s.index >= START].reindex(idx).fillna(0)
        cors = [s.corr(p) for p in parts]
        mx = max(abs(c) for c in cors)
        ryr, mdd, romad, sh, pct = book_stats(list(parts) + [s], years)
        cu = np.cumsum(s.to_numpy()); own = (np.maximum.accumulate(cu) - cu).max()
        rows.append(dict(nom=f'{nm} {sym}', n=st['n'], t=st['t'], ryr=st['ryr'],
                         romad_seul=st['ryr'] / own if own > 0 else np.nan,
                         cmax=mx, cb4=cors[3], d_pct=pct - base_pct,
                         d_romad=romad - base_romad, d_sh=sh - base_sh))
    x = pd.DataFrame(rows).sort_values('d_pct', ascending=False)
    print(f"  {'candidat':<26}{'n':>5}{'t':>6}{'R/an':>7}{'RoMaD':>7}{'|corr|max':>10}"
          f"{'corr b4':>9}{'Δ%/an':>8}{'ΔRoMaD':>8}{'ΔSharpe':>9}")
    for r in x.itertuples():
        print(f"  {r.nom:<26}{r.n:>5}{r.t:>6.2f}{r.ryr:>+7.1f}{r.romad_seul:>7.2f}"
              f"{r.cmax:>10.3f}{r.cb4:>9.3f}{r.d_pct:>+8.2f}{r.d_romad:>+8.3f}{r.d_sh:>+9.3f}")
    x.to_csv('scratchpad/candidates_eval.csv', index=False, encoding='utf-8')
    good = x[(x.d_pct > 0) & (x.cmax < 0.30)]
    print(f"\n  -> {len(good)} candidats DECORRELES (|corr|<0.30) qui AMELIORENT le book")


if __name__ == '__main__':
    main()
