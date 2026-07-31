"""Generic daily-bar rule runner for the QuantifiedStrategies triage — measured in R.

Every QS strategy that survives the filter reduces to the same shape:
    entry  : a boolean condition on the CLOSED bar  -> fill at the NEXT bar's open
    exit   : a boolean condition on the CLOSED bar  -> fill at the NEXT bar's open
             (+ an optional explicit stop / target, + a max-hold)

So one runner covers them all, and it uses the project's conventions so the numbers are
comparable with the book:
  * LIVE cadence (one decision per bar rollover; no closing and re-opening inside a bar —
    see wiki/system.md and edgelab/edges/ibs.py);
  * a MANDATORY stop (``sl_atr`` x ATR14) even when the article gives none, because R is
    defined by the stop distance. Where the article DOES give a stop/target, pass it.
  * intrabar stop is gap-aware; stop wins ties (pessimistic).

    from qs_backtest import run_rule, load, stats
"""
import sys; sys.path.insert(0, '.')

from pathlib import Path

import numpy as np
import pandas as pd

MT5 = Path('data_cache_mt5')
# round-trip cost in PRICE units, per instrument (Pepperstone-realistic, as used by the book)
COST = {'US500': 0.6, 'NAS100': 2.0, 'US30': 4.0, 'US2000': 0.5,
        'GER40': 2.0, 'FRA40': 1.5, 'UK100': 1.5, 'NETH25': 0.3, 'SWI20': 4.0,
        'XAUUSD': 0.35, 'EURUSD': 0.00012, 'GBPUSD': 0.00016, 'USDJPY': 0.016,
        'AUDUSD': 0.00016, 'USDCAD': 0.00020, 'USDCHF': 0.00020, 'EURJPY': 0.020,
        'BTCUSD': 35.0, 'ETHUSD': 2.0}
US_IDX = ('US500', 'NAS100', 'US30', 'US2000')
EU_IDX = ('GER40', 'FRA40', 'UK100', 'NETH25', 'SWI20')
FX = ('EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD', 'USDCAD', 'USDCHF', 'EURJPY')
GOLD = ('XAUUSD',)
CRYPTO = ('BTCUSD', 'ETHUSD')
ALL = US_IDX + EU_IDX + FX + GOLD + CRYPTO


def load(sym: str) -> pd.DataFrame:
    for ext in ('.parquet', '.csv'):
        p = MT5 / f'{sym}_D1{ext}'
        if p.exists():
            d = pd.read_parquet(p) if ext == '.parquet' else pd.read_csv(p)
            d.columns = [c.lower() for c in d.columns]
            d['t'] = pd.to_datetime(d['time'], utc=True)
            d = d.set_index('t')[['open', 'high', 'low', 'close']].astype(float).sort_index()
            return d[~d.index.duplicated()]
    raise FileNotFoundError(sym)


def atr(d: pd.DataFrame, n: int = 14) -> pd.Series:
    h, l, c = d['high'], d['low'], d['close']
    pc = c.shift(1)
    tr = pd.concat([(h - l), (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / n, adjust=False).mean()


def rsi(c: pd.Series, n: int = 14) -> pd.Series:
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn)


def ibs(d: pd.DataFrame) -> pd.Series:
    rng = (d['high'] - d['low']).replace(0, np.nan)
    return (d['close'] - d['low']) / rng


def run_rule(d: pd.DataFrame, entry: pd.Series, exit_: pd.Series, *, sym: str,
             direction: int = 1, sl_atr: float = 2.5, tp_atr: float | None = None,
             max_hold: int = 30, cost: float | None = None) -> pd.DataFrame:
    """Entry/exit booleans on CLOSED bars -> trades in R. See module docstring."""
    cost = COST.get(sym, 0.0) if cost is None else cost
    o, h, l = (d[x].to_numpy() for x in ('open', 'high', 'low'))
    a = atr(d).shift(1).to_numpy()          # prev-bar ATR: known at the entry decision
    en = entry.reindex(d.index).fillna(False).to_numpy().astype(bool)
    ex = exit_.reindex(d.index).fillna(False).to_numpy().astype(bool)
    idx, n = d.index, len(d)
    tr, in_pos, ei, ep, risk, stop, take = [], False, -1, 0.0, 0.0, 0.0, None

    def rec(t, px, why):
        R = direction * (px - ep) / risk - cost / risk
        tr.append({'entry_dt': idx[ei], 'exit_dt': idx[t], 'entry': ep, 'exit': px,
                   'reason': why, 'bars': t - ei, 'r_dist': risk, 'R': R})

    for t in range(1, n):
        if in_pos:                                    # (1) rollover exit at this bar's open
            if ex[t - 1] or (t - 1 - ei) >= max_hold:
                rec(t, o[t], 'signal' if ex[t - 1] else 'time'); in_pos = False
        if not in_pos and en[t - 1] and np.isfinite(a[t - 1]) and a[t - 1] > 0:
            ei, ep = t, o[t]
            risk = sl_atr * a[t - 1]
            stop = ep - direction * risk
            take = ep + direction * tp_atr * a[t - 1] if tp_atr else None
            in_pos = True
        if in_pos:                                    # (2) intrabar barriers, stop wins ties
            hit_s = l[t] <= stop if direction > 0 else h[t] >= stop
            hit_t = take is not None and (h[t] >= take if direction > 0 else l[t] <= take)
            if hit_s:
                px = stop if (o[t] >= stop if direction > 0 else o[t] <= stop) else o[t]
                rec(t, px, 'stop'); in_pos = False
            elif hit_t:
                rec(t, take, 'take'); in_pos = False
    return pd.DataFrame(tr)


def stats(t: pd.DataFrame, label: str = '', start: str = '2018-07-01') -> dict:
    if t is None or t.empty:
        return {'label': label, 'n': 0, 't': np.nan, 'ryr': 0.0, 'pf': np.nan, 'pyrs': '0/0'}
    t = t[pd.to_datetime(t['exit_dt']) >= pd.Timestamp(start, tz='UTC')]
    if len(t) < 5:
        return {'label': label, 'n': len(t), 't': np.nan, 'ryr': 0.0, 'pf': np.nan, 'pyrs': '0/0'}
    R = t['R'].to_numpy()
    yrs = max((t['exit_dt'].max() - t['exit_dt'].min()).days / 365.25, 0.5)
    yr = t.set_index('exit_dt')['R'].groupby(lambda z: z.year).sum()
    loss = -R[R < 0].sum()
    return {'label': label, 'n': len(R), 'ryr': R.sum() / yrs,
            't': R.mean() / R.std(ddof=1) * np.sqrt(len(R)),
            'pf': R[R > 0].sum() / loss if loss > 0 else np.inf,
            'e_r': R.mean(), 'pyrs': f'{int((yr > 0).sum())}/{len(yr)}'}


def report(rows, title):
    print('\n' + '=' * 96); print(f'  {title}'); print('=' * 96)
    print(f"  {'strategie / actif':<44}{'n':>5}{'R/an':>8}{'t':>7}{'PF':>6}{'E[R]':>8}{'+ans':>7}")
    for r in rows:
        if not r['n']:
            print(f"  {r['label']:<44}{'aucun trade':>33}"); continue
        print(f"  {r['label']:<44}{r['n']:>5}{r['ryr']:>+8.2f}{r['t']:>7.2f}"
              f"{r['pf']:>6.2f}{r.get('e_r',0):>+8.3f}{r['pyrs']:>7}")
