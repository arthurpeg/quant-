"""Kaufman (TSaM 5th ed.) intraday study -- indicators, sessions, and a bracket engine
that can force a trade flat before the session close.

Why a new engine rather than `gold_lib.outcomes`: the user's constraint is *purely
intraday* -- every position must be closed before the session ends. `gold_lib` caps a
trade by a fixed number of bars, which is not the same thing (a trade opened 3 bars
before the close must die at the close, one opened at the open may live all day). So the
outcome table here carries a per-entry DEADLINE bar index.

Everything else is deliberately identical to the rest of the project, so a number here is
comparable to a number in the ledger:
  * decision at bar i's CLOSE, fill at the OPEN of bar i+1 (no intrabar look-ahead);
  * one position at a time, re-arm on the bar the position closes;
  * a bar spanning both barriers is resolved PESSIMISTICALLY as the stop;
  * a gap through a barrier fills at the worse of (barrier, open);
  * cost = max(feed spread, live spread) + 2 slippage points + raw-account commission,
    charged once per trade at the SIGNAL bar's spread;
  * R = that trade's own initial stop distance, so a full stop-out is -1R net of cost.

`outcomes()` with `deadline=None` is verified bar-for-bar against `gold_lib.outcomes`
(see kauf_verify.py).
"""
import os
import json
import numpy as np
import pandas as pd

DATA = (r'C:\Users\arthu\AppData\Local\Temp\claude'
        r'\C--Users-arthu-OneDrive-Documents-ML-quantitatif'
        r'\0660f117-29a2-446a-9569-50c2946831ce\scratchpad\kauf_data')
# 2026-08-09: the 2026-08-07 session's temp dir (DATA above) was purged, taking
# specs.json and the M15 pulls with it. Fall back to the repo-local rebuild
# (scratchpad/inx_data.py: `point` from MT5, feed spread floored on its own
# IN-SESSION 6-month median). Strictly additive — if the old dir is still there it
# still wins, so any earlier run reproduces byte-for-byte.
_SPEC_PATHS = [os.path.join(DATA, 'specs.json'),
               os.path.join('scratchpad', '_inx', 'specs.json'),
               os.path.join(os.path.dirname(os.path.abspath(__file__)), '_inx', 'specs.json')]
SPECS = None
for _p in _SPEC_PATHS:
    if os.path.exists(_p):
        SPECS = json.load(open(_p))
        break
if SPECS is None:
    raise FileNotFoundError('no specs.json - run `python scratchpad/inx_data.py` first')

# MT5 stamps bars with the BROKER SERVER wall clock but labels them UTC. Reinterpret
# before any session logic runs -- the project convention (edgelab.intraday.orb).
SERVER_TZ = 'Europe/Athens'
SLIP_PTS = 1.0
COMMISSION_PTS = {s: 6.0 for s in ('EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD', 'USDCAD',
                                   'USDCHF', 'NZDUSD', 'EURJPY', 'XAUUSD')}
WARMUP = 250          # bars skipped at the head, as in the rest of the project
ATR_N = 14

FX = ('EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD', 'USDCAD', 'USDCHF', 'NZDUSD', 'EURJPY')
METAL = ('XAUUSD', 'XAGUSD')
US_IDX = ('NAS100', 'US500', 'US30', 'US2000')
EU_IDX = ('GER40', 'FRA40', 'UK100', 'SWI20', 'NETH25')
CRYPTO = ('BTCUSD', 'ETHUSD')

# Per asset class: (session timezone, entry window open, last entry, forced-flat time).
# The forced flat is always strictly before the venue's own close, so the exit is a
# market order into a liquid book rather than an auction print.
SESSION = {
    'us_idx': ('America/New_York', '09:30', '15:30', '15:55'),
    'eu_idx': ('Europe/Berlin',    '09:00', '17:00', '17:25'),
    'uk_idx': ('Europe/London',    '08:00', '16:00', '16:25'),
    'fx':     ('Europe/London',    '07:00', '19:00', '20:55'),   # London open -> pre-rollover
    'crypto': ('UTC',              '00:00', '21:00', '23:45'),
}


