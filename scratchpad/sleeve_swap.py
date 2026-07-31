"""Does SWAPPING a thin brick for a brick-4-calibre one beat just ADDING it?

User question: "would finding a brick of the same calibre as #4 and replacing #2 with it
smooth the DD and potentially raise returns?"

The honest test needs a real decorrelated sleeve, not a hypothetical one. We use the
strongest validated-but-not-added candidate from the ledger: GER40 (DAX) EU-open ATR
breakout, high-vol regime, both directions, M1 (t=2.28 net, +10.2 R/yr, corr ~0 to all
three original bricks) — see wiki/Failed Ideas/ledger.md.

Configurations compared on the canonical daily-R construction (same as the reports):
  A  current 4-brick
  B  A minus gold        (is gold even earning its seat?)
  C  A minus gold plus GER40   (the SWAP the question asks about)
  D  A plus GER40             (just ADD it, 5 sleeves)

Reported per config: R/yr, maxDD, Sharpe, RoMaD — and then the part that actually decides
it on a prop account: the worst day, the sizing the -5% daily rule allows, and the
resulting %/yr. In R the answer is trivial (more uncorrelated edges = better); the daily
loss limit is the scarce resource the sleeves compete for.

    python scratchpad/sleeve_swap.py
"""
import sys; sys.stdout.reconfigure(encoding='utf-8'); sys.path.insert(0, '.')

import numpy as np
import pandas as pd

from edgelab.intraday.atr_breakout import run_atr_breakout, ATRBreakParams
from edgelab.reports.monte_carlo_static import build_daily_R, START

DAILY_LIMIT = 0.05          # prop: -5% in one day
TOTAL_DD = 0.10             # prop: -10% static floor


def ger40_daily(idx) -> pd.Series:
    """GER40 EU-open ATR breakout, high-vol regime — the ledger's ⭐ candidate."""
    p = ATRBreakParams(session_open="09:00", entry_cutoff="10:35", session_close="17:25",
                       tz="Europe/Berlin", regime_mode="high", direction="both")
    t = run_atr_breakout("GER40", p, "M1").trades
    ix = pd.DatetimeIndex(pd.to_datetime(t["exit_time"]))
    ix = ix.tz_localize(None) if ix.tz is not None else ix
    s = pd.Series(t["R"].to_numpy(), index=ix)
    s = s[s.index >= START]
    return s.groupby(s.index.normalize()).sum().reindex(idx).fillna(0)


def stats(parts, label, years):
    R = sum(parts).to_numpy()
    cum = np.cumsum(R)
    mdd = float((np.maximum.accumulate(cum) - cum).max())
    act = R[R != 0]
    ryr = R.sum() / years
    worst = float(R.min())
    # A prop account has TWO ceilings; the binding one is whichever bites first.
    r_daily = DAILY_LIMIT / abs(worst)      # -5% in a day, vs the worst day ever seen
    r_dd = TOTAL_DD / mdd                   # -10% static floor, vs the worst drawdown
    r_max = min(r_daily, r_dd)
    return dict(label=label, ryr=ryr, mdd=mdd, romad=ryr / mdd,
                sharpe=float(act.mean() / act.std() * np.sqrt(252)),
                worst=worst, r_daily=r_daily, r_dd=r_dd, r_max=r_max,
                binds="daily" if r_daily < r_dd else "totalDD",
                pct_yr=ryr * r_max * 100)


