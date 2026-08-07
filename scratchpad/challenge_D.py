"""P(passing the challenge) with book D, in detail.

D = b1 + b2 + b3 + b4 @1R, KAER@0.5R, KELT@0.5R.

Rules simulated (the static-DD firm in config_live.yaml): target **+15%**, total drawdown
floor **-10% of the INITIAL balance** (static, so the floor never rises), daily loss
**-5%** of initial. One attempt, no retry. A 2-year path; anything that has neither passed
nor breached by then counts as "still running", which is why the three outcomes need not
sum to 100%.

Reported per risk-per-trade: the outcome split, the median time to pass, and the full
time-to-pass curve — because "92% pass" is worth much less if half of those take a year.

Cross-checked against `monte_carlo_static.simulate`, the function the project's own
reports print from.
"""
import sys, warnings
sys.path.insert(0, 'scratchpad'); sys.path.insert(0, '.')
warnings.filterwarnings('ignore')
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import numpy as np
import pandas as pd

from book_optimise import sleeves, perf, NAMES
from edgelab.reports.monte_carlo_static import simulate

N, BLOCK, HORIZON = 40000, 14, 730
TARGET, DDFLOOR, DAILY = 0.15, 0.10, 0.05
RISKS = (0.005, 0.0075, 0.01, 0.0125, 0.015)


def challenge(R, risk, n=N, seed=7):
    rng = np.random.default_rng(seed)
    T, DD, DAY = TARGET / risk, DDFLOOR / risk, DAILY / risk
    days = np.full(n, np.nan)
    out = np.zeros(n, dtype=np.int8)      # 1 pass, 2 fail DD, 3 fail daily, 0 running
    for k in range(n):
        p = []
        while len(p) < HORIZON:
            st = rng.integers(0, len(R) - BLOCK)
            p.extend(R[st:st + BLOCK])
        p = np.array(p[:HORIZON])
        e = 0.0
        for t, x in enumerate(p):
            if x <= -DAY:
                out[k] = 3
                break
            e += x
            if e <= -DD:
                out[k] = 2
                break
            if e >= T:
                out[k] = 1
                days[k] = t + 1
                break
    return out, days


def main():
    M, (s0, s1) = sleeves()
    mid = M.index[len(M) // 2]
    wD = (1, 1, 1, 1, .5, .5)
    D = pd.Series(M[NAMES].to_numpy() @ np.array(wD), index=M.index)
    p = perf(D)
    print(f"Livre D = b1+b2+b3+b4 @1R, KAER@0.5R, KELT@0.5R")
    print(f"  R/an {p['Ryr']:+.1f}  maxDD {p['maxDD']:.1f} R  RoMaD {p['RoMaD']:.2f}  "
          f"Sharpe {p['Sharpe']:.2f}  pire jour {p['worst']:+.2f} R")
    print(f"  fenetre {s0:%Y-%m}  ->  {s1:%Y-%m}\n")

    for tag, sl in (('ECHANTILLON COMPLET', slice(None)),
                    ('2e MOITIE SEULE (proxy forward-test)', slice(mid, None))):
        Rs = D.loc[sl].values
        print('=' * 96)
        print(f'PROBABILITE DE VALIDER LE CHALLENGE — {tag}')
        print('  cible +15% | DD statique -10% | perte quotidienne -5% | 1 seule tentative | 2 ans max')
        print('=' * 96)
        print(f"{'risque/trade':<14}{'P(VALIDE)':>11}{'P(fail DD)':>12}{'P(fail jour)':>14}"
              f"{'encore en cours':>17}{'delai median':>15}")
        keep = {}
        for r in RISKS:
            out, days = challenge(Rs, r)
            keep[r] = (out, days)
            print(f"{r*100:>8.2f}%     {(out == 1).mean():>10.1%}{(out == 2).mean():>12.1%}"
                  f"{(out == 3).mean():>14.1%}{(out == 0).mean():>17.1%}"
                  f"{np.nanmedian(days)/30.44:>13.1f} mo")
        print(f"\n  courbe du delai — P(valide EN MOINS DE ...), en cumule:")
        print(f"{'risque':<10}{'1 mois':>9}{'2 mois':>9}{'3 mois':>9}{'6 mois':>9}"
              f"{'9 mois':>9}{'12 mois':>9}{'24 mois':>9}")
        for r in RISKS:
            out, days = keep[r]
            row = [np.nanmean(np.where(out == 1, days, np.inf) <= m * 30.44)
                   for m in (1, 2, 3, 6, 9, 12, 24)]
            print(f"{r*100:>6.2f}%   " + ''.join(f'{x:>8.1%} ' for x in row))
        print()

    print('=' * 96)
    print('CONTRE-VERIFICATION avec monte_carlo_static.simulate (la fonction des rapports)')
    print('=' * 96)
    mc = simulate(D.values, N=20000)
    print(f"{'risque':<10}{'P(PASS)':>10}{'P(failDD)':>11}{'P(fail jour)':>14}{'delai med':>12}")
    for c in mc['chal']:
        mo = f"{c['med_months']:.1f} mo" if c['med_months'] else '--'
        print(f"{c['risk']*100:>6.2f}%   {c['p_pass']:>9.1%}{c['p_fail_dd']:>11.1%}"
              f"{c['p_fail_daily']:>14.1%}{mo:>12}")


if __name__ == '__main__':
    main()
