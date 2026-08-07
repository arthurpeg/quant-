"""The 4-brick book as it stands, against the same book with brick 3 replaced by the
BTCUSD H1 Keltner breakout.

The book is built by the project's canonical function
(`edgelab.reports.monte_carlo_static.build_daily_R`) — the same one the HTML report and
the Monte-Carlo read: LIVE cadence for bricks 3 and 4, the `crypto_risk:` exits for
brick 3, window 2018-07 onward, calendar index (crypto weekends count).

The Keltner sleeve is taken at its HONEST configuration — SL 3xATR14 **with the 25x-spread
floor**, TP 2R, 96-bar cap — not at the screened one. Flooring costs it 37% of its R/yr
(+27.1 -> +17.2) and it is the only version worth putting in front of a sizing decision.

Note what a REPLACEMENT actually changes, beyond the numbers: brick 3 is MACD+RSI on
**BTC and ETH, daily**; the Keltner sleeve is **BTC only, hourly**. Swapping drops ETH
from the book entirely and moves the crypto exposure onto an intraday clock.
"""
import sys, warnings
sys.path.insert(0, 'scratchpad'); sys.path.insert(0, '.')
warnings.filterwarnings('ignore')
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import numpy as np
import pandas as pd

import kauf_lib as K
import tsam_rules as T
from edgelab.reports.monte_carlo_static import build_daily_R, simulate

RISK_CHOICES = (0.005, 0.0075, 0.01)


def keltner_daily(idx, floor=25.0):
    b = K.Bars('BTCUSD', 'H1', source='cache', min_bars=5000)
    sig = T.all_rules(b)['Keltner_break_1.5']
    s = np.flatnonzero(sig != 0)
    tab = K.Table(b, 3.0, 2.0, 96, session=False, floor_spread=floor)
    R, xi, _ = tab.walk_idx(s, sig[s])
    t = pd.DatetimeIndex(b.time[xi]).tz_convert('UTC').tz_localize(None).normalize()
    d = pd.Series(R, index=t).groupby(level=0).sum()
    return d.reindex(idx).fillna(0.0), len(R)


def perf(s):
    span = max((s.index.max() - s.index.min()).days / 365.25, 1e-9)
    c = s.cumsum()
    dd = float((c.cummax() - c).max())
    return dict(Ryr=float(s.sum() / span), maxDD=dd,
                RoMaD=float((s.sum() / span) / dd) if dd > 0 else np.nan,
                Sharpe=float(s.mean() / s.std() * np.sqrt(365)) if s.std() > 0 else np.nan,
                worst_day=float(s.min()), worst_week=float(s.rolling(7).sum().min()))


