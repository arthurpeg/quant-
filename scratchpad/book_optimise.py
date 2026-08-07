"""Which combination of the six available sleeves makes the best book?

Sleeves (all on the canonical calendar index, 2018-07 -> 2026-07):
  b1    NAS100 US-open ATR breakout, low-vol regime      (live cadence, canonical)
  b2    XAUUSD turn-of-month                             (live cadence, canonical)
  b3    BTC+ETH MACD+RSI daily                           (live cadence, crypto_risk exits)
  b4    NAS100 IBS reversion                             (live cadence, canonical)
  KAER  NAS100 M15 efficiency-ratio breakout             (edgelab/intraday/kaer.py)
  KELT  BTCUSD H1 Keltner breakout, 25x-spread floor     (tsam_rules)

Weights swept over {0, 0.25, 0.5, 0.75, 1.0} R per sleeve = 5^6 = 15,625 books.

THE METRIC. On a static-drawdown prop account you are paid on the PATH, not on the
volatility: the binding constraint is the -10% floor, so the account is sized to a cushion
of 2x the historical maxDD and the figure of merit is the resulting **%/yr at equal
risk** = (0.10 / (2 x maxDD)) x R/yr. That is the project's standing admission test
(wiki/system.md), and it is why RoMaD beats Sharpe here.

THE HONEST PART. Optimising six weights on eight years of the same data is overfitting by
construction. So the script does three things beyond the ranking:
  1. reports the equal-weight books alongside the optimum, because a large gap between
     them is the signature of a fitted answer;
  2. runs a TRUE out-of-sample weight test — weights chosen on the first half only, scored
     on the second half, against the same choice made at random;
  3. keeps the Monte-Carlo prop numbers on the finalists, since P(ruin) is the number that
     actually ends an account.
"""
import sys, warnings, itertools
sys.path.insert(0, 'scratchpad'); sys.path.insert(0, '.')
warnings.filterwarnings('ignore')
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import numpy as np
import pandas as pd

import kauf_lib as K
import tsam_rules as T
from edgelab.intraday.kaer import run_kaer, KaerParams
from edgelab.reports.monte_carlo_static import build_daily_R, simulate

WEIGHTS = (0.0, 0.25, 0.5, 0.75, 1.0)
NAMES = ['b1', 'b2', 'b3', 'b4', 'KAER', 'KELT']


def _daily(R, times, idx):
    t = pd.DatetimeIndex(times)
    t = t.tz_convert('UTC') if t.tz is not None else t.tz_localize('UTC')
    s = pd.Series(np.asarray(R, float), index=t.tz_localize(None).normalize())
    return s.groupby(level=0).sum().reindex(idx).fillna(0.0)


def sleeves():
    R, parts, (start, end), _ = build_daily_R()
    idx = pd.date_range(start, end, freq='D')
    b1, b2, b3, b4 = [p.reindex(idx).fillna(0.0) for p in parts]

    kr = run_kaer('NAS100')
    kaer = _daily(kr.trades['R'], kr.trades['exit_time'], idx)

    b = K.Bars('BTCUSD', 'H1', source='cache', min_bars=5000)
    sig = T.all_rules(b)['Keltner_break_1.5']
    s = np.flatnonzero(sig != 0)
    tab = K.Table(b, 3.0, 2.0, 96, session=False, floor_spread=25.0)
    Rk, xi, _ = tab.walk_idx(s, sig[s])
    kelt = _daily(Rk, b.time[xi], idx)

    return pd.DataFrame({'b1': b1, 'b2': b2, 'b3': b3, 'b4': b4,
                         'KAER': kaer, 'KELT': kelt}), (start, end)


def perf(s):
    span = max((s.index.max() - s.index.min()).days / 365.25, 1e-9)
    c = s.cumsum()
    dd = float((c.cummax() - c).max())
    ryr = float(s.sum() / span)
    sd = s.std()
    return dict(Ryr=ryr, maxDD=dd, RoMaD=(ryr / dd if dd > 0 else np.nan),
                Sharpe=(float(s.mean() / sd * np.sqrt(365)) if sd > 0 else np.nan),
                worst=float(s.min()),
                pct=(100 * (0.10 / (2 * dd)) * ryr if dd > 0 else np.nan))


