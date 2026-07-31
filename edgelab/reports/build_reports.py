"""Regenerate BOTH HTML reports from one run of the book.  (canonical, 2026-07-31)

    python edgelab/reports/build_reports.py

Recomputes the whole 4-brick book from the brick modules, re-runs the block-bootstrap
Monte Carlo (`monte_carlo_static.simulate`, the same function `monte_carlo_static.py`
prints from — so the printout and the reports can never disagree), and injects the two
data blobs into the report pages:

  * `portfolio_backtest.html`  -> `const D={...}`  (equity curve, annual R, per-brick, corr)
  * `monte_carlo.html`         -> `const M={...}`  (percentile fan, histograms, prop odds)

Only the data lines are rewritten; the layout/prose of the pages is left alone. Copies are
also refreshed in `_out/` and as the root `RAPPORT_*.html` convenience files.

Run this after adding/changing a brick, then check the prose in the two pages for any
hard-coded number that moved (the script prints the values that appear in prose).
"""
import sys; sys.path.insert(0, '.')
import json
import re
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')   # the window string carries a '→'

import numpy as np
import pandas as pd

from edgelab.reports.monte_carlo_static import BRICKS, build_daily_R, simulate

HERE = Path('edgelab/reports')
ROOT = Path('.')
PAGES = {                       # source page -> (root convenience copy, JS const name)
    'portfolio_backtest.html': ('RAPPORT_backtest_portefeuille.html', 'D'),
    'monte_carlo.html': ('RAPPORT_monte_carlo.html', 'M'),
}
CORR_KEYS = ('NAS', 'Gold', 'Crypto', 'IBS')


def portfolio_data(R, parts, start, end, counts):
    """The `const D={...}` blob of portfolio_backtest.html."""
    idx = pd.date_range(start, end, freq='D')
    years = (end - start).days / 365.25
    s = pd.Series(R, index=idx)
    cum = s.cumsum()
    active = R[R != 0]
    mdd = float((np.maximum.accumulate(np.cumsum(R)) - np.cumsum(R)).max())
    eq = cum.resample('ME').last().ffill()

    df = pd.DataFrame({k: v.values for k, v in zip(CORR_KEYS, parts)}, index=idx)
    corr = df.corr()

    return {
        'window': f'{start:%Y-%m} → {end:%Y-%m}  ({years:.1f} yr)',
        'combined': {
            'r': round(float(R.sum()) / years, 1), 'maxdd': round(mdd, 1),
            'romad': round((float(R.sum()) / years) / mdd, 2),
            'sharpe': round(float(active.mean() / active.std() * np.sqrt(252)), 2),
            'worst': round(float(R.min()), 2), 'best': round(float(R.max()), 2),
            'win': int(round((active > 0).mean() * 100)),
        },
        'equity': [round(float(v), 1) for v in eq.values],
        'eq_start': round(start.year + (start.month - 1) / 12, 2),
        'years': {str(y): round(float(v), 1) for y, v in s.groupby(s.index.year).sum().items()},
        'bricks': {name: [round(float(p.sum()) / years, 1), round(float(p.sum()), 0), counts[name]]
                   for name, p in zip(BRICKS, parts)},
        'corr': {a: {b: round(float(corr.loc[a, b]), 2) for b in CORR_KEYS} for a in CORR_KEYS},
    }


