"""Monte Carlo of the FROZEN 3-brick portfolio, static-DD prop firm.  (canonical, 2026-07-29)

NO COMPOUNDING: 1R = risk% of the INITIAL balance (fixed-fractional), as prop accounts work.
The daily-R series is built the CORRECT way (two earlier bugs fixed, see wiki/system.md):
  * fixed-fractional TRADE-R on exit dates (sizing-invariant), NOT the engine's compounding
    mark-to-market (`res.returns` compounds -> understated crypto R);
  * a CALENDAR-day index (freq='D') so crypto WEEKEND exits are kept (freq='B' dropped them).
Correctness check: the MC median must match the historical backtest (both +37.9 R/yr).

Bricks: NAS100 US-open ATR-breakout (low-vol) + XAU turn-of-month + MACD(12,26,9)+RSI BTC+ETH.
Run from repo root:  python edgelab/reports/monte_carlo_static.py
Outputs: (0) full 1-yr R distribution, (1) +15%/-10%static/-5% challenge time-to-pass by sizing,
         (2) funded (-10% static, monthly payout resets to initial) optimal sizing.
"""
import sys; sys.path.insert(0, '.')
import numpy as np, pandas as pd
from pathlib import Path
from edgelab.config import load_config
from edgelab.backtest.engine import BacktestEngine
from edgelab.backtest.costs import CostModel
from edgelab.intraday.atr_breakout import run_atr_breakout, ATRBreakParams
from edgelab.edges.turn_of_month import run_turn_of_month, TurnOfMonthParams

CC = Path('data_cache_crypto'); cfg = load_config(); START = pd.Timestamp('2018-01-01')
eng = BacktestEngine(cfg, cost_model=CostModel(10, 3, {'BTCUSD': 5, 'ETHUSD': 8}))


def load(s):
    d = pd.read_parquet(CC / f'{s}_D1.parquet'); d['time'] = pd.to_datetime(d['time'], utc=True)
    return d.set_index('time')[['open', 'high', 'low', 'close']].assign(volume=0).astype(float).sort_index()


def rsi(c, n=14):
    dd = c.diff(); up = dd.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-dd.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean(); return 100 - 100 / (1 + up / dn)


def macd_rsi(d):
    c = d['close']; m = c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
    sig = m.ewm(span=9, adjust=False).mean(); r = rsi(c)
    base = (m > sig).astype(int) - (m < sig).astype(int)
    return base.where(((base > 0) & (r > 50)) | ((base < 0) & (r < 50)), 0).fillna(0).astype(int)


def build_daily_R():
    """Fixed-fractional trade-R on exit dates, all 3 bricks, on a CALENDAR-day index."""
    t1 = run_atr_breakout('NAS100', ATRBreakParams(regime_mode='low', direction='both'), 'M1').trades
    nas = pd.Series(t1['R'].values, index=pd.to_datetime(t1['exit_time'])).groupby(lambda x: x.normalize()).sum()
    g0 = run_turn_of_month('XAUUSD', TurnOfMonthParams(sl_atr=1.5))
    gold = pd.Series(g0['R'].values, index=pd.to_datetime(g0['date'])).groupby(level=0).sum()
    cr = []
    for s in ('BTCUSD', 'ETHUSD'):
        tr = eng.run(load(s), macd_rsi(load(s)), s, 'x').trades
        cr.append(pd.Series(tr['ret'].values, index=pd.to_datetime(tr['exit_time'])))
    crypto = pd.concat(cr).groupby(lambda x: pd.Timestamp(x).tz_localize(None).normalize()).sum()
    for x in (nas, gold, crypto):
        x.index = pd.to_datetime(x.index).tz_localize(None) if getattr(x.index, 'tz', None) else pd.to_datetime(x.index)
    nas, gold, crypto = [x[x.index >= START] for x in (nas, gold, crypto)]
    end = max(nas.index.max(), gold.index.max(), crypto.index.max())
    idx = pd.date_range(START, end, freq='D')  # calendar -> keep crypto weekends
    R = (nas.reindex(idx).fillna(0) + gold.reindex(idx).fillna(0) + crypto.reindex(idx).fillna(0)).values
    return R, (nas, gold, crypto), (START, end)


