"""Funded payout-FREQUENCY study for the frozen 3-brick book.  (canonical, 2026-07-29)

Static -10% DD floor (fixed at 90% of INITIAL). Each payout withdraws profit>0 and RESETS
balance to 100%. Question: is a frequent (biweekly) payout better than monthly/quarterly?
Finding: annual income is ~flat across cadence, but frequent payout strips the cushion
(reset to 100% = always 10% from the static floor) -> ~2x the ruin risk. Take payouts
INFREQUENTLY (unless counterparty risk dominates). If partial withdrawals are allowed,
keeping a +4% cushion roughly halves ruin for ~-3 pts of income.

Reuses the corrected fixed-fractional calendar-day R series from monte_carlo_static.py.
Run from repo root:  python edgelab/reports/payout_frequency.py
"""
import sys; sys.path.insert(0, '.')
import numpy as np
from edgelab.reports.monte_carlo_static import build_daily_R

R, _, _ = build_daily_R()
rng = np.random.default_rng(7); B = 14; N = 40000; Lf = 365


def _path(L):
    o = []
    while len(o) < L:
        st = rng.integers(0, len(R) - B); o.extend(R[st:st + B])
    return np.array(o[:L])


PATHS = np.array([_path(Lf) for _ in range(N)])


def sim(risk, cadence, buffer_pct=0.0):
    """Static floor at -10%/risk (in R below 100%). Withdraw down to (100+buffer)%; reset there."""
    DDfloor = -0.10 / risk; bufR = buffer_pct / risk
    wtot = np.zeros(N); ruin = np.zeros(N, bool)
    for k in range(N):
        e = 0.0; w = 0.0
        for t, x in enumerate(PATHS[k]):
            e += x
            if e <= DDfloor: ruin[k] = True; break
            if (t + 1) % cadence == 0 and e > bufR: w += (e - bufR); e = bufR
        wtot[k] = w * risk * 100
    return wtot, ruin


def main():
    print('=' * 70)
    print('  PAYOUT-FREQUENCY  (funded, static -10% floor, reset-to-initial on payout)')
    print('=' * 70)
    for risk in (0.005, 0.0075, 0.01):
        print(f'\n  --- sizing {risk*100:.2f}%/trade ---')
        print(f'  {"cadence":>9} {"E[wd %/yr]":>11} {"P(ruin/yr)":>11}')
        for cad in (7, 14, 21, 30, 60, 90):
            w, ru = sim(risk, cad)
            print(f'  {cad:>6}d   {w.mean():>10.1f}% {ru.mean():>11.1%}')

    print('\n' + '=' * 70)
    print('  BUFFER POLICY at 0.75% biweekly (if partial withdrawals allowed)')
    print('=' * 70)
    print(f'  {"buffer":>8} {"E[wd %/yr]":>11} {"P(ruin/yr)":>11}')
    for buf in (0.0, 0.02, 0.04, 0.06):
        w, ru = sim(0.0075, 14, buffer_pct=buf)
        print(f'  +{buf*100:>4.0f}%   {w.mean():>10.1f}% {ru.mean():>11.1%}')


if __name__ == '__main__':
    main()
