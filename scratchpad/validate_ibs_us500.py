"""Full validation: does IBS US500 earn a 5th brick slot?

The candidate surfaced in scratchpad/sleeve_swap.py (config E, +2.3 pts/yr at equal risk on
the pre-brick-3-fix book). The book has since changed (+32.0 R/yr), so the bar moved.

The decisive question exp-009 never asked: **IBS US500 vs IBS NAS100**. exp-009 measured
US500 against the three bricks of the time, not against brick 4 — but they are the SAME
mechanism on two co-moving US indices, so that correlation is the whole case.

Battery (same as the brick-3 exits validation):
  1  standalone, live cadence
  2  correlation to all four bricks — brick 4 above all
  3  robustness: per-year, split-half (+ is the gap significant), cost, bootstrap
  4  book impact at EQUAL RISK (each config sized to its own binding prop ceiling)
  5  overlap: how often are bricks 4 and 5 in the market on the same day, same direction

    python scratchpad/validate_ibs_us500.py
"""
import sys; sys.path.insert(0, '.'); sys.stdout.reconfigure(encoding='utf-8')

import numpy as np
import pandas as pd

from edgelab.edges.ibs import run_ibs, IBSParams
from edgelab.reports.monte_carlo_static import build_daily_R, START

DAILY_LIMIT, TOTAL_DD = 0.05, 0.10


def t_of(R):
    R = np.asarray(R, float)
    return R.mean() / R.std(ddof=1) * np.sqrt(len(R)) if len(R) > 2 else np.nan


def ibs_trades(sym, sl=2.5, cost=None):
    p = IBSParams(sl_atr=sl) if cost is None else IBSParams(sl_atr=sl, cost_price=cost)
    t = run_ibs(sym, p, cadence='live')
    t['ex'] = pd.to_datetime(t['exit_dt'])
    return t[t['ex'] >= START]


def daily(t, idx):
    s = pd.Series(t['R'].to_numpy(), index=pd.DatetimeIndex(t['ex']).normalize())
    return s.groupby(level=0).sum().reindex(idx).fillna(0)


def cfg_stats(parts, label, years):
    R = sum(parts).to_numpy(); cum = np.cumsum(R)
    mdd = float((np.maximum.accumulate(cum) - cum).max()); act = R[R != 0]
    ryr = R.sum() / years
    r_max = min(DAILY_LIMIT / abs(R.min()), TOTAL_DD / mdd)
    return dict(label=label, ryr=ryr, mdd=mdd, romad=ryr / mdd,
                sharpe=act.mean() / act.std() * np.sqrt(252), worst=R.min(),
                r_max=r_max, pct_yr=ryr * r_max * 100)


def hdr(x):
    print('\n' + '=' * 94); print(f'  {x}'); print('=' * 94)