def klass(sym):
    if sym in US_IDX:
        return 'us_idx'
    if sym == 'UK100':
        return 'uk_idx'
    if sym in EU_IDX:
        return 'eu_idx'
    if sym in CRYPTO:
        return 'crypto'
    return 'fx'          # FX majors and gold both trade the London/NY day


def to_true_utc(idx):
    naive = idx.tz_convert('UTC').tz_localize(None) if idx.tz is not None else idx
    return naive.tz_localize(SERVER_TZ, ambiguous='NaT',
                             nonexistent='NaT').tz_convert('UTC')


# --------------------------------------------------------------------------------
# indicators -- Kaufman's own definitions
# --------------------------------------------------------------------------------
def atr(h, l, c, n=ATR_N):
    """Wilder ATR, matching mt4_indicators.atr used everywhere else here."""
    pc = np.concatenate(([c[0]], c[:-1]))
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    out = np.full(len(c), np.nan)
    if len(c) <= n:
        return out
    out[n - 1] = tr[:n].mean()
    for i in range(n, len(c)):
        out[i] = (out[i - 1] * (n - 1) + tr[i]) / n
    return out


def efficiency_ratio(c, n=10):
    """Kaufman's efficiency ratio / fractal efficiency (TSaM ch.1 p.10, ch.17 p.781).

        ER_t = |C_t - C_{t-n}| / sum_{i=t-n+1..t} |C_i - C_{i-1}|

    1.0 = a straight line over n bars (no noise), 0.0 = pure back-and-forth.
    """
    d = np.abs(np.diff(c, prepend=c[0]))
    vol = pd.Series(d).rolling(n).sum().to_numpy()
    net = np.full(len(c), np.nan)
    net[n:] = np.abs(c[n:] - c[:-n])
    with np.errstate(invalid='ignore', divide='ignore'):
        er = np.where(vol > 0, net / vol, np.nan)
    er[:n] = np.nan
    return er


def kama(c, er, fast=2, slow=30):
    """Kaufman's Adaptive Moving Average (TSaM ch.17 p.780).

        sc_t  = [ ER_t * (2/(fast+1) - 2/(slow+1)) + 2/(slow+1) ]^2
        KAMA_t = KAMA_{t-1} + sc_t * (C_t - KAMA_{t-1})
    """
    f, s = 2.0 / (fast + 1), 2.0 / (slow + 1)
    sc = (np.nan_to_num(er) * (f - s) + s) ** 2
    out = np.full(len(c), np.nan)
    start = int(np.argmax(np.isfinite(er))) if np.isfinite(er).any() else len(c)
    if start >= len(c):
        return out
    out[start] = c[start]
    for i in range(start + 1, len(c)):
        out[i] = out[i - 1] + sc[i] * (c[i] - out[i - 1])
    return out


def rolling_pct_rank(x, w):
    """Percentile rank of x_t inside its own trailing window of w bars, in [0,1].

    Causal: the window ENDS at t and includes it, exactly as a trader would rank today's
    reading against the recent past. Used to turn the raw efficiency ratio into a
    per-asset noise STATE without importing a cross-asset constant."""
    s = pd.Series(x)
    return s.rolling(w, min_periods=max(20, w // 4)).rank(pct=True).to_numpy()


# --------------------------------------------------------------------------------
# bars
# --------------------------------------------------------------------------------
_cache = {}


def load(sym, tf, source='pull'):
    """Bars in TRUE UTC. source='pull' = the M15/M5 pulled for this study;
    source='m1' = resample the project's long M1 cache up to `tf`."""
    key = (sym, tf, source)
    if key in _cache:
        return _cache[key]
    if source == 'cache':
        # the project's own data_cache_mt5 (D1/H1/H4), parquet or csv
        pq = os.path.join('data_cache_mt5', f'{sym}_{tf}.parquet')
        cs = os.path.join('data_cache_mt5', f'{sym}_{tf}.csv')
        if os.path.exists(pq):
            d = pd.read_parquet(pq)
        elif os.path.exists(cs):
            d = pd.read_csv(cs)
        else:
            return None
        d.columns = [c.lower() for c in d.columns]
    elif source == 'inx':
        # M5/M15/M30 resampled from the M1 cache, or native M10 (scratchpad/inx_data.py).
        # inx_data already returns a TRUE-UTC index, so return before the shared
        # server-time reinterpretation below (applying it twice would shift sessions).
        import inx_data
        d = inx_data.bars(sym, tf)
        if d is None or not len(d):
            return None
        _cache[key] = d.sort_index()
        return _cache[key]
    elif source == 'pull':
        p = os.path.join(DATA, f'{sym}_{tf}.parquet')
        if not os.path.exists(p):
            return None
        d = pd.read_parquet(p)
    else:
        p = os.path.join('data_cache_mt5', f'{sym}_M1.parquet')
        if not os.path.exists(p):
            return None
        d = pd.read_parquet(p)
        rule = {'M15': '15min', 'M30': '30min', 'H1': '1h', 'M5': '5min'}[tf]
        d = (d.set_index('time')
               .resample(rule, label='left', closed='left')
               .agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last',
                     'tick_volume': 'sum', 'spread': 'median'})
               .dropna(subset=['open'])
               .reset_index())
    d['time'] = pd.to_datetime(d['time'], utc=True)
    idx = to_true_utc(pd.DatetimeIndex(d['time']))
    d = d.loc[idx.notna()].copy()
    d.index = idx[idx.notna()]
    d = d.sort_index()
    _cache[key] = d
    return d