def main():
    R, parts, (start, end), _ = build_daily_R()
    idx = pd.date_range(start, end, freq='D')
    b1, b2, b3, b4 = [p.reindex(idx).fillna(0.0) for p in parts]
    kelt, nk = keltner_daily(idx)

    print(f'fenetre canonique du livre : {start:%Y-%m-%d} -> {end:%Y-%m-%d}\n')
    print('sleeves (sur la fenetre du livre):')
    for nm, s in (('b1 NAS ORB', b1), ('b2 gold ToM', b2), ('b3 crypto MACD-RSI', b3),
                  ('b4 IBS NAS', b4), (f'Keltner BTC H1 (n={nk})', kelt)):
        p = perf(s)
        print(f"  {nm:<24} R/yr {p['Ryr']:+7.1f}  maxDD {p['maxDD']:5.1f}  "
              f"RoMaD {p['RoMaD']:5.2f}  Sharpe {p['Sharpe']:4.2f}  "
              f"pire jour {p['worst_day']:+5.2f}  jours actifs {int((s != 0).sum())}")

    M = pd.DataFrame({'b1': b1, 'b2': b2, 'b3': b3, 'b4': b4, 'KELT': kelt})
    print('\ncorrelations QUOTIDIENNES:')
    print(M.corr().round(3).to_string())
    print('\ncorrelations MENSUELLES (l horizon honnete):')
    print(M.resample('ME').sum().corr().round(3).to_string())

    configs = {
        'A  livre actuel (b1+b2+b3+b4)':        b1 + b2 + b3 + b4,
        'B  b3 -> Keltner @1R (remplacement)':  b1 + b2 + kelt + b4,
        'C  b3 -> Keltner @0.5R':               b1 + b2 + 0.5 * kelt + b4,
        'D  b3 CONSERVE + Keltner @0.5R':       b1 + b2 + b3 + 0.5 * kelt + b4,
        'E  b3 CONSERVE + Keltner @1R':         b1 + b2 + b3 + kelt + b4,
    }

    print('\n' + '=' * 112)
    print('PERFORMANCE HISTORIQUE (1R = risque par trade, non compose)')
    print('=' * 112)
    print(f"{'config':<38}{'R/an':>8}{'maxDD':>8}{'RoMaD':>7}{'Sharpe':>8}"
          f"{'pire jour':>11}{'pire sem.':>11}{'%/an @risque egal':>19}")
    res = {}
    for nm, s in configs.items():
        p = perf(s)
        res[nm] = s
        pct = 100 * (0.10 / (2 * p['maxDD'])) * p['Ryr']
        print(f"{nm:<38}{p['Ryr']:>+8.1f}{p['maxDD']:>8.1f}{p['RoMaD']:>7.2f}"
              f"{p['Sharpe']:>8.2f}{p['worst_day']:>+11.2f}{p['worst_week']:>+11.2f}"
              f"{pct:>18.1f}%")

    print('\nR par annee:')
    yr = pd.DataFrame({nm: s.groupby(s.index.year).sum() for nm, s in res.items()})
    print(yr.round(1).to_string())
    print('\nannees positives :', {nm: f'{int((yr[nm] > 0).sum())}/{len(yr)}'
                                   for nm in yr.columns})

    print('\n' + '=' * 112)
    print('MONTE-CARLO block-bootstrap (fonction canonique, 20k sims)')
    print('=' * 112)
    mcs = {nm: simulate(s.values, N=20000) for nm, s in res.items()}
    print(f"\n{'config':<38}{'P(an +)':>9}{'R/an med':>10}{'5e pct':>9}"
          f"{'maxDD med':>11}{'maxDD 95e':>11}")
    for nm, mc in mcs.items():
        a, d = mc['annual'], mc['mdd']
        print(f"{nm:<38}{(a > 0).mean():>8.1%}{np.median(a):>+10.1f}"
              f"{np.percentile(a, 5):>+9.1f}{np.median(d):>11.1f}"
              f"{np.percentile(d, 95):>11.1f}")

    print('\nCHALLENGE (cible +15% / DD statique -10% / quotidien -5%)')
    print(f"{'config':<38}{'risque':>8}{'P(PASS)':>9}{'P(fail DD)':>11}"
          f"{'P(fail jour)':>13}{'duree med':>11}")
    for nm, mc in mcs.items():
        for c in mc['chal']:
            if c['risk'] not in RISK_CHOICES:
                continue
            mo = f"{c['med_months']:.1f} mo" if c['med_months'] else '--'
            print(f"{nm if c['risk'] == RISK_CHOICES[0] else '':<38}"
                  f"{c['risk']*100:>7.2f}%{c['p_pass']:>9.1%}{c['p_fail_dd']:>11.1%}"
                  f"{c['p_fail_daily']:>13.1%}{mo:>11}")

    print('\nFUNDED (DD statique -10%, payout mensuel)')
    print(f"{'config':<38}{'risque':>8}{'E[retire %/an]':>16}{'P(ruine/an)':>13}")
    for nm, mc in mcs.items():
        for f in mc['fund']:
            if f['risk'] not in RISK_CHOICES:
                continue
            print(f"{nm if f['risk'] == RISK_CHOICES[0] else '':<38}"
                  f"{f['risk']*100:>7.2f}%{f['mean_wd']:>15.1f}%{f['p_ruin']:>13.1%}")


if __name__ == '__main__':
    main()
