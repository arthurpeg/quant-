"""FULL validation: should brick 3's exits be widened (TP 3->6 ATR, time-exit 10->30 bars)?

Everything on the honest LIVE cadence. The candidate came from an in-sample sweep on
BTC+ETH, so the burden of proof is the project's standard battery — the same tests that
killed GER40 and Forecast-to-Fill:

  1  headline + per-year, both configs
  2  bootstrap: P(E[R]<=0), and a PAIRED (by day) CI of the improvement
  3  split-half, and whether the early/late gap is statistically real
  4  WALK-FORWARD: pick the exits on the first half only, score on the untouched second
  5  OOS ASSETS: 8 coins never used to choose anything (ADA BCH DOGE DOT LINK LTC SOL XRP)
  6  is it just beta? long/short split + correlation to the underlying
  7  multiple-testing context (the sweep was ~30 cells -> the bar is t ~ 2.9-3.0)

    python scratchpad/validate_crypto_exits.py
"""
import sys; sys.stdout.reconfigure(encoding='utf-8'); sys.path.insert(0, '.')

import copy
import numpy as np
import pandas as pd

from edgelab.config import load_config
from edgelab.backtest.engine import BacktestEngine
from edgelab.backtest.costs import CostModel
from edgelab.reports.monte_carlo_static import load, macd_rsi

BASE = load_config()
COST = CostModel(10, 3, {'BTCUSD': 5, 'ETHUSD': 8})
COST_OTHER = CostModel(20, 6, {})          # unknown alts -> wider, honest default
W = pd.Timestamp('2018-07-01')
CUR = (3.0, 10)                            # current frozen exits
CAND = (6.0, 30)                           # the candidate
CORE = ('BTCUSD', 'ETHUSD')
OOS = ('ADAUSD', 'BCHUSD', 'DOGEUSD', 'DOTUSD', 'LINKUSD', 'LTCUSD', 'SOLUSD', 'XRPUSD')
_D, _S = {}, {}


def bars(s):
    if s not in _D:
        _D[s] = load(s); _S[s] = macd_rsi(_D[s])
    return _D[s], _S[s]


def run(syms, tp, te, cost=COST, start=W):
    cfg = copy.deepcopy(BASE)
    for k, v in (('take_profit_atr', tp), ('time_exit_bars', te)):
        cfg.raw['risk'][k] = v; cfg.risk[k] = v
    e = BacktestEngine(cfg, cost_model=cost, cadence='live')
    out = []
    for s in syms:
        d, sig = bars(s)
        tr = e.run(d, sig, s, 'x').trades
        if tr.empty:
            continue
        tr['ex'] = pd.to_datetime(tr['exit_time']).dt.tz_localize(None)
        tr['sym'] = s
        out.append(tr[tr['ex'] >= start])
    return pd.concat(out) if out else pd.DataFrame()


def t_of(R):
    R = np.asarray(R, float)
    return R.mean() / R.std(ddof=1) * np.sqrt(len(R)) if len(R) > 2 else np.nan


def daily(tr, idx):
    s = pd.Series(tr['ret'].to_numpy(), index=tr['ex'].dt.normalize())
    return s.groupby(level=0).sum().reindex(idx).fillna(0)


def hdr(x):
    print('\n' + '=' * 92); print(f'  {x}'); print('=' * 92)