class Bars:
    """One (symbol, timeframe): price arrays, Kaufman indicators, session masks, cost."""

    def __init__(self, sym, tf, source='pull', er_n=10, rank_days=20, min_bars=2000):
        d = load(sym, tf, source)
        if d is None or len(d) < min_bars:
            raise ValueError(f'no usable bars for {sym} {tf} ({source})')
        self.sym, self.tf, self.source, self.d = sym, tf, source, d
        self.o = d['open'].to_numpy(float)
        self.h = d['high'].to_numpy(float)
        self.l = d['low'].to_numpy(float)
        self.c = d['close'].to_numpy(float)
        self.n = len(self.c)
        self.time = d.index
        self.atr = atr(self.h, self.l, self.c)
        self.er = efficiency_ratio(self.c, er_n)
        self.kama = kama(self.c, self.er)

        # --- session structure -------------------------------------------------
        tz, t_open, t_last, t_flat = SESSION[klass(sym)]
        loc = d.index.tz_convert(tz)
        mins = loc.hour * 60 + loc.minute
        def hm(s):
            a, b = s.split(':')
            return int(a) * 60 + int(b)
        mins = np.asarray(mins)
        dow = np.asarray(loc.dayofweek)
        wk = np.ones(len(mins), bool) if klass(sym) == 'crypto' else (dow < 5)
        self.in_window = (mins >= hm(t_open)) & (mins <= hm(t_last)) & wk
        after_flat = mins >= hm(t_flat)
        # session id: a new session starts at the local calendar-day boundary of the
        # session timezone (crypto included -- its "day" is the UTC day).
        day = loc.normalize()
        self.sess = pd.factorize(day)[0]
        # deadline[i] = the LAST bar index at which a position opened at/ before i may
        # still be held. It is the last bar of i's session that is strictly before the
        # forced-flat time; a trade still open there exits at that bar's close.
        ok_hold = ~after_flat
        self.deadline = self._deadlines(self.sess, ok_hold)

        # --- friction ----------------------------------------------------------
        sp = SPECS[sym]
        spr = d['spread'].to_numpy(float) if 'spread' in d else np.zeros(self.n)
        self.point = sp['point']
        self.comm = COMMISSION_PTS.get(sym, 0.0)
        self.spread_pts = np.maximum(spr, sp['spread_now'])
        self.rt = (self.spread_pts + 2 * SLIP_PTS + self.comm) * self.point
        self.spread_px = self.spread_pts * self.point
        # bars per session, used to size the noise-state ranking window
        cnt = pd.Series(1, index=self.sess).groupby(level=0).sum()
        self.bars_per_sess = float(np.median(cnt.to_numpy()))
        self.rank_w = max(50, int(round(self.bars_per_sess * rank_days)))
        self.er_rank = rolling_pct_rank(self.er, self.rank_w)

    @staticmethod
    def _deadlines(sess, ok_hold):
        """Last holdable bar index of each bar's own session."""
        n = len(sess)
        dl = np.full(n, -1, dtype=np.int64)
        last = -1
        for i in range(n - 1, -1, -1):
            if i == n - 1 or sess[i] != sess[i + 1]:
                last = -1                      # entering a new session from the right
            if ok_hold[i]:
                last = i if last < 0 else max(last, i)
            dl[i] = last
        # a bar past its session's flat time gets its own index (nothing can be held)
        dl[dl < 0] = np.arange(n)[dl < 0]
        return dl

    def cost(self, extra_pts=0.0):
        return (self.spread_pts + 2 * (SLIP_PTS + extra_pts) + self.comm) * self.point


