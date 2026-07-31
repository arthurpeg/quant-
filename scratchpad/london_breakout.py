"""London Breakout — the QuantifiedStrategies rule, on Pepperstone M1, to the letter.

Article (not paywalled): mark the range of the ASIAN session, then trade the breakout of
that range during the LONDON session. "A breakout above the range signals a potential long,
a breakout below indicates a short." Two range definitions are given:
  * high-low range  — the highest/lowest PRICE of the Asian session
  * open-close range — ignores the wicks, uses the highest/lowest open/close (candle body)
Exit: the article's own backtest exits "at various times between 12:00 and 17:00 London
time", so the exit hour is swept over exactly that span. The article notes the breakout can
also happen the hour before the London open (Frankfurt), so the entry window starts at 07:00.

The article's own verdict is negative ("entering a long position on a breakout above the
high of the Asian session range and exiting at various times between 12:00 and 17:00 London
time often resulted in losses"), so this is a falsification test, not a hunt.

TIMEZONE: the cached MT5 bars are broker EET wall-clock labelled UTC. They MUST go through
edgelab.intraday.orb.to_true_utc before any session logic — this project already burned a
whole experiment on that bug (see the retracted ledger row). Sessions are then evaluated in
Europe/London, which is what the article means by "London time".

    python scratchpad/london_breakout.py
"""
import sys; sys.path.insert(0, '.'); sys.stdout.reconfigure(encoding='utf-8')

import numpy as np
import pandas as pd

from edgelab.intraday.orb import to_true_utc

MT5 = 'data_cache_mt5'
PAIRS = ['EURUSD', 'GBPUSD', 'USDJPY', 'EURJPY', 'AUDUSD', 'USDCAD', 'USDCHF']
# half-spread + slippage in PRICE units, per side (Pepperstone majors, realistic)
COST = {'EURUSD': 0.000075, 'GBPUSD': 0.000105, 'USDJPY': 0.0105, 'EURJPY': 0.0135,
        'AUDUSD': 0.000105, 'USDCAD': 0.000135, 'USDCHF': 0.000135}
ASIA_START, ASIA_END = 0, 8          # Asian range: 00:00-08:00 London
ENTRY_FROM, ENTRY_TO = 7, 12         # breakout window (07:00 = Frankfurt, per the article)


def load_m1(sym: str) -> pd.DataFrame:
    d = pd.read_parquet(f'{MT5}/{sym}_M1.parquet')
    d.columns = [c.lower() for c in d.columns]
    idx = pd.DatetimeIndex(pd.to_datetime(d['time'], utc=True))
    d = d.set_index(to_true_utc(idx))                     # broker EET -> true UTC
    d = d[d.index.notna()][['open', 'high', 'low', 'close']].astype(float).sort_index()
    return d[~d.index.duplicated()]


def run(sym: str, exit_hour: int, body_range: bool = False, both: bool = True,
        stop_opposite: bool = True) -> pd.DataFrame:
    """One trade per day at most. R = the stop distance."""
    d = load_m1(sym)
    lon = d.index.tz_convert('Europe/London')
    d = d.assign(_h=lon.hour, _m=lon.minute, _day=lon.normalize())
    cost = COST[sym]
    trades = []

    for day, g in d.groupby('_day', sort=True):
        asia = g[(g._h >= ASIA_START) & (g._h < ASIA_END)]
        win = g[(g._h >= ENTRY_FROM) & (g._h < ENTRY_TO)]
        out = g[g._h >= exit_hour]
        if len(asia) < 120 or len(win) < 30 or len(out) < 1:
            continue
        if body_range:                                     # candle bodies only
            hi = max(asia['open'].max(), asia['close'].max())
            lo = min(asia['open'].min(), asia['close'].min())
        else:
            hi, lo = asia['high'].max(), asia['low'].min()
        if not np.isfinite(hi) or not np.isfinite(lo) or hi <= lo:
            continue

        c = win['close'].to_numpy(); o = win['open'].to_numpy()
        up = np.flatnonzero(c > hi); dn = np.flatnonzero(c < lo)
        iu = up[0] if len(up) else 10**9
        idn = dn[0] if len(dn) else 10**9
        if min(iu, idn) == 10**9 or min(iu, idn) + 1 >= len(win):
            continue
        direction = 1 if iu < idn else -1
        if not both and direction < 0:
            continue
        k = min(iu, idn) + 1                               # fill at the NEXT M1 open
        entry = o[k]
        # stop = the opposite side of the Asian range (the rule's own level)
        stop = lo if direction > 0 else hi
        risk = abs(entry - stop)
        if risk <= 0:
            continue

        rest = win.iloc[k:]
        after = pd.concat([rest, out]) if len(out) else rest
        exit_px, why = float(out['open'].iloc[0] if len(out) else after['close'].iloc[-1]), 'time'
        if stop_opposite:                                  # intrabar stop, gap-aware
            seg = after[after.index <= (out.index[0] if len(out) else after.index[-1])]
            hit = (seg['low'] <= stop) if direction > 0 else (seg['high'] >= stop)
            if hit.any():
                j = hit.idxmax()
                op = float(seg.loc[j, 'open'])
                exit_px = stop if (op >= stop if direction > 0 else op <= stop) else op
                why = 'stop'
        R = (direction * (exit_px - entry) - 2 * cost) / risk
        trades.append({'day': day, 'dir': direction, 'entry': entry, 'exit': exit_px,
                       'why': why, 'risk': risk, 'R': R})
    return pd.DataFrame(trades)