def main():
    R, (nas, gold, crypto), (start, end) = build_daily_R()
    years = (end - start).days / 365.25; active = R[R != 0]
    rng = np.random.default_rng(7); B = 14

    def path(L):
        o = []
        while len(o) < L:
            st = rng.integers(0, len(R) - B); o.extend(R[st:st + B])
        return np.array(o[:L])

    print('=' * 74)
    print('  0) FULL MONTE-CARLO STATS  (no compounding, 1R = risk% of INITIAL balance)')
    print('=' * 74)
    print(f'  History {start.date()}..{end.date()} ({years:.1f}y) | per brick R/yr: '
          f'NAS {nas.sum()/years:+.1f}  gold {gold.sum()/years:+.1f}  crypto {crypto.sum()/years:+.1f}')
    cumH = np.cumsum(R); mddH = (np.maximum.accumulate(cumH) - cumH).max()
    print(f'  Historical: total {R.sum():+.0f}R = {R.sum()/years:+.1f} R/yr | maxDD {mddH:.1f}R | '
          f'RoMaD {(R.sum()/years)/mddH:.2f} | Sharpe {active.mean()/active.std()*np.sqrt(252):.2f} | '
          f'worst day {R.min():+.2f}R')
    N = 40000; paths = np.array([path(365) for _ in range(N)]); cum = np.cumsum(paths, axis=1)
    annual = cum[:, -1]; mddR = (np.maximum.accumulate(cum, axis=1) - cum).max(axis=1)
    print(f'\n  1-YEAR distribution ({N} sims): P(profit yr)={(annual>0).mean():.1%}')
    print(f'  {"pct":>5} {"annual R":>10} {"maxDD R":>9}')
    for p in (5, 25, 50, 75, 95):
        print(f'  {p:>4}th {np.percentile(annual,p):>+9.1f}R {np.percentile(mddR,p):>8.1f}R')
    print(f'  mean {annual.mean():+.1f}R | maxDD 99th {np.percentile(mddR,99):.1f}R worst {mddR.max():.1f}R')

    print('\n' + '=' * 74)
    print('  1) CHALLENGE  target +15% | static max DD -10% (floor 90%) | daily -5%')
    print('=' * 74)
    pathsC = np.array([path(730) for _ in range(N)])
    print(f'  {"risk":>6} {"P(PASS)":>8} {"P(failDD)":>9} {"P(daily)":>8} {"med months":>11}')
    for r in (0.005, 0.0075, 0.01, 0.0125, 0.015, 0.02):
        T = 0.15 / r; DD = 0.10 / r; DAY = 0.05 / r; days = []; npass = nfd = nfl = 0
        for k in range(N):
            e = 0.0; res = None
            for t, x in enumerate(pathsC[k]):
                if x <= -DAY: res = 'fl'; break
                e += x
                if e <= -DD: res = 'fd'; break
                if e >= T: res = 'ps'; days.append(t + 1); break
            if res == 'ps': npass += 1
            elif res == 'fd': nfd += 1
            elif res == 'fl': nfl += 1
        mo = f'{np.median(days)/30.44:.1f}mo' if days else '--'
        print(f'  {r*100:>5.2f}% {npass/N:>8.1%} {nfd/N:>9.1%} {nfl/N:>8.1%} {mo:>11}')

    print('\n' + '=' * 74)
    print('  2) FUNDED  static -10% DD | monthly payout resets balance to initial')
    print('=' * 74)
    pathsF = np.array([path(365) for _ in range(N)]); MO = 30
    print(f'  {"risk":>6} {"E[wd %/yr]":>11} {"med %/yr":>9} {"P(ruin/yr)":>11}')
    for r in (0.005, 0.0075, 0.01, 0.0125, 0.015, 0.02):
        DD = 0.10 / r; wtot = np.zeros(N); ruin = 0
        for k in range(N):
            e = 0.0; w = 0.0
            for t, x in enumerate(pathsF[k]):
                e += x
                if e <= -DD: ruin += 1; break
                if (t + 1) % MO == 0 and e > 0: w += e; e = 0.0
            wtot[k] = w * r * 100
        print(f'  {r*100:>5.2f}% {wtot.mean():>10.1f}% {np.median(wtot):>8.1f}% {ruin/N:>11.1%}')


if __name__ == '__main__':
    main()