# --------------------------------------------------------------------------------
# the bracket engine
# --------------------------------------------------------------------------------
def outcomes(b, sl_mult, tp_mult, maxbars, direction, rt=None, deadline=None,
             floor_spread=0.0, dist_override=None):
    """Resolve the hypothetical trade entered at EVERY bar for one bracket.

    Entry bar m means the signal fired at bar m-1's close and we fill at open[m]; the stop
    distance is sl_mult * ATR(14)[m-1], the ATR as known at the DECISION (never the entry
    bar's own, which would be look-ahead).

    `deadline[m]` (if given) is the last bar index the trade may be held to; whatever is
    still open there exits at that bar's CLOSE. `maxbars` still applies, whichever binds
    first. Passing deadline=None reproduces gold_lib.outcomes exactly.

    Returns (R, xi): net result in R and the exit bar index, nan / -1 where impossible.
    """
    n, o, h, l, c = b.n, b.o, b.h, b.l, b.c
    if rt is None:
        rt = b.rt
    # friction is charged at the SIGNAL bar's spread (the last one known when the trade
    # is decided) -- what every earlier pass in this project did.
    rt = np.concatenate(([rt[0]], rt[:-1]))
    dn = 1 if direction > 0 else -1

    m = np.arange(n)
    dist = np.full(n, np.nan)
    if dist_override is not None:
        # stop de STRUCTURE (ex: plus-bas des N dernieres barres). Comme pour l'ATR on
        # decale d'une barre: la distance est celle CONNUE A LA DECISION, jamais celle
        # de la barre d'entree (qui serait du look-ahead).
        dist[1:] = np.asarray(dist_override, float)[:-1]
    else:
        dist[1:] = sl_mult * b.atr[:-1]
    if floor_spread:
        f = np.full(n, np.nan)
        f[1:] = floor_spread * b.spread_px[:-1]
        dist = np.fmax(dist, f)
    entry = o.copy()
    ok = np.isfinite(dist) & (dist > 0) & (m > WARMUP)
    if deadline is not None:
        ok &= (deadline >= m)

    last = np.minimum(m + maxbars - 1, n - 1)
    if deadline is not None:
        last = np.minimum(last, deadline)

    sl = entry - dn * dist
    tp = entry + dn * tp_mult * dist if tp_mult is not None else None

    R = np.full(n, np.nan)
    xi = np.full(n, -1, dtype=np.int64)
    done = ~ok

    horizon = int(maxbars)
    for k in range(horizon):
        j = m + k
        live = (~done) & (j < n) & (j <= last)
        if not live.any():
            break
        jj = np.where(live, j, 0)
        hj, lj, oj = h[jj], l[jj], o[jj]
        if dn == 1:
            hit_sl = live & (lj <= sl)
            hit_tp = (live & (hj >= tp)) if tp is not None else np.zeros(n, bool)
            px_sl = np.minimum(sl, oj)
            px_tp = np.maximum(tp, oj) if tp is not None else None
        else:
            hit_sl = live & (hj >= sl)
            hit_tp = (live & (lj <= tp)) if tp is not None else np.zeros(n, bool)
            px_sl = np.maximum(sl, oj)
            px_tp = np.minimum(tp, oj) if tp is not None else None
        take_tp = hit_tp & ~hit_sl              # PESSIMISTIC: stop wins a spanning bar
        for take, px in ((hit_sl, px_sl), (take_tp, px_tp)):
            if px is None or not take.any():
                continue
            R[take] = (dn * (px[take] - entry[take]) - rt[take]) / dist[take]
            xi[take] = jj[take]
            done = done | take

    left = (~done) & ok
    if left.any():
        jl = np.where(left, last, 0)
        R[left] = (dn * (c[jl][left] - entry[left]) - rt[left]) / dist[left]
        xi[left] = jl[left]
    R[~ok] = np.nan
    xi[~ok] = -1
    return R, xi