def main():
    rng = np.random.default_rng(3)
    cur, cand = run(CORE, *CUR), run(CORE, *CAND)
    yrs = (cand['ex'].max() - cand['ex'].min()).days / 365.25
    idx = pd.date_range(W, max(cur['ex'].max(), cand['ex'].max()), freq='D')

    # ---- 1 headline + per-year ------------------------------------------------
    hdr('1) HEADLINE + PAR ANNEE (BTC+ETH, cadence live, 2018-07+)')
    for lbl, tr in (('actuel  TP3/TE10', cur), ('candidat TP6/TE30', cand)):
        R = tr['ret'].to_numpy()
        print(f'  {lbl:<18} n={len(R):>4} R/yr={R.sum()/yrs:+6.2f} t={t_of(R):5.2f} '
              f'PF={R[R>0].sum()/-R[R<0].sum():4.2f} E[R]={R.mean():+.3f} '
              f'win={100*(R>0).mean():.0f}% bars={tr.bars_held.mean():.1f}')
    yr = pd.DataFrame({'actuel': cur.set_index('ex')['ret'].groupby(lambda z: z.year).sum(),
                       'candidat': cand.set_index('ex')['ret'].groupby(lambda z: z.year).sum()}).round(1)
    print('\n' + yr.to_string())

    # ---- 2 bootstrap ----------------------------------------------------------
    hdr('2) BOOTSTRAP (10k) — le candidat est-il > 0, et > l\'actuel ?')
    Rc = cand['ret'].to_numpy()
    bs = np.array([rng.choice(Rc, len(Rc), replace=True).mean() for _ in range(10000)])
    print(f'  candidat  E[R]={Rc.mean():+.3f}  P(E[R]<=0) = {(bs <= 0).mean():.4f}  '
          f'IC95% [{np.percentile(bs,2.5):+.3f}, {np.percentile(bs,97.5):+.3f}]')
    dc, dd = daily(cur, idx), daily(cand, idx)
    diff = (dd - dc).to_numpy()                      # PAIRED by calendar day
    bd = np.array([rng.choice(diff, len(diff), replace=True).sum() for _ in range(10000)])
    print(f'  ecart quotidien apparie (candidat - actuel): total {diff.sum():+.1f} R sur {yrs:.1f} ans')
    print(f'  IC95% de l\'ecart TOTAL = [{np.percentile(bd,2.5):+.1f}, {np.percentile(bd,97.5):+.1f}] R'
          f'  -> P(candidat <= actuel) = {(bd <= 0).mean():.4f}')

    # ---- 3 split-half ---------------------------------------------------------
    hdr('3) SPLIT-HALF — et la faiblesse recente est-elle SIGNIFICATIVE ?')
    for lbl, tr in (('actuel', cur), ('candidat', cand)):
        mid = tr['ex'].quantile(0.5)
        e1 = tr[tr['ex'] < mid]['ret'].to_numpy(); e2 = tr[tr['ex'] >= mid]['ret'].to_numpy()
        d = np.array([rng.choice(e1, len(e1), True).mean() - rng.choice(e2, len(e2), True).mean()
                      for _ in range(10000)])
        print(f'  {lbl:<9} early t={t_of(e1):5.2f} (E[R] {e1.mean():+.3f}) | '
              f'late t={t_of(e2):5.2f} (E[R] {e2.mean():+.3f}) | '
              f'IC95% early-late [{np.percentile(d,2.5):+.3f}, {np.percentile(d,97.5):+.3f}]'
              f'{"  -> ecart NON significatif" if np.percentile(d,2.5) <= 0 <= np.percentile(d,97.5) else "  -> DEGRADATION REELLE"}')

    # ---- 4 walk-forward -------------------------------------------------------
    hdr('4) WALK-FORWARD — choisir les sorties sur la 1re moitie SEULEMENT, scorer sur la 2e')
    MID = pd.Timestamp('2022-07-01')
    best, bt = None, -9
    for tp in (3., 4., 5., 6., 7., 8.):
        for te in (10, 15, 20, 25, 30, 35, 40):
            tr = run(CORE, tp, te); tr = tr[tr['ex'] < MID]
            v = t_of(tr['ret'].to_numpy())
            if v > bt:
                bt, best = v, (tp, te)
    print(f'  meilleur sur 2018-07..2022-06 (42 cellules) = TP{best[0]:.0f}/TE{best[1]} (t={bt:.2f} in-sample)')
    for lbl, cfgp in (('choisi en WF', best), ('actuel', CUR), ('candidat', CAND)):
        tr = run(CORE, *cfgp); oo = tr[tr['ex'] >= MID]['ret'].to_numpy()
        y2 = (tr[tr['ex'] >= MID]['ex'].max() - MID).days / 365.25
        print(f'    -> OOS 2022-07..2026-07  {lbl:<13} TP{cfgp[0]:.0f}/TE{cfgp[1]:<3} '
              f'n={len(oo):>3} R/yr={oo.sum()/y2:+6.2f} t={t_of(oo):5.2f}')

    # ---- 5 OOS assets ---------------------------------------------------------
    hdr('5) ACTIFS OOS — 8 coins jamais utilises pour choisir quoi que ce soit')
    print(f'  {"coin":<9}{"n cur":>7}{"R/yr cur":>10}{"t cur":>7}   {"n cand":>7}{"R/yr cand":>11}{"t cand":>8}')
    tot = {CUR: [], CAND: []}
    for s in OOS:
        line = f'  {s:<9}'
        for cfgp in (CUR, CAND):
            tr = run([s], *cfgp, cost=COST_OTHER, start=pd.Timestamp('2021-01-01'))
            R = tr['ret'].to_numpy() if len(tr) else np.array([])
            tot[cfgp].append(R)
            y = (tr['ex'].max() - tr['ex'].min()).days / 365.25 if len(tr) > 1 else 1
            line += f'{len(R):>7}{R.sum()/y:>10.2f}{t_of(R):>7.2f}   ' if len(R) > 2 else f'{"-":>7}{"-":>10}{"-":>7}   '
        print(line)
    for cfgp, lbl in ((CUR, 'actuel'), (CAND, 'candidat')):
        P = np.concatenate([r for r in tot[cfgp] if len(r)])
        print(f'  POOL 8 coins {lbl:<9} n={len(P):>4} E[R]={P.mean():+.3f} t={t_of(P):5.2f} '
              f'PF={P[P>0].sum()/-P[P<0].sum():4.2f}')

    # ---- 6 beta? --------------------------------------------------------------
    hdr('6) EST-CE JUSTE DU BETA ? (tenir plus longtemps = plus d\'exposition)')
    btc = bars('BTCUSD')[0]['close'].pct_change()
    btc.index = pd.DatetimeIndex(btc.index).tz_localize(None).normalize()
    btc = btc.reindex(idx).fillna(0)
    for lbl, tr, d in (('actuel', cur, dc), ('candidat', cand, dd)):
        lo = tr[tr.direction > 0]['ret']; sh = tr[tr.direction < 0]['ret']
        print(f'  {lbl:<9} LONG n={len(lo):>3} R={lo.sum():+6.1f} t={t_of(lo):5.2f} | '
              f'SHORT n={len(sh):>3} R={sh.sum():+6.1f} t={t_of(sh):5.2f} | '
              f'corr(R quotidien, BTC) = {d.corr(btc):+.3f}')
    print('  (si le gain venait du beta, les SHORTS se degraderaient et la corr monterait fort)')


if __name__ == '__main__':
    main()
