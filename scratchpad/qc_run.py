"""Stage 5 — backtest the Quantocracy strategies that are fully specified and in scope.

Survivors of the funnel (7606 links -> 231 fetched -> 144 with text -> these):

  Q1 Bitcoin hour-of-day seasonality [Quantpedia]
     "buy Bitcoin at 21:00 (UTC+0) and sell it at 23:00 (UTC+0)"  -- verbatim
  Q2 FX time-of-day [Quant Journey]
     "Short at GMT 09:15 am, do this on Wednesday, Thursday and Friday, close after 5 hours"
     (the article's own comment section objects that it is just the post-2008 EURUSD
     downtrend -- so the falsification is built in and gets tested)
  Q3 Bitcoin 10-day-high breakout [Quantpedia]
     "Enter a long position when a new 10-day high is reached. Close position when the
     current close price is not a 10-day high."
  Q4 Bitcoin overnight on a local high [Quantpedia]
     "buy Bitcoin at NYSE close when Bitcoin is on the local X-day high, hold [overnight]",
     X in {5,10,20,30,40,50} as listed; plus the weekday-night variants the article names.

Rejected at the read stage: DTR Trading (RUT iron condors = options), Alvarez (country-ETF
rotation, dividend screens, Hi-Lo breadth index = stock universes / external data),
Black Arbs (2-asset allocation), Allocate Smartly (monthly TSM -- ledger-killed), Rulyfi
(meta-research on backtest overfitting, not a strategy), Quantpedia MACD-on-Bitcoin
(= brick 3's family, already in the book).

Conventions: R = 2.5 x ATR14 of the entry timeframe (the articles give no stop, and R needs
one); cost = Pepperstone-realistic per instrument; timezone via to_true_utc.

    python scratchpad/qc_run.py
"""
import sys; sys.path.insert(0, '.'); sys.stdout.reconfigure(encoding='utf-8')

import numpy as np
import pandas as pd

from edgelab.intraday.orb import to_true_utc

MT5 = 'data_cache_mt5'
COST = {'BTCUSD': 35.0, 'ETHUSD': 2.0, 'EURUSD': 0.00015, 'GBPUSD': 0.00021,
        'USDJPY': 0.021, 'EURJPY': 0.027, 'AUDUSD': 0.00021, 'USDCAD': 0.00027,
        'USDCHF': 0.00027}


def load(sym, tf):
    import os
    pq, cs = f'{MT5}/{sym}_{tf}.parquet', f'{MT5}/{sym}_{tf}.csv'
    if os.path.exists(pq):
        d = pd.read_parquet(pq)
    elif os.path.exists(cs):
        d = pd.read_csv(cs)
    else:
        raise FileNotFoundError(f'{sym} {tf}')
    d.columns = [c.lower() for c in d.columns]
    idx = pd.DatetimeIndex(pd.to_datetime(d['time'], utc=True))
    d = d.set_index(to_true_utc(idx))
    d = d[d.index.notna()][['open', 'high', 'low', 'close']].astype(float).sort_index()
    return d[~d.index.duplicated()]


