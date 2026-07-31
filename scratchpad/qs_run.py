"""Backtest every QuantifiedStrategies rule that survived the filter — to the letter.

Only strategies whose rules are STATED IN THE ARTICLE PROSE are here (the site gates its
formal "Trading Rules" box behind MemberPress, so the rest cannot be reproduced faithfully
— see RESEARCH_LOG_QS.md). Assets restricted to the user's classes: US + EU indices,
forex, gold, crypto.

Two conventions, both flagged in the report:
  * the articles are long-only and mostly carry NO stop; R needs one, so a MANDATORY
    2.5*ATR14 stop is added (project rule). The overnight family holds one bar, so the
    stop is nearly inert there.
  * everything runs on the LIVE cadence (see wiki/system.md).

    python scratchpad/qs_run.py
"""
import sys
sys.stdout.reconfigure(encoding='utf-8'); sys.path.insert(0, 'scratchpad')

import numpy as np
import pandas as pd

from qs_backtest import (load, atr, rsi, ibs, run_rule, stats, report,
                         US_IDX, EU_IDX, FX, GOLD, CRYPTO, COST)

IDX = US_IDX + EU_IDX
ALL = IDX + FX + GOLD + CRYPTO
T = True


def ma(c, n):   return c.rolling(n).mean()
def ema(c, n):  return c.ewm(span=n, adjust=False).mean()


# ---------------------------------------------------------------------------------
# Each entry: name -> (entry_fn, exit_fn, assets, kwargs).  entry/exit take the OHLC
# frame and return a boolean Series on CLOSED bars.
# ---------------------------------------------------------------------------------
def qs_exit(d):                      # "the QS exit": close > yesterday's high
    return d['close'] > d['high'].shift(1)


STRATS = {
    # ---- A. overnight family (buy the close, exit the next open) -----------------
    'A1 overnight, inconditionnel':
        (lambda d: pd.Series(T, d.index), lambda d: pd.Series(T, d.index), ALL, {}),
    'A2 overnight, 3 cloutres en baisse':
        (lambda d: (d['close'] < d['close'].shift(1)) & (d['close'].shift(1) < d['close'].shift(2))
                   & (d['close'].shift(2) < d['close'].shift(3)),
         lambda d: pd.Series(T, d.index), ALL, {}),
    'A3 overnight, plus-bas 5j + cloture>ouverture':
        (lambda d: (d['open'] <= d['low'].rolling(5).min()) & (d['close'] > d['open']),
         lambda d: pd.Series(T, d.index), ALL, {}),
    'A4 overnight, filtre MA200':
        (lambda d: d['close'] > ma(d['close'], 200), lambda d: pd.Series(T, d.index), ALL, {}),

    # ---- B. mean reversion, exit on strength -------------------------------------
    'B1 inside day -> QS exit':
        (lambda d: (d['high'] < d['high'].shift(1)) & (d['low'] > d['low'].shift(1)),
         qs_exit, ALL, {}),
    'B2 Turnaround Tuesday (lundi -1%)':
        (lambda d: (d.index.dayofweek == 0) & (d['close'] <= d['close'].shift(1) * 0.99),
         lambda d: pd.Series(T, d.index), IDX, {'max_hold': 1}),
    'B3 Connors 3-day high/low':
        (lambda d: (d['close'] > ma(d['close'], 200)) & (d['close'] < ma(d['close'], 5))
                   & (d['high'] < d['high'].shift(1)) & (d['high'].shift(1) < d['high'].shift(2))
                   & (d['low'] < d['low'].shift(1)) & (d['low'].shift(1) < d['low'].shift(2)),
         lambda d: d['close'] > ma(d['close'], 5), ALL, {}),
    'B4 Donchian bas 20 -> QS exit':
        (lambda d: d['close'] < d['low'].rolling(20).min().shift(1), qs_exit, ALL, {}),
    'B5 Connors %b (MA200, %b<0.2 -> >0.8)':
        (lambda d: (d['close'] > ma(d['close'], 200))
                   & (((d['close'] - (ma(d['close'], 20) - 2 * d['close'].rolling(20).std()))
                       / (4 * d['close'].rolling(20).std())) < 0.2),
         lambda d: ((d['close'] - (ma(d['close'], 20) - 2 * d['close'].rolling(20).std()))
                    / (4 * d['close'].rolling(20).std())) > 0.8, ALL, {}),
    'B6 Keltner: <bande basse -> ligne mediane':
        (lambda d: d['close'] < ema(d['close'], 20) - 2 * atr(d, 20),
         lambda d: d['close'] > ema(d['close'], 20), ALL, {}),
    'B7 IBS<0.2 -> >0.8  (= brique 4, controle)':
        (lambda d: ibs(d) < 0.2, lambda d: ibs(d) > 0.8, ALL, {}),

    # ---- C. trend / crossovers ---------------------------------------------------
    'C1 croisement 9 EMA':
        (lambda d: d['close'] > ema(d['close'], 9), lambda d: d['close'] < ema(d['close'], 9),
         ALL, {'max_hold': 250}),
    'C2 croisement 20 EMA':
        (lambda d: d['close'] > ema(d['close'], 20), lambda d: d['close'] < ema(d['close'], 20),
         ALL, {'max_hold': 250}),
    'C3 MACD(12,26,9) croisement':
        (lambda d: (ema(d['close'], 12) - ema(d['close'], 26))
                   > (ema(d['close'], 12) - ema(d['close'], 26)).ewm(span=9, adjust=False).mean(),
         lambda d: (ema(d['close'], 12) - ema(d['close'], 26))
                   < (ema(d['close'], 12) - ema(d['close'], 26)).ewm(span=9, adjust=False).mean(),
         ALL, {'max_hold': 250}),
    'C4 Golden/Death cross 50-200':
        (lambda d: ma(d['close'], 50) > ma(d['close'], 200),
         lambda d: ma(d['close'], 50) < ma(d['close'], 200), ALL, {'max_hold': 500}),
    'C5 MA200 (long au-dessus)':
        (lambda d: d['close'] > ma(d['close'], 200), lambda d: d['close'] < ma(d['close'], 200),
         ALL, {'max_hold': 500}),
    'C6 MA 12 mois (~250j, or)':
        (lambda d: d['close'] > ma(d['close'], 250), lambda d: d['close'] < ma(d['close'], 250),
         ALL, {'max_hold': 500}),
    'C7 Donchian haut 20 + sortie 80j':
        (lambda d: d['close'] > d['high'].rolling(20).max().shift(1),
         lambda d: pd.Series(False, d.index), ALL, {'max_hold': 80}),
    'C8 Bollinger breakout (cloture>bande haute)':
        (lambda d: d['close'] > ma(d['close'], 20) + 2 * d['close'].rolling(20).std(),
         lambda d: d['close'] < ma(d['close'], 20), ALL, {'max_hold': 250}),
    'C9 ROC(12) croise zero':
        (lambda d: d['close'].pct_change(12) > 0, lambda d: d['close'].pct_change(12) < 0,
         ALL, {'max_hold': 250}),

    # ---- D. seasonality ----------------------------------------------------------
    # (turn-of-month is brick 2's family and is handled by edgelab/edges/turn_of_month.py)
}