def main():
    rng = np.random.default_rng(5)
    R, parts, (s0, e0), _ = build_daily_R()
    years = (e0 - s0).days / 365.25
    idx = pd.date_range(s0, e0, freq='D')
    nas, gold, crypto, ibs4 = parts

    t5 = ibs_trades('US500'); t4 = ibs_trades('NAS100')
    d5 = daily(t5, idx)

    # ---- 1 standalone -------------------------------------------------------------
    hdr('1) AUTONOME (cadence live, 2018-07+)')
    for lbl, t in (('IBS NAS100 (brique 4)', t4), ('IBS US500 (candidat)', t5)):
        Rv = t['R'].to_numpy()
        yr = t.set_index('ex')['R'].groupby(lambda z: z.year).sum()
        print(f"  {lbl:<24} n={len(Rv):>4} R/an={Rv.sum()/years:+6.2f} t={t_of(Rv):5.2f} "
              f"PF={Rv[Rv>0].sum()/-Rv[Rv<0].sum():4.2f} E[R]={Rv.mean():+.3f} "
              f"+ans={int((yr>0).sum())}/{len(yr)}")
    yr5 = t5.set_index('ex')['R'].groupby(lambda z: z.year).sum().round(1)
    yr4 = t4.set_index('ex')['R'].groupby(lambda z: z.year).sum().round(1)
    print('\n' + pd.DataFrame({'brique 4 (NAS100)': yr4, 'candidat (US500)': yr5}).to_string())

    # ---- 2 correlation ------------------------------------------------------------
    hdr('2) CORRELATION — la question decisive est vs la BRIQUE 4 (meme mecanisme)')
    df = pd.DataFrame({'NAS(b1)': nas, 'or(b2)': gold, 'crypto(b3)': crypto,
                       'IBS-NAS(b4)': ibs4, 'IBS-US500': d5})
    c = df.corr()['IBS-US500'].drop('IBS-US500')
    for k, v in c.items():
        flag = '  <-- MEME MECANISME' if 'b4' in k else ''
        print(f"  IBS-US500 vs {k:<14} {v:+.3f}{flag}")
    print(f"\n  max |corr| = {c.abs().max():.3f}  (les corr brique-brique existantes sont <= 0.03)")
    both = ((d5 != 0) & (ibs4 != 0)).sum()
    print(f"  jours ou les DEUX briques IBS cloturent un trade : {both} "
          f"({both/max((d5!=0).sum(),1)*100:.0f}% des jours actifs du candidat)")

    # ---- 3 robustness -------------------------------------------------------------
    hdr('3) ROBUSTESSE')
    R5 = t5['R'].to_numpy()
    bs = np.array([rng.choice(R5, len(R5), True).mean() for _ in range(10000)])
    print(f"  bootstrap      P(E[R]<=0) = {(bs<=0).mean():.4f}  IC95 [{np.percentile(bs,2.5):+.3f}, {np.percentile(bs,97.5):+.3f}]")
    mid = t5['ex'].quantile(0.5)
    e1 = t5[t5['ex'] < mid]['R'].to_numpy(); e2 = t5[t5['ex'] >= mid]['R'].to_numpy()
    dd = np.array([rng.choice(e1, len(e1), True).mean() - rng.choice(e2, len(e2), True).mean()
                   for _ in range(10000)])
    print(f"  split-half     early t={t_of(e1):5.2f} / late t={t_of(e2):5.2f} | "
          f"IC95 early-late [{np.percentile(dd,2.5):+.3f}, {np.percentile(dd,97.5):+.3f}]")
    print("  sensibilite au cout (US500, cout aller-retour en points) :")
    for cst in (0.6, 1.0, 2.0, 4.0, 6.0):
        tt = ibs_trades('US500', cost=cst)['R'].to_numpy()
        print(f"     {cst:>4.1f} pt -> t={t_of(tt):5.2f}  R/an={tt.sum()/years:+6.2f}")

    # ---- 4 book impact ------------------------------------------------------------
    hdr('4) IMPACT SUR LE BOOK, A RISQUE EGAL (chaque config a son propre plafond prop)')
    cfgs = [('A  book actuel (4 briques)', [nas, gold, crypto, ibs4]),
            ('E  + IBS US500 (5 briques)', [nas, gold, crypto, ibs4, d5]),
            ('E2 IBS US500 a la place de b4', [nas, gold, crypto, d5])]
    rows = [cfg_stats(p, n, years) for n, p in cfgs]
    print(f"  {'config':<32}{'R/an':>8}{'maxDD':>8}{'RoMaD':>7}{'Sharpe':>8}{'plafond':>9}{'%/an':>8}")
    for r in rows:
        print(f"  {r['label']:<32}{r['ryr']:>+8.1f}{r['mdd']:>8.1f}{r['romad']:>7.2f}"
              f"{r['sharpe']:>8.2f}{r['r_max']*100:>8.2f}%{r['pct_yr']:>7.1f}%")
    b = rows[0]
    print(f"\n  vs le book actuel :")
    for r in rows[1:]:
        print(f"    {r['label']:<32} {r['pct_yr']-b['pct_yr']:+5.1f} pts/an  "
              f"(RoMaD {r['romad']-b['romad']:+.2f}, Sharpe {r['sharpe']-b['sharpe']:+.2f})")
    # standalone RoMaD — the project's admission test
    hdr('5) TEST D\'ADMISSION DU PROJET : RoMaD individuel')
    for nm, x in (('NAS (b1)', nas), ('or (b2)', gold), ('crypto (b3)', crypto),
                  ('IBS NAS (b4)', ibs4), ('IBS US500 (cand.)', d5)):
        cu = np.cumsum(x.to_numpy()); m = (np.maximum.accumulate(cu) - cu).max()
        print(f"    {nm:<18} R/an {x.sum()/years:+6.1f}  maxDD {m:5.1f} R  -> RoMaD {x.sum()/years/m:4.2f}")


if __name__ == '__main__':
    main()
