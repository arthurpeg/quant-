"""Monte Carlo of the FROZEN 4-brick portfolio, static-DD prop firm.  (canonical, 2026-07-31)

NO COMPOUNDING: 1R = risk% of the INITIAL balance (fixed-fractional), as prop accounts work.
The daily-R series is built the CORRECT way (two earlier bugs fixed, see wiki/system.md):
  * fixed-fractional TRADE-R on exit dates (sizing-invariant), NOT the engine's compounding
    mark-to-market (`res.returns` compounds -> understated crypto R);
  * a CALENDAR-day index (freq='D') so crypto WEEKEND exits are kept (freq='B' dropped them).
Brick 3 uses the PEPPERSTONE crypto bars (data_cache_mt5) — the data the live runner
actually trades — not Yahoo. That makes this the LIVE-realistic book rather than the
Yahoo-optimistic one (Yahoo's longer history + different daily-close boundary).

Bricks: NAS100 US-open ATR-breakout (low-vol) + XAU turn-of-month + MACD(12,26,9)+RSI BTC+ETH
        + NAS100 IBS reversion (brick 4, added 2026-07-31 - see exp-009), priced on the
        LIVE driver cadence (run_ibs(cadence='live')) so the book is what can be traded.
Run from repo root:  python edgelab/reports/monte_carlo_static.py
Outputs: (0) full 1-yr R distribution, (1) +15%/-10%static/-5% challenge time-to-pass by sizing,
         (2) funded (-10% static, monthly payout resets to initial) optimal sizing.

`simulate()` is the single source of truth for the MC numbers: `main()` prints from it and
`build_reports.py` renders the HTML reports from it, so the two can never disagree.
"""
import sys; sys.path.insert(0, '.')
import numpy as np, pandas as pd
from pathlib import Path
from edgelab.config import load_config
from edgelab.backtest.engine import BacktestEngine
from edgelab.backtest.costs import CostModel
from edgelab.intraday.atr_breakout import run_atr_breakout, ATRBreakParams
from edgelab.edges.turn_of_month import run_turn_of_month, TurnOfMonthParams
from edgelab.edges.ibs import run_ibs, IBSParams

# Pepperstone crypto (the live feed). ETH history there starts 2018-06 -> window from 2018-07.
CC = Path('data_cache_mt5'); cfg = load_config(); START = pd.Timestamp('2018-07-01')
eng = BacktestEngine(cfg, cost_model=CostModel(10, 3, {'BTCUSD': 5, 'ETHUSD': 8}))

BRICKS = ('NAS100 breakout', 'Gold turn-of-month', 'Crypto MACD-RSI', 'NAS100 IBS reversion')
RISKS = (0.005, 0.0075, 0.01, 0.0125, 0.015, 0.02)


def load(s):
    d = pd.read_parquet(CC / f'{s}_D1.parquet'); d.columns = [c.lower() for c in d.columns]
    d['time'] = pd.to_datetime(d['time'], utc=True)
    return d.set_index('time')[['open', 'high', 'low', 'close']].assign(volume=0).astype(float).sort_index()


def rsi(c, n=14):
    dd = c.diff(); up = dd.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-dd.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean(); return 100 - 100 / (1 + up / dn)


def macd_rsi(d):
    c = d['close']; m = c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
    sig = m.ewm(span=9, adjust=False).mean(); r = rsi(c)
    base = (m > sig).astype(int) - (m < sig).astype(int)
    return base.where(((base > 0) & (r > 50)) | ((base < 0) & (r < 50)), 0).fillna(0).astype(int)


def _naive(x):
    """tz-naive DatetimeIndex from a Series or Index (the bricks mix UTC-aware and naive)."""
    ix = pd.DatetimeIndex(pd.to_datetime(x))
    return ix.tz_localize(None) if ix.tz is not None else ix


def build_daily_R():
    """Fixed-fractional trade-R on exit dates, all 4 bricks, on a CALENDAR-day index.

    Returns (R, per-brick daily series, (start, end), per-brick TRADE-R series). The trade
    series (one row per closed trade, indexed by exit datetime, in-window) is what the
    report derives trade counts, per-year activity and profit factor from — daily sums
    would merge same-day trades and understate both.
    """
    t1 = run_atr_breakout('NAS100', ATRBreakParams(regime_mode='low', direction='both'), 'M1').trades
    tr_nas = pd.Series(t1['R'].values, index=_naive(t1['exit_time']))
    g0 = run_turn_of_month('XAUUSD', TurnOfMonthParams(sl_atr=1.5))
    tr_gold = pd.Series(g0['R'].values, index=_naive(g0['date']))
    cr = []
    for s in ('BTCUSD', 'ETHUSD'):
        tr = eng.run(load(s), macd_rsi(load(s)), s, 'x').trades
        cr.append(pd.Series(tr['ret'].values, index=_naive(tr['exit_time'])))
    tr_crypto = pd.concat(cr).sort_index()
    # brick 4: IBS reversion, on the cadence the deployed driver actually runs
    # (cadence='live'; the exploratory 'literal' loop reads ~0.8 R/yr richer).
    i0 = run_ibs('NAS100', IBSParams(sl_atr=2.5), cadence='live')
    tr_ibs = pd.Series(i0['R'].values, index=_naive(i0['exit_dt']))

    tr = [x[x.index >= START] for x in (tr_nas, tr_gold, tr_crypto, tr_ibs)]
    dly = [x.groupby(x.index.normalize()).sum() for x in tr]
    end = max(x.index.max() for x in dly)
    idx = pd.date_range(START, end, freq='D')  # calendar -> keep crypto weekends
    parts = [x.reindex(idx).fillna(0) for x in dly]
    R = sum(parts).values
    return R, tuple(parts), (START, end), dict(zip(BRICKS, tr))