def dow_month(d):
    """helpers for the calendar strategies"""
    m = pd.PeriodIndex(d.index.tz_localize(None), freq='M')
    tdom = pd.Series(np.arange(len(d)), index=d.index).groupby(m).rank().astype(int)
    size = pd.Series(m).map(pd.Series(m).value_counts().to_dict()).values
    return tdom.values, size


def add_seasonal():
    def tom_entry(d):                      # QS: long at the close on the 5th-last trading day
        tdom, size = dow_month(d)
        return pd.Series(tdom == size - 4, index=d.index)

    def expiry_week(d):                    # long at the close of the 3rd-Friday, hold 1 week
        i = d.index.tz_localize(None)
        third_fri = (i.dayofweek == 4) & (i.day > 14) & (i.day <= 21)
        return pd.Series(third_fri, index=d.index)

    STRATS['D1 turn-of-month (5e dernier jour, 7j)'] = (
        tom_entry, lambda d: pd.Series(False, d.index), ALL, {'max_hold': 7})
    STRATS['D2 semaine expiration (3e vendredi, 5j)'] = (
        expiry_week, lambda d: pd.Series(False, d.index), IDX + CRYPTO, {'max_hold': 5})


def main():
    add_seasonal()
    print(f"  {len(STRATS)} strategies x jusqu'a {len(ALL)} actifs — cadence live, stop 2.5*ATR14")
    out = []
    for name, (efn, xfn, assets, kw) in STRATS.items():
        rows = []
        for s in assets:
            try:
                d = load(s)
            except FileNotFoundError:
                continue
            t = run_rule(d, efn(d), xfn(d), sym=s, **kw)
            st = stats(t, s)
            st['strat'] = name
            if st['n'] >= 10:
                rows.append(st)
        if not rows:
            continue
        pool = pd.DataFrame(rows)
        # pooled t over all assets, and how many assets are individually positive
        allR = []
        for s in assets:
            try:
                d = load(s)
            except FileNotFoundError:
                continue
            t = run_rule(d, efn(d), xfn(d), sym=s, **kw)
            t = t[pd.to_datetime(t['exit_dt']) >= pd.Timestamp('2018-07-01', tz='UTC')] if len(t) else t
            if len(t):
                allR.append(t['R'].to_numpy())
        R = np.concatenate(allR) if allR else np.array([])
        tp = R.mean() / R.std(ddof=1) * np.sqrt(len(R)) if len(R) > 5 else np.nan
        out.append(dict(strat=name, n=len(R), t_pool=tp,
                        n_assets=len(pool), pos=(pool.ryr > 0).sum(),
                        best=pool.loc[pool.t.idxmax(), 'label'] if len(pool) else '-',
                        best_t=pool.t.max(), best_ryr=pool.loc[pool.t.idxmax(), 'ryr'],
                        e_r=R.mean() if len(R) else 0))
        pool.to_csv(f"scratchpad/qs_out_{name.split()[0]}.csv", index=False)
    res = pd.DataFrame(out).sort_values('t_pool', ascending=False)
    res.to_csv('scratchpad/qs_results.csv', index=False, encoding='utf-8')
    print('\n' + '=' * 104)
    print("  RESULTATS — poolés sur tous les actifs testés (2018-07+), long only, net de cout")
    print('=' * 104)
    print(f"  {'strategie':<46}{'n':>6}{'t pool':>8}{'E[R]':>8}{'actifs+':>9}{'meilleur actif':>22}{'t':>6}")
    for r in res.itertuples():
        print(f"  {r.strat:<46}{r.n:>6}{r.t_pool:>8.2f}{r.e_r:>+8.3f}"
              f"{f'{r.pos}/{r.n_assets}':>9}{r.best:>16} {r.best_ryr:>+5.1f}R{r.best_t:>6.2f}")


if __name__ == '__main__':
    main()