def main():
    R, parts, (start, end), trades = build_daily_R()
    years = (end - start).days / 365.25
    idx = pd.date_range(start, end, freq='D')
    nas, gold, crypto, ibs = parts
    ger = ger40_daily(idx)

    print("=" * 96)
    print("  SLEEVE ECONOMICS — what each brick contributes on its own")
    print("=" * 96)
    print(f"  {'sleeve':<22} {'R/yr':>7} {'daily vol':>10} {'Sharpe':>7} {'worst day':>10} {'trades/yr':>10}")
    named = [("NAS breakout (b1)", nas), ("gold ToM (b2)", gold), ("crypto MACD (b3)", crypto),
             ("IBS reversion (b4)", ibs), ("GER40 ORB (cand.)", ger)]
    for nm, s in named:
        a = s[s != 0].to_numpy()
        sh = a.mean() / a.std() * np.sqrt(252) if len(a) > 1 else float('nan')
        print(f"  {nm:<22} {s.sum()/years:>+7.1f} {a.std():>10.3f} {sh:>7.2f} "
              f"{s.min():>+10.2f} {len(a)/years:>10.0f}")

    print()
    print("=" * 96)
    print("  CONFIGURATIONS   (equal 1R/trade, no compounding, 2018-07..2026-07)")
    print("=" * 96)
    # E: a REAL same-family addition (IBS on US500 — exp-009's alternative name)
    from edgelab.edges.ibs import run_ibs, IBSParams
    t5 = run_ibs('US500', IBSParams(sl_atr=2.5), cadence='live')
    s5 = pd.Series(t5['R'].to_numpy(), index=pd.DatetimeIndex(pd.to_datetime(t5['exit_dt'])))
    s5 = s5[s5.index >= START]
    ibs5 = s5.groupby(s5.index.normalize()).sum().reindex(idx).fillna(0)

    # F: the THEORETICAL upper bound — a sleeve with IBS's exact return distribution but
    # INDEPENDENT timing (its days shuffled), i.e. "another brick of brick-4 calibre".
    # Averaged over seeds so the answer is not one lucky permutation.
    rng = np.random.default_rng(11)
    synth = []
    for _ in range(200):
        v = ibs.to_numpy().copy()
        rng.shuffle(v)
        synth.append(pd.Series(v, index=idx))

    cfgs = [
        ("A  current 4-brick",              [nas, gold, crypto, ibs]),
        ("B  A - gold",                     [nas, crypto, ibs]),
        ("C  A - gold + GER40  (SWAP)",     [nas, crypto, ibs, ger]),
        ("D  A + GER40         (ADD)",      [nas, gold, crypto, ibs, ger]),
        ("E  A + IBS US500     (ADD)",      [nas, gold, crypto, ibs, ibs5]),
    ]
    rows = [stats(p, n, years) for n, p in cfgs]
    fs = [stats([nas, gold, crypto, ibs, s], "F", years) for s in synth]
    rows.append({k: (np.mean([f[k] for f in fs]) if isinstance(fs[0][k], float) else fs[0][k])
                 for k in fs[0]} | {'label': "F  A + IBS-calibre indep. (ADD)"})

    print(f"  {'config':<32} {'R/yr':>7} {'maxDD':>7} {'RoMaD':>6} {'Sharpe':>7} "
          f"{'worst d':>8} {'ceiling':>9} {'binds':>8} {'%/yr':>7}")
    for r in rows:
        print(f"  {r['label']:<32} {r['ryr']:>+7.1f} {r['mdd']:>7.1f} {r['romad']:>6.2f} "
              f"{r['sharpe']:>7.2f} {r['worst']:>+8.2f} {r['r_max']*100:>8.2f}% "
              f"{r['binds']:>8} {r['pct_yr']:>6.1f}%")

    base = rows[0]
    print(f"\n  deltas vs A (current) — %/yr is at each config's OWN risk ceiling (= equal risk):")
    for r in rows[1:]:
        print(f"    {r['label']:<32} R/yr {r['ryr']-base['ryr']:+5.1f} | maxDD {r['mdd']-base['mdd']:+5.1f} "
              f"| RoMaD {r['romad']-base['romad']:+5.2f} | Sharpe {r['sharpe']-base['sharpe']:+5.2f} "
              f"| %/yr {r['pct_yr']-base['pct_yr']:+5.1f} pts")

    # correlation of the candidate to what is already there
    print()
    df = pd.DataFrame({'NAS': nas, 'Gold': gold, 'Crypto': crypto, 'IBS': ibs, 'GER40': ger})
    print("  GER40 corr to the book:",
          ", ".join(f"{k} {df['GER40'].corr(df[k]):+.3f}" for k in ('NAS', 'Gold', 'Crypto', 'IBS')))

    # how often do sleeves lose together on the SAME day? (what sets the worst day)
    print("\n  worst 5 days of config A vs D (which sleeves fire together):")
    tot_a = sum([nas, gold, crypto, ibs])
    for d in tot_a.nsmallest(5).index:
        print(f"    {d:%Y-%m-%d}  total {tot_a[d]:+6.2f} R  = NAS {nas[d]:+.2f} gold {gold[d]:+.2f} "
              f"crypto {crypto[d]:+.2f} IBS {ibs[d]:+.2f} | GER40 would add {ger[d]:+.2f}")


if __name__ == '__main__':
    main()