class Table:
    """Long and short outcome tables for one bracket -- what a rule is scored against."""

    def __init__(self, b, sl_mult, tp_mult, maxbars, rt=None, session=True,
                 floor_spread=0.0, dist_override=None):
        self.b = b
        self.key = (sl_mult, tp_mult, maxbars, session, floor_spread,
                    None if dist_override is None else id(dist_override))
        dl = b.deadline if session else None
        self.RL, self.XL = outcomes(b, sl_mult, tp_mult, maxbars, +1, rt, dl, floor_spread,
                                    dist_override)
        self.RS, self.XS = outcomes(b, sl_mult, tp_mult, maxbars, -1, rt, dl, floor_spread,
                                    dist_override)

    def walk(self, sig):
        idx = np.flatnonzero(sig != 0)
        return self.walk_idx(idx, np.asarray(sig)[idx])

    def walk_idx(self, idx, sgn):
        """One position at a time. `idx` are SIGNAL bars (decision at their close), the
        fill is at idx+1's open; after a trade exits on bar x the strategy re-arms, so a
        signal on bar x is allowed. Advances by searchsorted -> one iteration per trade
        TAKEN, not per signal."""
        RL, XL, RS, XS = self.RL, self.XL, self.RS, self.XS
        n = self.b.n
        out_r, out_x, out_e = [], [], []
        p, npos = 0, len(idx)
        while p < npos:
            i = idx[p]
            m = i + 1
            if m >= n:
                break
            s = sgn[p]
            r = RL[m] if s > 0 else RS[m]
            if not np.isfinite(r):
                p += 1
                continue
            x = int(XL[m] if s > 0 else XS[m])
            out_r.append(float(r)); out_x.append(x); out_e.append(m)
            p = int(np.searchsorted(idx, x, side='left'))
        return (np.array(out_r), np.array(out_x, dtype=np.int64),
                np.array(out_e, dtype=np.int64))


def tstat(R):
    R = np.asarray(R, float)
    if len(R) < 2:
        return np.nan
    s = R.std(ddof=1)
    return R.mean() / s * np.sqrt(len(R)) if s > 0 else np.nan


def cell_stats(b, R, xi):
    if len(R) < 5:
        return None
    t_exit = pd.to_datetime(b.time[xi])
    span = max((t_exit.max() - t_exit.min()).days / 365.25, 1e-9)
    gl = -R[R <= 0].sum()
    cum = np.cumsum(R)
    mdd = float(np.max(np.maximum.accumulate(cum) - cum)) if len(cum) else np.nan
    ryr = float(R.sum() / span)
    return dict(n=len(R), win=float((R > 0).mean()), ER=float(R.mean()), Ryr=ryr,
                t=float(tstat(R)), PF=float(R[R > 0].sum() / gl) if gl > 0 else np.inf,
                maxDD=mdd, RoMaD=float(ryr / mdd) if mdd and mdd > 0 else np.nan,
                span=float(span))


def null_ts(table, pool, n_signals, long_frac, ndraw=400, rng=None, seed=0):
    """t-distribution of the SAME bracket entered at RANDOM bars drawn from `pool`.

    The project's standing rule: a long-biased ATR bracket earns a positive t with no
    signal at all (drift), so P(E[R]<=0) tests the wrong hypothesis. The matched null
    holds the bracket, the direction mix, the signal count, the eligible bars AND the
    one-position-at-a-time sequencing fixed, and randomises only WHICH bars fire.
    """
    rng = rng or np.random.default_rng(seed)
    k = min(int(n_signals), len(pool))
    if k < 5:
        return np.array([])
    ts = []
    for _ in range(ndraw):
        bars = np.sort(rng.choice(pool, k, replace=False))
        sgn = np.where(rng.random(k) < long_frac, 1, -1).astype(np.int8)
        R, _, _ = table.walk_idx(bars, sgn)
        if len(R) >= 5:
            ts.append(tstat(R))
    return np.array([x for x in ts if np.isfinite(x)])