def atr(d, n=14):
    h, l, c = d['high'], d['low'], d['close']
    pc = c.shift(1)
    tr = pd.concat([(h - l), (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / n, adjust=False).mean()


def t_of(R):
    R = np.asarray(R, float)
    return R.mean() / R.std(ddof=1) * np.sqrt(len(R)) if len(R) > 5 else np.nan


def summarize(R, dates, label):
    R = np.asarray(R, float)
    if len(R) < 10:
        return dict(label=label, n=len(R), ryr=0, t=np.nan, pf=np.nan, e_r=0, pyrs='-')
    dates = pd.DatetimeIndex(dates)
    yrs = max((dates.max() - dates.min()).days / 365.25, .5)
    yr = pd.Series(R, index=dates).groupby(lambda z: z.year).sum()
    loss = -R[R < 0].sum()
    return dict(label=label, n=len(R), ryr=R.sum() / yrs, t=t_of(R),
                pf=R[R > 0].sum() / loss if loss > 0 else np.inf, e_r=R.mean(),
                pyrs=f'{int((yr > 0).sum())}/{len(yr)}')


def table(rows, title):
    rows = [r for r in rows if r and r['n'] >= 10]
    print('\n' + '=' * 92); print(f'  {title}'); print('=' * 92)
    print(f"  {'variante':<44}{'n':>6}{'R/an':>8}{'t':>7}{'PF':>6}{'E[R]':>8}{'+ans':>7}")
    for r in sorted(rows, key=lambda x: -(x['t'] if np.isfinite(x['t']) else -9)):
        print(f"  {r['label']:<44}{r['n']:>6}{r['ryr']:>+8.2f}{r['t']:>7.2f}"
              f"{r['pf']:>6.2f}{r['e_r']:>+8.3f}{r['pyrs']:>7}")


def hourly_window(sym, tf, buy_h, sell_h, direction=1, days=None, sl_atr=2.5):
    """Enter at the open of the `buy_h` bar, exit at the open of the `sell_h` bar (UTC)."""
    d = load(sym, tf)
    a = atr(d).shift(1)
    h = d.index.hour
    R, dts = [], []
    for day, g in d.groupby(d.index.normalize()):
        if days is not None and day.dayofweek not in days:
            continue
        gi = g.index.hour
        bi = np.flatnonzero(gi == buy_h)
        si = np.flatnonzero(gi == sell_h)
        if not len(bi) or not len(si) or si[0] <= bi[0]:
            continue
        e = float(g['open'].iloc[bi[0]]); x = float(g['open'].iloc[si[0]])
        rv = a.get(g.index[bi[0]], np.nan)
        if not np.isfinite(rv) or rv <= 0:
            continue
        risk = sl_atr * rv
        R.append((direction * (x - e) - COST[sym]) / risk); dts.append(day)
    return R, dts


def main():
    # ---- Q1 -----------------------------------------------------------------------
    rows = [summarize(*hourly_window('BTCUSD', 'H1', 21, 23), 'Q1 BTC achat 21:00 UTC -> vente 23:00 UTC')]
    for b, s in ((20, 22), (21, 22), (22, 0), (19, 23), (21, 1)):
        rr, dd = hourly_window('BTCUSD', 'H1', b, s)
        rows.append(summarize(rr, dd, f'   voisinage {b:02d}:00 -> {s:02d}:00'))
    table(rows, "Q1 [Quantpedia] SAISONNALITE HORAIRE BITCOIN — la regle verbatim + son voisinage")

    # ---- Q2 -----------------------------------------------------------------------
    rows = []
    for p in ('EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD', 'USDCAD', 'USDCHF', 'EURJPY'):
        try:
            rr, dd = hourly_window(p, 'H1', 9, 14, direction=-1, days={2, 3, 4})
        except FileNotFoundError:
            continue
        rows.append(summarize(rr, dd, f'Q2 {p} short 09h GMT mer/jeu/ven, 5h'))
    table(rows, "Q2 [Quant Journey] SHORT FX A 09:15 GMT, MER/JEU/VEN, SORTIE +5h")
    # the article's own objection: is it just the EURUSD downtrend? -> split the sample
    rr, dd = hourly_window('EURUSD', 'H1', 9, 14, direction=-1, days={2, 3, 4})
    s = pd.Series(rr, index=pd.DatetimeIndex(dd))
    half = s.index[len(s) // 2]
    print(f"\n  objection de l'article (ce n'est que la tendance baissiere EURUSD) :")
    print(f"    1ere moitie ({s.index.min():%Y-%m}..{half:%Y-%m}) t={t_of(s[:half]):.2f} | "
          f"2e moitie ({half:%Y-%m}..{s.index.max():%Y-%m}) t={t_of(s[half:]):.2f}")
    rl, dl = hourly_window('EURUSD', 'H1', 9, 14, direction=+1, days={2, 3, 4})
    print(f"    le LONG symetrique (meme fenetre) : t={t_of(rl):.2f}  "
          f"-> si le short marche par simple biais directionnel, le long doit perdre autant")

    # ---- Q3 / Q4 -------------------------------------------------------------------
    rows = []
    for sym in ('BTCUSD', 'ETHUSD'):
        d = load(sym, 'D1'); a = atr(d).shift(1)
        hi10 = d['high'].rolling(10).max()
        entry = d['close'] >= hi10                      # new 10-day high
        exitc = d['close'] < hi10                        # no longer a 10-day high
        o = d['open'].to_numpy(); R, dts = [], []
        inpos, ep, risk = False, 0., 0.
        en, ex = entry.to_numpy(), exitc.to_numpy(); av = a.to_numpy()
        for i in range(1, len(d)):
            if inpos and ex[i - 1]:
                R.append((o[i] - ep - COST[sym]) / risk); dts.append(d.index[i]); inpos = False
            if not inpos and en[i - 1] and np.isfinite(av[i - 1]) and av[i - 1] > 0:
                ep, risk, inpos = o[i], 2.5 * av[i - 1], True
        rows.append(summarize(R, dts, f'Q3 {sym} plus-haut 10j -> sortie hors plus-haut'))
    table(rows, "Q3 [Quantpedia] CASSURE DU PLUS-HAUT 10 JOURS (crypto)")

    rows = []
    for X in (5, 10, 20, 30, 40, 50):
        d1 = load('BTCUSD', 'D1'); h1 = load('BTCUSD', 'H1')
        hi = d1['high'].rolling(X).max()
        onhigh = (d1['close'] >= hi)
        a = atr(d1).shift(1)
        R, dts = [], []
        for day, g in h1.groupby(h1.index.normalize()):
            gi = g.index.hour
            ci = np.flatnonzero(gi == 21)               # NYSE close = 21:00 UTC
            if not len(ci):
                continue
            prev = onhigh.reindex([day]).iloc[0] if day in onhigh.index else False
            if not prev:
                continue
            nxt = h1[(h1.index > g.index[ci[0]])]
            nn = nxt[nxt.index.hour == 14]              # NYSE open = 14:30 UTC (14:00 bar)
            if not len(nn):
                continue
            e = float(g['open'].iloc[ci[0]]); x = float(nn['open'].iloc[0])
            rv = a.reindex([day]).iloc[0] if day in a.index else np.nan
            if not np.isfinite(rv) or rv <= 0:
                continue
            R.append((x - e - COST['BTCUSD']) / (2.5 * rv)); dts.append(day)
        rows.append(summarize(R, dts, f'Q4 BTC nuit apres plus-haut {X}j'))
    table(rows, "Q4 [Quantpedia] BTC ACHAT CLOTURE NYSE SUR PLUS-HAUT Xj -> VENTE OUVERTURE NYSE")


if __name__ == '__main__':
    main()