def mc_data(mc):
    """The `const M={...}` blob of monte_carlo.html."""
    annual, mdd, cum = mc['annual'], mc['mdd'], mc['cum']
    fan_days = list(range(0, 361, 5))
    pad = np.hstack([np.zeros((cum.shape[0], 1)), cum])       # day 0 = flat start of the fan
    fan = {f'p{q}': [round(float(np.percentile(pad[:, d], q)), 1) for d in fan_days]
           for q in (5, 25, 50, 75, 95)}

    def hist(x, marks):
        c, e = np.histogram(x, bins=40)
        return {'c': [int(v) for v in c], 'e': [round(float(v), 1) for v in e],
                'mk': [round(float(np.percentile(x, m)), 1) for m in marks]}

    return {
        'tiles': {'med': round(float(np.percentile(annual, 50)), 1),
                  'mean': round(float(annual.mean()), 1),
                  'pprofit': round(float((annual > 0).mean() * 100), 1),
                  'ddmed': round(float(np.percentile(mdd, 50)), 1),
                  'dd95': round(float(np.percentile(mdd, 95)), 1),
                  'dd99': round(float(np.percentile(mdd, 99)), 1)},
        'fan_days': fan_days, **fan,
        'hA': hist(annual, (5, 50, 95)), 'hD': hist(mdd, (50, 95)),
        # the report tables stop at 1.5%/trade (above that the daily rule dominates)
        'chal': [[c['risk'] * 100, round(c['p_pass'] * 100, 1), round(c['p_fail_dd'] * 100, 1),
                  round(c['p_fail_daily'] * 100, 1), round(c['med_months'], 1)]
                 for c in mc['chal'] if c['risk'] <= 0.015],
        'fund': [[f['risk'] * 100, round(f['mean_wd'], 1), round(f['med_wd'], 1),
                  round(f['p_ruin'] * 100, 1)] for f in mc['fund'] if f['risk'] <= 0.015],
    }


def inject(page: str, var: str, obj) -> str:
    """Replace the `const <var>={...};` data line in a report page, leaving the rest alone."""
    src = (HERE / page).read_text(encoding='utf-8')
    blob = f'const {var}={json.dumps(obj, separators=(",", ":"))};'
    new, n = re.subn(rf'^const {var}=\{{.*?^\}};|^const {var}=\{{.*?\}};',
                     lambda _: blob, src, count=1, flags=re.S | re.M)
    if n != 1:
        raise RuntimeError(f'{page}: could not locate the `const {var}={{...}};` data line')
    (HERE / page).write_text(new, encoding='utf-8', newline='\n')
    return new


def main():
    R, parts, (start, end), counts = build_daily_R()
    D = portfolio_data(R, parts, start, end, counts)
    print(f'  book {D["window"]} | {D["combined"]["r"]:+.1f} R/yr | maxDD {D["combined"]["maxdd"]}R'
          f' | Sharpe {D["combined"]["sharpe"]} | RoMaD {D["combined"]["romad"]}')
    for name, (ry, tot, n) in D['bricks'].items():
        print(f'    {name:<24} {ry:+6.1f} R/yr  {tot:+7.0f} R  {n:>5} trades')

    mc = simulate(R)
    M = mc_data(mc)
    print(f'  MC  median {M["tiles"]["med"]:+.1f} R/yr | P(profit) {M["tiles"]["pprofit"]}%'
          f' | median maxDD {M["tiles"]["ddmed"]}R'
          f' | 5th-pct year {np.percentile(mc["annual"], 5):+.1f} R')

    for page, (copy, var) in PAGES.items():
        html = inject(page, var, D if var == 'D' else M)
        for dest in (HERE / '_out' / page, ROOT / copy):
            dest.parent.mkdir(exist_ok=True)
            dest.write_text(html, encoding='utf-8', newline='\n')
        print(f'  wrote {HERE / page}  (+ _out/ + {copy})')

    (HERE / '_out').mkdir(exist_ok=True)
    (HERE / '_out' / 'report_data.json').write_text(
        json.dumps({'portfolio': D, 'monte_carlo': M}, indent=1), encoding='utf-8')

    print('\n  numbers hard-coded in the pages\' prose — check these still read right:')
    c = D['combined']
    ch1 = next(x for x in M['chal'] if x[0] == 1.0); f05 = next(x for x in M['fund'] if x[0] == 0.5)
    print(f'    portfolio: maxDD {c["maxdd"]}R, R/yr {c["r"]}, Sharpe {c["sharpe"]},'
          f' first-year {D["years"][str(start.year)]:+.1f} R')
    print(f'    monte carlo: challenge @1% pass {ch1[1]}% in {ch1[4]}mo;'
          f' funded @0.5% {f05[1]}%/yr at {f05[3]}% ruin; worst day {c["worst"]} R')


if __name__ == '__main__':
    main()
