"""The placebo divisor for the H1 crypto+metals sweep.

Why it is mandatory here and not optional: the H1 geometry null is *catastrophic*
(median null t = -3.51 on BTCUSD, -11.25 on ETHUSD, with a floor at -37), because on H1
the friction is charged against a much smaller ATR. So "excess over the null" is inflated
by a terrible baseline, and 46% of H1 cells clear their null p95 while only 15.5% make
money at all. The ledger already carries this rule from the ProRealCode pass — *beating a
terrible null is not the same as making money* — and the divisor is what turns the
observation into a number.

Same funnel, same code path, matched random signals, one replicate per asset.
"""
import sys, warnings, itertools, time
sys.path.insert(0, 'scratchpad')
warnings.filterwarnings('ignore')
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import numpy as np
import pandas as pd

from tsam_placebo import placebo_one
from tsam_sweep import CLS

SYMS = ['BTCUSD', 'ETHUSD', 'XAUUSD']


def screen(d):
    """The economic floor applied to the real sweep, verbatim."""
    return d[(d.t > d.null_p95) & (d.ER > 0) & (d.n >= 60) & (d.t > 2)]


def main():
    real = pd.read_parquet('scratchpad/_tsam_scored_H1_BTCUSD-ETHUSD-XAUUSD-XAGUSD.parquet')
    rows, nulls = [], []
    rng = np.random.default_rng(77)
    t0 = time.time()
    for s in SYMS:
        try:
            placebo_one(s, 'H1', 0, rows, nulls, rng)
            print(f'  {s} done [{time.time()-t0:.0f}s]', flush=True)
        except Exception as e:
            print(f'  {s} SKIP {type(e).__name__}: {e}', flush=True)
    p = pd.DataFrame(rows)
    nl = pd.DataFrame(nulls).drop_duplicates(['sym', 'tf', 'sl', 'tp', 'mb', 'lfb'])
    p = p.merge(nl, on=['sym', 'tf', 'sl', 'tp', 'mb', 'lfb'], how='left')
    p['excess'] = p['t'] - p['null_med']
    p.to_parquet('scratchpad/_tsam_placebo_H1.parquet', index=False)

    rs, ps = screen(real), screen(p)
    print('\n' + '=' * 92)
    print('H1 — REAL vs PLACEBO, with and without the economic floor')
    print('=' * 92)
    for lab, r_, p_ in (('cells', real, p),
                        ('above null p95', real[real.t > real.null_p95], p[p.t > p.null_p95]),
                        ('+ E[R]>0, n>=60, t>2 (the floor)', rs, ps)):
        print(f'  {lab:<36} real {len(r_):>6,}   placebo {len(p_):>6,}   '
              f'ratio {len(r_)/max(len(p_),1):>6.2f}x')
    print()
    out = pd.DataFrame({
        'real_cells': real.groupby('cls').size(),
        'placebo_cells': p.groupby('cls').size(),
        'real_med_excess': real.groupby('cls')['excess'].median(),
        'placebo_med_excess': p.groupby('cls')['excess'].median(),
        'real_survivors': rs.groupby('cls').size(),
        'placebo_survivors': ps.groupby('cls').size(),
    }).fillna(0)
    out['RATIO'] = out['real_survivors'] / out['placebo_survivors'].replace(0, np.nan)
    print(out.round(3).to_string())
    print('\nstop width of the REAL survivors (the tell):')
    print(rs.groupby('sl').size().to_string())
    print('\n-> scratchpad/_tsam_placebo_H1.parquet')


if __name__ == '__main__':
    main()