def t_of(R):
    R = np.asarray(R, float)
    return R.mean() / R.std(ddof=1) * np.sqrt(len(R)) if len(R) > 5 else np.nan


def summarize(tr, label):
    if tr is None or len(tr) < 10:
        return None
    R = tr['R'].to_numpy()
    yrs = max((tr['day'].max() - tr['day'].min()).days / 365.25, .5)
    yr = tr.set_index('day')['R'].groupby(lambda z: z.year).sum()
    loss = -R[R < 0].sum()
    return dict(label=label, n=len(R), ryr=R.sum() / yrs, t=t_of(R),
                pf=R[R > 0].sum() / loss if loss > 0 else np.inf,
                e_r=R.mean(), pyrs=f'{int((yr > 0).sum())}/{len(yr)}')


def table(rows, title):
    rows = [r for r in rows if r]
    print('\n' + '=' * 92); print(f'  {title}'); print('=' * 92)
    print(f"  {'variante / paire':<40}{'n':>6}{'R/an':>8}{'t':>7}{'PF':>6}{'E[R]':>8}{'+ans':>7}")
    for r in sorted(rows, key=lambda x: -x['t']):
        print(f"  {r['label']:<40}{r['n']:>6}{r['ryr']:>+8.2f}{r['t']:>7.2f}"
              f"{r['pf']:>6.2f}{r['e_r']:>+8.3f}{r['pyrs']:>7}")
    return rows


def main():
    import os
    avail = [p for p in PAIRS if os.path.exists(f'{MT5}/{p}_M1.parquet')]
    print(f"  paires avec M1 Pepperstone: {avail}")

    # 1) the article's exact test: exit hour swept 12:00-17:00 London, pooled over pairs
    rows = []
    for eh in (12, 13, 14, 15, 16, 17):
        allR, n, yrs = [], 0, 0
        for p in avail:
            tr = run(p, eh)
            if len(tr) > 10:
                allR.append(tr['R'].to_numpy()); n += len(tr)
                yrs = max(yrs, (tr['day'].max() - tr['day'].min()).days / 365.25)
        R = np.concatenate(allR)
        rows.append(dict(label=f'sortie {eh}:00 Londres (7 paires poolees)', n=len(R),
                         ryr=R.sum() / yrs / len(avail), t=t_of(R), e_r=R.mean(),
                         pf=R[R > 0].sum() / -R[R < 0].sum(), pyrs='-'))
    table(rows, "1) LA REGLE DE L'ARTICLE — balayage de l'heure de sortie 12:00-17:00 Londres")

    # 2) per pair, at the middle of the article's window
    table([summarize(run(p, 15), p) for p in avail],
          "2) PAR PAIRE (sortie 15:00 Londres, stop = cote oppose du range asiatique)")

    # 3) variants
    v = []
    for p in avail:
        v.append(summarize(run(p, 15, body_range=True), f'{p} range open-close'))
    table(v, "3) VARIANTE 'OPEN-CLOSE RANGE' (sans les meches, comme decrit dans l'article)")

    v = []
    for p in avail:
        v.append(summarize(run(p, 15, both=False), f'{p} long seulement'))
    table(v, "4) LONG SEULEMENT (la cassure haussiere que l'article teste explicitement)")


if __name__ == '__main__':
    main()