def grid(M, cols=NAMES):
    A = M[cols].to_numpy()
    idx = M.index
    out = []
    for w in itertools.product(WEIGHTS, repeat=len(cols)):
        if sum(w) == 0:
            continue
        s = pd.Series(A @ np.array(w), index=idx)
        p = perf(s)
        p['w'] = w
        p['nsleeves'] = int(sum(1 for x in w if x > 0))
        p['total_R'] = sum(w)
        out.append(p)
    return pd.DataFrame(out)


def label(w, cols=NAMES):
    return ' '.join(f'{n}{x:g}' for n, x in zip(cols, w) if x > 0)


def main():
    M, (start, end) = sleeves()
    print(f'fenetre : {start:%Y-%m-%d} -> {end:%Y-%m-%d}\n')
    print('sleeves seules:')
    for n in NAMES:
        p = perf(M[n])
        print(f"  {n:<5} R/yr {p['Ryr']:+7.1f}  maxDD {p['maxDD']:5.1f}  RoMaD {p['RoMaD']:5.2f}"
              f"  Sharpe {p['Sharpe']:4.2f}  pire jour {p['worst']:+5.2f}"
              f"  %/an seul {p['pct']:5.1f}%  jours actifs {int((M[n] != 0).sum())}")
    print('\ncorrelations MENSUELLES:')
    print(M.resample('ME').sum().corr().round(3).to_string())

    g = grid(M)
    g['label'] = g['w'].map(label)

    print('\n' + '=' * 104)
    print('LES 15 MEILLEURS LIVRES (classes sur %/an a risque egal)')
    print('=' * 104)
    top = g.nlargest(15, 'pct')
    print(f"{'poids':<44}{'R/an':>8}{'maxDD':>8}{'RoMaD':>7}{'Sharpe':>8}"
          f"{'pire j':>8}{'%/an':>8}")
    for _, r in top.iterrows():
        print(f"{r['label']:<44}{r['Ryr']:>+8.1f}{r['maxDD']:>8.1f}{r['RoMaD']:>7.2f}"
              f"{r['Sharpe']:>8.2f}{r['worst']:>+8.2f}{r['pct']:>7.1f}%")

    print('\n' + '=' * 104)
    print('REFERENCES — les livres SIMPLES, sans optimisation de poids')
    print('=' * 104)
    refs = {
        'livre actuel (b1+b2+b3+b4 @1R)': (1, 1, 1, 1, 0, 0),
        'les 6 @1R': (1, 1, 1, 1, 1, 1),
        'les 6, nouveaux @0.5R': (1, 1, 1, 1, .5, .5),
        '4 actuelles + KAER@0.5': (1, 1, 1, 1, .5, 0),
        '4 actuelles + KELT@0.5': (1, 1, 1, 1, 0, .5),
        'b2+b3+b4+KELT @1R (sans NAS)': (0, 1, 1, 1, 0, 1),
        'b1+b2+b4+KAER (sans crypto)': (1, 1, 0, 1, 1, 0),
    }
    print(f"{'config':<44}{'R/an':>8}{'maxDD':>8}{'RoMaD':>7}{'Sharpe':>8}"
          f"{'pire j':>8}{'%/an':>8}")
    named = {}
    for nm, w in refs.items():
        s = M[NAMES].to_numpy() @ np.array(w)
        s = pd.Series(s, index=M.index)
        named[nm] = (w, s)
        p = perf(s)
        print(f"{nm:<44}{p['Ryr']:>+8.1f}{p['maxDD']:>8.1f}{p['RoMaD']:>7.2f}"
              f"{p['Sharpe']:>8.2f}{p['worst']:>+8.2f}{p['pct']:>7.1f}%")

    print('\n' + '=' * 104)
    print('LE TEST QUI COMPTE — poids choisis sur la 1re moitie, notes sur la 2e')
    print('=' * 104)
    mid = M.index[len(M) // 2]
    A, B = M.loc[:mid], M.loc[mid:]
    gA = grid(A)
    best_w = gA.nlargest(1, 'pct')['w'].iloc[0]
    rows = []
    for nm, w in [('optimum in-sample 1re moitie', best_w),
                  ('livre actuel @1R', (1, 1, 1, 1, 0, 0)),
                  ('les 6 @1R', (1, 1, 1, 1, 1, 1)),
                  ('les 6, nouveaux @0.5R', (1, 1, 1, 1, .5, .5))]:
        sB = pd.Series(B[NAMES].to_numpy() @ np.array(w), index=B.index)
        pB = perf(sB)
        sA = pd.Series(A[NAMES].to_numpy() @ np.array(w), index=A.index)
        pA = perf(sA)
        rows.append((nm, label(w), pA['pct'], pB['pct'], pB['Ryr'], pB['maxDD'], pB['RoMaD']))
    print(f"{'config':<32}{'poids':<34}{'%/an 1re':>10}{'%/an 2e':>10}"
          f"{'R/an 2e':>9}{'maxDD 2e':>10}{'RoMaD 2e':>10}")
    for nm, lb, pa, pb, ry, dd, ro in rows:
        print(f'{nm:<32}{lb:<34}{pa:>9.1f}%{pb:>9.1f}%{ry:>+9.1f}{dd:>10.1f}{ro:>10.2f}')
    # how much of the in-sample optimum's edge is real: compare to random weightings
    rng = np.random.default_rng(0)
    rand = []
    for _ in range(500):
        w = rng.choice(WEIGHTS, size=6)
        if w.sum() == 0:
            continue
        rand.append(perf(pd.Series(B[NAMES].to_numpy() @ w, index=B.index))['pct'])
    rand = np.array(rand)
    opt_oos = rows[0][3]
    print(f'\n  poids aleatoires sur la 2e moitie : mediane {np.median(rand):.1f}%  '
          f'90e pct {np.percentile(rand, 90):.1f}%  max {rand.max():.1f}%')
    print(f'  -> l optimum appris sur la 1re moitie se classe au '
          f'{100 * (rand < opt_oos).mean():.0f}e percentile des poids TIRES AU HASARD')

    print('\n' + '=' * 104)
    print('MONTE-CARLO + REGLES PROP sur les finalistes')
    print('=' * 104)
    finalists = {'A livre actuel @1R': named['livre actuel (b1+b2+b3+b4 @1R)'][1],
                 'B les 6, nouveaux @0.5R': named['les 6, nouveaux @0.5R'][1],
                 'C les 6 @1R': named['les 6 @1R'][1],
                 'D optimum in-sample': pd.Series(
                     M[NAMES].to_numpy() @ np.array(top.iloc[0]['w']), index=M.index)}
    mcs = {nm: simulate(s.values, N=20000) for nm, s in finalists.items()}
    print(f"\n{'config':<28}{'P(an +)':>9}{'R/an med':>10}{'5e pct':>9}{'maxDD med':>11}")
    for nm, mc in mcs.items():
        a, d = mc['annual'], mc['mdd']
        print(f"{nm:<28}{(a > 0).mean():>8.1%}{np.median(a):>+10.1f}"
              f"{np.percentile(a, 5):>+9.1f}{np.median(d):>11.1f}")
    print(f"\n{'config':<28}{'risque':>8}{'P(PASS)':>9}{'P(fail DD)':>11}"
          f"{'P(fail jour)':>13}{'E[retire]':>11}{'P(ruine)':>10}")
    for nm, mc in mcs.items():
        for c, f in zip(mc['chal'], mc['fund']):
            if c['risk'] not in (0.005, 0.0075, 0.01):
                continue
            print(f"{nm if c['risk'] == 0.005 else '':<28}{c['risk']*100:>7.2f}%"
                  f"{c['p_pass']:>9.1%}{c['p_fail_dd']:>11.1%}{c['p_fail_daily']:>13.1%}"
                  f"{f['mean_wd']:>10.1f}%{f['p_ruin']:>10.1%}")


if __name__ == '__main__':
    main()