def simulate(R, N=40000, seed=7, B=14):
    """Block-bootstrap MC. Single source of truth for both the printout and the HTML report.

    Draw order is fixed (1-yr paths -> 2-yr challenge paths -> 1-yr funded paths) so the
    seed reproduces the same numbers on every run.
    """
    rng = np.random.default_rng(seed)

    def path(L):
        o = []
        while len(o) < L:
            st = rng.integers(0, len(R) - B); o.extend(R[st:st + B])
        return np.array(o[:L])

    # --- 0) one-year distribution -------------------------------------------------
    paths = np.array([path(365) for _ in range(N)]); cum = np.cumsum(paths, axis=1)
    annual = cum[:, -1]; mddR = (np.maximum.accumulate(cum, axis=1) - cum).max(axis=1)

    # --- 1) challenge --------------------------------------------------------------
    pathsC = np.array([path(730) for _ in range(N)]); chal = []
    for r in RISKS:
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
        chal.append(dict(risk=r, p_pass=npass / N, p_fail_dd=nfd / N, p_fail_daily=nfl / N,
                         med_months=(np.median(days) / 30.44 if days else None)))

    # --- 2) funded -----------------------------------------------------------------
    pathsF = np.array([path(365) for _ in range(N)]); MO = 30; fund = []
    for r in RISKS:
        DD = 0.10 / r; wtot = np.zeros(N); ruin = 0
        for k in range(N):
            e = 0.0; w = 0.0
            for t, x in enumerate(pathsF[k]):
                e += x
                if e <= -DD: ruin += 1; break
                if (t + 1) % MO == 0 and e > 0: w += e; e = 0.0
            wtot[k] = w * r * 100
        fund.append(dict(risk=r, mean_wd=wtot.mean(), med_wd=float(np.median(wtot)), p_ruin=ruin / N))

    return dict(N=N, B=B, annual=annual, mdd=mddR, cum=cum, chal=chal, fund=fund)


def main():
    R, (nas, gold, crypto, ibs), (start, end), _trades = build_daily_R()
    years = (end - start).days / 365.25; active = R[R != 0]

    print('=' * 74)
    print('  0) FULL MONTE-CARLO STATS  (no compounding, 1R = risk% of INITIAL balance)')
    print('=' * 74)
    print(f'  History {start.date()}..{end.date()} ({years:.1f}y) | per brick R/yr: '
          f'NAS {nas.sum()/years:+.1f}  gold {gold.sum()/years:+.1f}  crypto {crypto.sum()/years:+.1f}  IBS {ibs.sum()/years:+.1f}')
    cumH = np.cumsum(R); mddH = (np.maximum.accumulate(cumH) - cumH).max()
    print(f'  Historical: total {R.sum():+.0f}R = {R.sum()/years:+.1f} R/yr | maxDD {mddH:.1f}R | '
          f'RoMaD {(R.sum()/years)/mddH:.2f} | Sharpe {active.mean()/active.std()*np.sqrt(252):.2f} | '
          f'worst day {R.min():+.2f}R')

    mc = simulate(R)
    annual, mddR, N = mc['annual'], mc['mdd'], mc['N']
    print(f'\n  1-YEAR distribution ({N} sims): P(profit yr)={(annual>0).mean():.1%}')
    print(f'  {"pct":>5} {"annual R":>10} {"maxDD R":>9}')
    for p in (5, 25, 50, 75, 95):
        print(f'  {p:>4}th {np.percentile(annual,p):>+9.1f}R {np.percentile(mddR,p):>8.1f}R')
    print(f'  mean {annual.mean():+.1f}R | maxDD 99th {np.percentile(mddR,99):.1f}R worst {mddR.max():.1f}R')

    print('\n' + '=' * 74)
    print('  1) CHALLENGE  target +15% | static max DD -10% (floor 90%) | daily -5%')
    print('=' * 74)
    print(f'  {"risk":>6} {"P(PASS)":>8} {"P(failDD)":>9} {"P(daily)":>8} {"med months":>11}')
    for c in mc['chal']:
        mo = f'{c["med_months"]:.1f}mo' if c['med_months'] else '--'
        print(f'  {c["risk"]*100:>5.2f}% {c["p_pass"]:>8.1%} {c["p_fail_dd"]:>9.1%} {c["p_fail_daily"]:>8.1%} {mo:>11}')

    print('\n' + '=' * 74)
    print('  2) FUNDED  static -10% DD | monthly payout resets balance to initial')
    print('=' * 74)
    print(f'  {"risk":>6} {"E[wd %/yr]":>11} {"med %/yr":>9} {"P(ruin/yr)":>11}')
    for f in mc['fund']:
        print(f'  {f["risk"]*100:>5.2f}% {f["mean_wd"]:>10.1f}% {f["med_wd"]:>8.1f}% {f["p_ruin"]:>11.1%}')


if __name__ == '__main__':
    main()
