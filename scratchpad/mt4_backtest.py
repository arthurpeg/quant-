"""Faithful Python ports + Pepperstone backtests of the eligible MQL4 Code Base EAs.

Corpus  : strategies_mt4.zip = the MQL4 Code Base (1063 entries / 1256 .mq4).
Filter  : mt4_triage.py -> mt4_triage2.py (hard SL+TP in the OrderSend call, a real
          signal, pure OHLCV, no external data / ML / iCustom / lot progression).
Port    : each survivor transcribed to the letter -- same indicators (mt4_indicators.py
          reproduces MQL4's quirks), same shifts, same thresholds, same SL/TP, same
          session and one-position-at-a-time gating.

Execution model (same as the earlier EA sessions in this project):
  * MQL4 `shift k` -> array index i-k. The EA's decision on bar i is taken at that
    bar's close; the fill is the OPEN of bar i+1 (no intrabar look-ahead).
  * one position at a time per symbol; re-arm on the bar the position closes.
  * SL/TP resolved PESSIMISTICALLY: if a bar's range spans both, the stop is taken.
  * trailing stops are ratcheted at bar close (the EAs trail on tick -- a bar-level
    approximation, noted; it is the optimistic side for the trail and is why the
    non-trailing variants are the headline numbers).
  * cost = max(feed spread, live spread) + 2*slippage points, charged once per trade.
  * everything measured in R, where 1R = that EA's own initial stop distance.

`Point` convention: these EAs were written for 4-digit brokers, where 1 Point = 1 pip.
On the 5-digit Pepperstone feed the literal reading makes "StopLoss = 30" a 3-pip stop.
We therefore run BOTH:
    mode 'literal' -- SYMBOL_POINT as-is (what the code says)
    mode 'pip'     -- x10 on 3/5-digit symbols (what the author meant)
and report both, since the literal reading on FX mostly measures the spread.
"""
import os, sys, json, argparse
sys.path.insert(0, '.'); sys.path.insert(0, 'scratchpad')
import numpy as np
import pandas as pd
from brick_baseline import score, tstat
import mt4_indicators as I

BASE = r'C:\Users\arthu\AppData\Local\Temp\claude\C--Users-arthu-OneDrive-Documents-ML-quantitatif\f15a2d67-4d17-4075-b14b-316a2b53ff35\scratchpad'
PEP = os.path.join(BASE, 'pep_h1')
# 2026-08-09: BASE ci-dessus est le scratchpad d'une session purgee. Repli sur la
# reconstruction locale du repo (scratchpad/inx_data.py). Strictement additif: si
# l'ancien repertoire existe encore il gagne, donc les runs anterieurs reproduisent.
_SP = [os.path.join(BASE, 'specs.json'), os.path.join('scratchpad', '_inx', 'specs.json'),
       os.path.join(os.path.dirname(os.path.abspath(__file__)), '_inx', 'specs.json')]
SPECS = None
for _p in _SP:
    if os.path.exists(_p):
        SPECS = json.load(open(_p)); break
if SPECS is None:
    raise FileNotFoundError('no specs.json - run `python scratchpad/inx_data.py` first')
SLIP_PTS = 1.0
PESSIMISTIC = True      # a bar spanning both barriers is resolved as the stop

UNI = ['XAUUSD', 'XAGUSD', 'NAS100', 'US500', 'US30', 'US2000', 'GER40', 'FRA40', 'UK100',
       'BTCUSD', 'ETHUSD', 'EURUSD', 'GBPUSD', 'USDJPY', 'USDCHF', 'USDCAD', 'AUDUSD',
       'NZDUSD', 'EURJPY']

_cache = {}


def load(sym, tf):
    """Barres (sym, tf). Ordre des sources: l'ancien pull `PEP` s'il existe encore,
    sinon la reconstruction locale — intraday via inx_data (M5/M10/M15/M30, index en
    VRAI UTC), et H1/H4/D1 depuis data_cache_mt5 reinterprete de la meme facon.
    L'index DOIT etre en vrai UTC dans tous les cas: le transpileur aligne les
    timeframes entre eux, et melanger heure-serveur et UTC decalerait l'alignement
    d'une a trois heures sans rien casser visiblement."""
    k = (sym, tf)
    if k in _cache:
        return _cache[k]
    p = os.path.join(PEP, f'{sym}_{tf}.parquet')
    if os.path.exists(p):
        d = pd.read_parquet(p)
        d['time'] = pd.to_datetime(d['time'], utc=True)
        _cache[k] = d.set_index('time').sort_index()
        return _cache[k]
    import sys as _s
    _s.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import inx_data as _ix
    if tf in ('M5', 'M10', 'M15', 'M30'):
        d = _ix.bars(sym, tf)
        if d is None:
            return None
        _cache[k] = d.sort_index()
        return _cache[k]
    for ext, rd in (('parquet', pd.read_parquet), ('csv', pd.read_csv)):
        q = os.path.join('data_cache_mt5', f'{sym}_{tf}.{ext}')
        if os.path.exists(q):
            d = rd(q)
            d.columns = [c.lower() for c in d.columns]
            d['time'] = pd.to_datetime(d['time'], utc=True)
            ix = _ix.to_true_utc(pd.DatetimeIndex(d['time']))
            d = d.loc[ix.notna()].copy()
            d.index = ix[ix.notna()]
            _cache[k] = d.sort_index().drop(columns=['time'])
            return _cache[k]
    return None


def align(base_index, other):
    """Value of `other`'s LAST COMPLETED bar as of each base bar's close.

    `other` is indexed by bar START; a bar stamped t is only complete at t+dt, so we
    merge on t+dt (its close time) with direction='backward'. No look-ahead."""
    dt = other.index.to_series().diff().median()
    ot = other.copy()
    ot.index = ot.index + dt
    return ot.reindex(ot.index.union(base_index)).ffill().reindex(base_index)


class Ctx:
    """Per-(symbol,timeframe) context handed to each ported EA."""

    def __init__(self, sym, tf, mode):
        self.sym, self.tf, self.mode = sym, tf, mode
        sp = SPECS[sym]
        self.point = sp['point']
        self.digits = sp['digits']
        self.tick = sp['tick_size']
        # 'literal' = Point as the code writes it; 'pip' = the 4-digit-broker intent
        self.mul = 10.0 if (mode == 'pip' and sp['digits'] in (3, 5)) else 1.0
        self.P = self.point * self.mul          # one "EA point"
        self.d = load(sym, tf)
        # NOTE: MT5 hands back broker-server timestamps; pandas labels them UTC but they
        # are EET. That is exactly the clock MQL4's Hour()/DayOfWeek() read, so the
        # session gates below are applied on this index deliberately, not by accident.
        self.bar_minutes = ({'M5': 5, 'M15': 15, 'M30': 30, 'H1': 60, 'H4': 240,
                             'D1': 1440}).get(tf, 60)

    def other(self, tf):
        o = load(self.sym, tf)
        return None if o is None else align(self.d.index, o)


# =============================================================================
#  PORTED STRATEGIES
#  Each returns: sig[i] in {-1,0,+1} decided on bar i (fill = open of i+1),
#                sl_dist[i], tp_dist[i] in PRICE units (0/NaN = none),
#                manage: None | dict(trail=price, be=price)
#                exit_sig[i] (optional): close an open position at open i+1
#  entry='market' (default) or ('stop', price_long, price_short) for pending orders.
# =============================================================================

def s_cm_rsi(x):
    """16069 cm_RSI -- RSI(14, PRICE_OPEN) crossing the 30/70 levels.
       BUY when RSI[0]>30 and RSI[1]<30; SELL when RSI[0]<70 and RSI[1]>70.
       SL 100 Point, TP 200 Point."""
    d = x.d
    r = I.rsi(d['open'].to_numpy(), 14)
    n = len(d)
    sig = np.zeros(n)
    buy = np.zeros(n, bool); sell = np.zeros(n, bool)
    buy[1:] = (r[1:] > 30) & (r[:-1] < 30)
    sell[1:] = (r[1:] < 70) & (r[:-1] > 70)
    sig[buy] = 1; sig[sell & ~buy] = -1
    return sig, np.full(n, 100 * x.P), np.full(n, 200 * x.P), None, None


def s_ema_cross(x):
    """8606 EMA_CROSS -- EMA(5) x EMA(60) on close. SL 30, TP 20, trailing 50."""
    d = x.d
    c = d['close'].to_numpy()
    f = I.ma(c, 5, I.MODE_EMA); s = I.ma(c, 60, I.MODE_EMA)
    n = len(c)
    sig = np.zeros(n)
    sig[I.crossed_up(f, s)] = 1
    sig[I.crossed_dn(f, s)] = -1
    return (sig, np.full(n, 30 * x.P), np.full(n, 20 * x.P),
            dict(trail=50 * x.P, be=50 * x.P), None)


def s_bbands_break(x):
    """37577 _HPCS_Inter7 -- Bollinger(20,2) BREAKOUT.
       BUY when Close crosses above the UPPER band, SELL when it crosses below the
       LOWER band. SL = TP = 10 pips (the EA applies its own x10 for 3/5 digits)."""
    d = x.d
    c = d['close'].to_numpy()
    up, mid, lo = I.bands(c, 20, 2.0)
    n = len(c)
    sig = np.zeros(n)
    sig[I.crossed_up(c, up)] = 1
    sig[I.crossed_dn(c, lo)] = -1
    fac = 10.0 if SPECS[x.sym]['digits'] in (3, 5) else 1.0   # the EA's own li_Factor
    dist = 10 * x.point * fac
    return sig, np.full(n, dist), np.full(n, dist), None, None


def s_bigdog(x):
    """9259 FT_TIME_BIGDOG -- the 'Big Dog' session-range breakout.
       Range = high/low of the 14:00-16:00 (server) window. Once past 16:00, if the
       range is narrower than 50 Point, arm BOTH stop orders for the rest of the day:
         BuyStop  @ range high, SL = range low,  TP = high + 50 Point
         SellStop @ range low,  SL = range high, TP = low  - 50 Point
       (the EA also requires price to still be >20 Point away from the trigger)."""
    d = x.d
    o = d['open'].to_numpy(); h = d['high'].to_numpy()
    l = d['low'].to_numpy(); c = d['close'].to_numpy()
    n = len(d)
    hours = d.index.hour.to_numpy()
    days = d.index.normalize().to_numpy()
    hi = np.full(n, np.nan); lo = np.full(n, np.nan)
    # rolling per-day 14:00-16:00 extremes, only visible from 16:00 on
    cur_day = None; ch = -np.inf; cl = np.inf
    for i in range(n):
        if days[i] != cur_day:
            cur_day = days[i]; ch = -np.inf; cl = np.inf
        if 14 <= hours[i] < 16:
            ch = max(ch, h[i]); cl = min(cl, l[i])
        if hours[i] >= 16 and np.isfinite(ch) and ch > -np.inf:
            hi[i] = ch; lo[i] = cl
    rng = hi - lo
    ok = np.isfinite(rng) & (rng < 50 * x.P)
    sig = np.zeros(n)
    sl = np.full(n, np.nan); tp = np.full(n, np.nan)
    trig_l = np.full(n, np.nan); trig_s = np.full(n, np.nan)
    armed = ok & ((hi - c) > 20 * x.P) & ((c - lo) > 20 * x.P)
    sig[armed] = 2                      # 2 = "both stop orders armed"
    trig_l[armed] = hi[armed]; trig_s[armed] = lo[armed]
    sl[armed] = rng[armed]              # 1R = the range width
    tp[armed] = 50 * x.P
    return sig, sl, tp, None, dict(kind='straddle', up=trig_l, dn=trig_s)


def s_adx_expert(x):
    """20315 ADX Expert -- +DI[1] > -DI[2] and +DI[2] < -DI[2] and ADX[1] < 20 -> BUY
       (mirror for SELL). SL 200 Point, TP 400 Point. ADX(14, PRICE_CLOSE)."""
    d = x.d
    m, p, mi = I.adx(d['high'].to_numpy(), d['low'].to_numpy(), d['close'].to_numpy(), 14)
    n = len(d)
    sig = np.zeros(n)
    a1 = np.roll(m, 1); p1 = np.roll(p, 1)
    p2 = np.roll(p, 2); mi2 = np.roll(mi, 2)
    a1[:1] = np.nan; p1[:1] = np.nan; p2[:2] = np.nan; mi2[:2] = np.nan
    buy = (p1 > mi2) & (p2 < mi2) & (a1 < 20)
    sell = (p1 < mi2) & (p2 > mi2) & (a1 < 20)
    sig[np.nan_to_num(buy)] = 1
    sig[np.nan_to_num(sell) & ~np.nan_to_num(buy)] = -1
    return sig, np.full(n, 200 * x.P), np.full(n, 400 * x.P), None, None


def s_cci_expert(x):
    """29318 CCI-expert -- CCI(14) with [0]>1, [1]>1, [2]<1 -> BUY (mirror SELL).
       SL 600 Point, TP 150 Point. Also closes early on the opposite signal, but only
       when the position is in profit -- ported as a profitable-only signal exit."""
    d = x.d
    v = I.cci(d['high'].to_numpy(), d['low'].to_numpy(), d['close'].to_numpy(), 14)
    n = len(d)
    v1 = np.roll(v, 1); v2 = np.roll(v, 2)
    v1[:1] = np.nan; v2[:2] = np.nan
    buy = (v > 1) & (v1 > 1) & (v2 < 1)
    sell = (v < 1) & (v1 < 1) & (v2 > 1)
    sig = np.zeros(n)
    sig[np.nan_to_num(buy)] = 1
    sig[np.nan_to_num(sell) & ~np.nan_to_num(buy)] = -1
    ex = np.zeros(n)
    ex[np.nan_to_num(sell)] = 1        # exit longs
    ex[np.nan_to_num(buy)] = -1        # exit shorts
    return (sig, np.full(n, 600 * x.P), np.full(n, 150 * x.P), None,
            dict(kind='exit_if_profit', arr=ex))


def s_macd_mtf(x):
    """20246 MACD Expert -- MACD(12,26,9) SIGNAL above MAIN on M5 *and* M15 *and* H1
       *and* H4 simultaneously -> BUY (mirror SELL). SL 200 Point, TP 400 Point.
       Runs on its finest timeframe (M5); coarser TFs aligned without look-ahead."""
    d = x.d
    n = len(d)
    conds_up = []; conds_dn = []
    for tf in ('M5', 'M15', 'H1', 'H4'):
        if tf == x.tf:
            c = d['close'].to_numpy()
        else:
            o = x.other(tf) if tf != 'H4' else None
            if tf == 'H4':
                h1 = x.other('H1')
                if h1 is None:
                    return np.zeros(n), np.zeros(n), np.zeros(n), None, None
                o = h1.resample('4h').agg({'close': 'last'}).dropna()
                o = align(d.index, o)
            if o is None:
                return np.zeros(n), np.zeros(n), np.zeros(n), None, None
            c = o['close'].to_numpy()
        m, s = I.macd(c, 12, 26, 9)
        m1 = np.roll(m, 1); s1 = np.roll(s, 1)      # the EA reads shift 1
        m1[:1] = np.nan; s1[:1] = np.nan
        conds_up.append(s1 > m1)
        conds_dn.append(s1 < m1)
    buy = np.logical_and.reduce(conds_up)
    sell = np.logical_and.reduce(conds_dn)
    sig = np.zeros(n)
    sig[buy] = 1
    sig[sell & ~buy] = -1
    return sig, np.full(n, 200 * x.P), np.full(n, 400 * x.P), None, None


def s_macd_cross_d1(x):
    """10713 MACDcrossAUDD1 -- MACD(12,26,9) main crossing its signal between shift 2
       and shift 1. SL 40 pips (hard-coded 0.0001), TP = 3 x SL. Hour gate 6..14.
       The EA hard-codes AUDUSD/D1; we run the RULE on the whole universe."""
    d = x.d
    m, s = I.macd(d['close'].to_numpy(), 12, 26, 9)
    n = len(d)
    m1 = np.roll(m, 1); s1 = np.roll(s, 1); m2 = np.roll(m, 2); s2 = np.roll(s, 2)
    for a, k in ((m1, 1), (s1, 1), (m2, 2), (s2, 2)):
        a[:k] = np.nan
    # MQL4's Hour() is the CURRENT SERVER TIME, not the bar's hour. On an intraday
    # chart the two coincide; on the D1 chart this EA is written for, the gate is a
    # wall-clock window that any given day satisfies, so it does not filter bars.
    if x.bar_minutes < 1440:
        hours = d.index.hour.to_numpy()
        gate = (hours > 5) & (hours < 15)
    else:
        gate = np.ones(n, bool)
    buy = (m2 < s2) & (m1 > s1) & gate
    sell = (m2 > s2) & (m1 < s1) & gate
    sig = np.zeros(n)
    sig[np.nan_to_num(buy)] = 1
    sig[np.nan_to_num(sell) & ~np.nan_to_num(buy)] = -1
    # the EA writes 40*0.0001 literally, i.e. 40 pips on a 4-digit FX quote
    dist = 40 * (0.0001 if SPECS[x.sym]['digits'] in (4, 5) else 10 * x.point)
    return sig, np.full(n, dist), np.full(n, 3 * dist), None, None


def s_mare(x):
    """9643 MARE5.1 -- SMA(13) vs SMA(55), ma_shift 2, on M1 in the original.
       SELL when Slow[0]-Fast[0] >= 1 Point, Fast[2]-Slow[2] >= 1 Point,
       Fast[5]-Slow[5] >= 1 Point and the last candle was down (Close[1]<Open[1]);
       BUY is the mirror. Hours 8..14. SL 80 Point, TP 110 Point."""
    d = x.d
    c = d['close'].to_numpy(); o = d['open'].to_numpy()
    f = I.ma(c, 13, I.MODE_SMA, shift=2)
    s = I.ma(c, 55, I.MODE_SMA, shift=2)
    n = len(c)

    def sh(a, k):
        r = np.roll(a, k); r[:k] = np.nan; return r
    f2, s2, f5, s5 = sh(f, 2), sh(s, 2), sh(f, 5), sh(s, 5)
    o1, c1 = sh(o, 1), sh(c, 1)
    hours = d.index.hour.to_numpy()
    gate = (hours >= 8) & (hours <= 14)
    pt = x.P
    sell = (s - f >= pt) & (f2 - s2 >= pt) & (f5 - s5 >= pt) & (c1 < o1) & gate
    buy = (f - s >= pt) & (s2 - f2 >= pt) & (s5 - f5 >= pt) & (c1 > o1) & gate
    sig = np.zeros(n)
    sig[np.nan_to_num(sell)] = -1
    sig[np.nan_to_num(buy)] = 1
    return sig, np.full(n, 80 * x.P), np.full(n, 110 * x.P), None, None


def s_mamacd(x):
    """8356 MAMACD -- LWMA(85) and LWMA(75) on PRICE_LOW vs EMA(5) on close, armed by
       a prior cross ('startb'/'starts' latch), confirmed by MACD(26,26,1) > 0 or
       rising. SL 15 Point, TP 15 Point."""
    d = x.d
    c = d['close'].to_numpy(); l = d['low'].to_numpy()
    n = len(c)
    w1 = I.ma(l, 85, I.MODE_LWMA); w2 = I.ma(l, 75, I.MODE_LWMA)
    e1 = I.ma(c, 5, I.MODE_EMA)
    mcur, _ = I.macd(c, 26, 26, 1)
    mlast, _ = I.macd(c, 26, 15, 1)

    def sh(a, k):
        r = np.roll(a, k); r[:k] = np.nan; return r
    w1, w2, e1 = sh(w1, 1), sh(w2, 1), sh(e1, 1)
    mc, ml = sh(mcur, 1), sh(mlast, 2)
    sig = np.zeros(n)
    startb = starts = 0
    for i in range(90, n):
        if not (np.isfinite(w1[i]) and np.isfinite(e1[i]) and np.isfinite(mc[i])):
            continue
        if e1[i] < w1[i] and e1[i] < w2[i]:
            startb = 1
        if e1[i] > w1[i] and e1[i] > w2[i]:
            starts = 1
        if e1[i] > w1[i] and e1[i] > w2[i] and startb == 1 and (mc[i] > 0 or mc[i] > ml[i]):
            sig[i] = 1; startb = 0
        elif e1[i] < w1[i] and e1[i] < w2[i] and starts == 1 and (mc[i] < 0 or mc[i] < ml[i]):
            sig[i] = -1; starts = 0
    return sig, np.full(n, 15 * x.P), np.full(n, 15 * x.P), None, None


def s_sourcecode2(x):
    """10294 SourceCode2 -- M15 in the original. EMA(3) vs EMA(34) on PRICE_MEDIAN,
       PSAR(0.02,0.2) on the far side of the current bar, and Bears/BullsPower(13)
       turning. SELL: SL 400 Point / TP 2000 Point;  BUY: SL 2000 / TP 400
       (the asymmetry is in the original -- ported as written)."""
    d = x.d
    o = d['open'].to_numpy(); h = d['high'].to_numpy()
    l = d['low'].to_numpy(); c = d['close'].to_numpy()
    med = (h + l) / 2.0
    n = len(c)
    f = I.ma(med, 3, I.MODE_EMA); s = I.ma(med, 34, I.MODE_EMA)
    ps = I.sar(h, l, 0.02, 0.2)
    bear = I.bears_power(h, l, c, 13); bull = I.bulls_power(h, l, c, 13)
    b1 = np.roll(bear, 1); b1[:1] = np.nan
    u1 = np.roll(bull, 1); u1[:1] = np.nan
    hours = d.index.hour.to_numpy()
    gate = (hours > 8) & (hours < 17)
    sell = (f < s) & (ps > h) & (bear < 0) & (bear > b1) & gate
    buy = (f > s) & (ps < l) & (bull > 0) & (bull < u1) & gate
    sig = np.zeros(n); sl = np.zeros(n); tp = np.zeros(n)
    sell = np.nan_to_num(sell); buy = np.nan_to_num(buy)
    sig[sell] = -1; sl[sell] = 400 * x.P; tp[sell] = 2000 * x.P
    b = buy & ~sell
    sig[b] = 1; sl[b] = 2000 * x.P; tp[b] = 400 * x.P
    return sig, sl, tp, None, None


def s_trend_catcher(x):
    """13661 Trend_Catcher -- price crossing the PSAR(0.004,0.2) with SMA(50)>SMA(200)
       and price beyond SMA(25).  SL = |price - SAR| clamped to [10,200] Point,
       TP = SL (TP_koef 1) -> a 1:1 bracket on a volatility-scaled stop."""
    d = x.d
    c = d['close'].to_numpy(); h = d['high'].to_numpy(); l = d['low'].to_numpy()
    n = len(c)
    ps = I.sar(h, l, 0.004, 0.2)
    ma200 = I.ma(c, 200, I.MODE_SMA); ma50 = I.ma(c, 50, I.MODE_SMA)
    ma25 = I.ma(c, 25, I.MODE_SMA)
    c1 = np.roll(c, 1); c1[:1] = np.nan
    p1 = np.roll(ps, 1); p1[:1] = np.nan
    buy = (c > ps) & (c1 < p1) & (ma50 > ma200) & (c > ma25)
    sell = (c < ps) & (c1 > p1) & (ma50 < ma200) & (c < ma25)
    sl = np.abs(ps - c)
    sl = np.clip(sl, 10 * x.P, 200 * x.P)
    sig = np.zeros(n)
    sig[np.nan_to_num(buy)] = 1
    sig[np.nan_to_num(sell) & ~np.nan_to_num(buy)] = -1
    return sig, sl, sl.copy(), None, None


def s_envelopes_fade(x):
    """30561 5Mins Envelopes -- LWMA(3) envelope on PRICE_MEDIAN, deviation 0.05%.
       When the last bar's LOW *and* the current price are more than 140 Point BELOW
       the lower band -> BUY (a fade, per the EA's own direct<0 -> OP_BUY branch);
       mirror above the upper band -> SELL.  StopLoss 250 Point, no TP,
       trailing stop 120 Point."""
    d = x.d
    h = d['high'].to_numpy(); l = d['low'].to_numpy(); c = d['close'].to_numpy()
    med = (h + l) / 2.0
    n = len(c)
    up, lo = I.envelopes(med, 3, I.MODE_LWMA, 0.05)

    def sh(a, k):
        r = np.roll(a, k); r[:k] = np.nan; return r
    up1, lo1, l1, h1 = sh(up, 1), sh(lo, 1), sh(l, 1), sh(h, 1)
    dist = 140 * x.P
    buy = (lo1 - l1 > dist) & (lo1 - c > dist)
    sell = (h1 - up1 > dist) & (c - up1 > dist)
    sig = np.zeros(n)
    sig[np.nan_to_num(buy)] = 1
    sig[np.nan_to_num(sell) & ~np.nan_to_num(buy)] = -1
    return (sig, np.full(n, 250 * x.P), np.full(n, np.nan),
            dict(trail=120 * x.P, be=120 * x.P), None)


def s_forex_profit(x):
    """8117 Forex Profit System -- EMA(10)/EMA(25)/EMA(50) on PRICE_MEDIAN plus PSAR.
       BUY: EMA10>EMA25, EMA10>EMA50, EMA10[2]<=EMA50 and SAR[1] < Close[1].
       SL 30 Point, TP 50 Point, trailing 10 Point."""
    d = x.d
    h = d['high'].to_numpy(); l = d['low'].to_numpy(); c = d['close'].to_numpy()
    med = (h + l) / 2.0
    n = len(c)
    e10 = I.ma(med, 10, I.MODE_EMA); e25 = I.ma(med, 25, I.MODE_EMA)
    e50 = I.ma(med, 50, I.MODE_EMA)
    ps = I.sar(h, l, 0.02, 0.2)

    def sh(a, k):
        r = np.roll(a, k); r[:k] = np.nan; return r
    a10, a25, a50 = sh(e10, 1), sh(e25, 1), sh(e50, 1)
    p10 = sh(e10, 2); s1 = sh(ps, 1); c1 = sh(c, 1)
    buy = (a10 > a25) & (a10 > a50) & (p10 <= a50) & (s1 < c1)
    sell = (a10 < a25) & (a10 < a50) & (p10 >= a50) & (s1 > c1)
    sig = np.zeros(n)
    sig[np.nan_to_num(buy)] = 1
    sig[np.nan_to_num(sell) & ~np.nan_to_num(buy)] = -1
    return (sig, np.full(n, 30 * x.P), np.full(n, 50 * x.P),
            dict(trail=10 * x.P, be=10 * x.P), None)


def s_sidus(x):
    """8324 Sidus_v1 -- EMA(23)-EMA(62) spread vs a threshold, filtered by RSI(67).
       BUY when spread < 63 Point and RSI(67) < 59 ; SELL when spread > -57 Point and
       RSI(97) > 60. BUY: SL 100 / TP 95 Point.  SELL: SL 69 / TP 17 Point.
       (thresholds are compared to a raw price spread in the original -- kept literal,
       scaled by Point so the comparison is dimensionally what the author meant)."""
    d = x.d
    c = d['close'].to_numpy()
    n = len(c)
    f = I.ma(c, 23, I.MODE_EMA); s = I.ma(c, 62, I.MODE_EMA)
    f2 = I.ma(c, 18, I.MODE_EMA); s2 = I.ma(c, 54, I.MODE_EMA)
    r1 = I.rsi(c, 67); r2 = I.rsi(c, 97)

    def sh(a, k):
        r = np.roll(a, k); r[:k] = np.nan; return r
    f, s, f2, s2, r1, r2 = (sh(v, 1) for v in (f, s, f2, s2, r1, r2))
    spread = (f - s) / x.P
    buy = (spread < 63) & (r1 < 59)
    sell = (spread > -57) & (r2 > 60)
    sig = np.zeros(n); sl = np.zeros(n); tp = np.zeros(n)
    buy = np.nan_to_num(buy); sell = np.nan_to_num(sell)
    sig[buy] = 1; sl[buy] = 100 * x.P; tp[buy] = 95 * x.P
    sset = sell & ~buy
    sig[sset] = -1; sl[sset] = 69 * x.P; tp[sset] = 17 * x.P
    return sig, sl, tp, None, None


def s_sto_mtf(x):
    """9017 STO_m5xm15xm30 -- Stochastic(5,3,3) crossing on M5 (shift 0 vs shift 3)
       aligned with the M15 and M30 stochastics. SL 10 Point, TP 30 Point."""
    d = x.d
    n = len(d)

    def stoch_of(frame):
        return I.stochastic(frame['high'].to_numpy(), frame['low'].to_numpy(),
                            frame['close'].to_numpy(), 5, 3, 3, I.MODE_SMA, 1)
    k0, dd0 = stoch_of(d)
    o15 = x.other('M15'); o30 = x.other('M30')
    if o15 is None or o30 is None:
        return np.zeros(n), np.zeros(n), np.zeros(n), None, None
    k15, d15 = stoch_of(o15)
    k30, d30 = stoch_of(o30)

    def sh(a, k):
        r = np.roll(a, k); r[:k] = np.nan; return r
    k3, d3 = sh(k0, 3), sh(dd0, 3)
    buy = (k0 > dd0) & (k3 < d3) & (k15 > d15) & (k30 > d30)
    sell = (k0 < dd0) & (k3 > d3) & (k15 < d15) & (k30 < d30)
    sig = np.zeros(n)
    sig[np.nan_to_num(buy)] = 1
    sig[np.nan_to_num(sell) & ~np.nan_to_num(buy)] = -1
    return sig, np.full(n, 10 * x.P), np.full(n, 30 * x.P), None, None


def s_adx_system(x):
    """8830 ADX_System -- ADX(14) rising (ADX[2]<ADX[1]) with +DI crossing above the
       ADX line -> BUY; -DI crossing above ADX -> SELL. SL 30 Point, TP 100 Point."""
    d = x.d
    m, p, mi = I.adx(d['high'].to_numpy(), d['low'].to_numpy(), d['close'].to_numpy(), 14)
    n = len(d)

    def sh(a, k):
        r = np.roll(a, k); r[:k] = np.nan; return r
    a2, a1 = sh(m, 2), sh(m, 1)
    p2, p1 = sh(p, 2), sh(p, 1)
    m2, m1 = sh(mi, 2), sh(mi, 1)
    buy = (a2 < a1) & (p2 < a2) & (p1 > a1)
    sell = (a2 < a1) & (m2 < a2) & (m1 > a1)
    sig = np.zeros(n)
    sig[np.nan_to_num(buy)] = 1
    sig[np.nan_to_num(sell) & ~np.nan_to_num(buy)] = -1
    return sig, np.full(n, 30 * x.P), np.full(n, 100 * x.P), None, None


def s_adx_2ma(x):
    """9825 Robot_ADX+2MA -- EMA(5)/EMA(12) separated by more than n=10 Point, with
       ADX(6) +DI/-DI crossing. SL 2400 Point, TP 4700 Point."""
    d = x.d
    c = d['close'].to_numpy()
    n = len(c)
    x1 = I.ma(c, 5, I.MODE_EMA); x2 = I.ma(c, 12, I.MODE_EMA)
    _, p, mi = I.adx(d['high'].to_numpy(), d['low'].to_numpy(), c, 6)

    def sh(a, k):
        r = np.roll(a, k); r[:k] = np.nan; return r
    f1, s1 = sh(x1, 1), sh(x2, 1)
    sep = np.abs(f1 - s1) / x.P
    p0, m0 = p, mi
    p1, m1 = sh(p, 1), sh(mi, 1)
    buy = (sep > 10) & (f1 > s1) & (p1 < m1) & (p0 > m0)
    sell = (sep > 10) & (f1 < s1) & (p1 > m1) & (p0 < m0)
    sig = np.zeros(n)
    sig[np.nan_to_num(buy)] = 1
    sig[np.nan_to_num(sell) & ~np.nan_to_num(buy)] = -1
    return sig, np.full(n, 2400 * x.P), np.full(n, 4700 * x.P), None, None


def s_adx_ma(x):
    """8088 ADX_MA -- Close[1] crossing the SMMA(21) on PRICE_MEDIAN with
       ADX(14, PRICE_MEDIAN) > 16.  Asymmetric brackets, as written:
         BUY  : SL 30 Point,  TP 1300 Point, trail 270
         SELL : SL 50 Point,  TP  160 Point, trail 20"""
    d = x.d
    h = d['high'].to_numpy(); l = d['low'].to_numpy(); c = d['close'].to_numpy()
    med = (h + l) / 2.0
    n = len(c)
    m = I.ma(med, 21, I.MODE_SMMA)
    a, _, _ = I.adx(h, l, med, 14)

    def sh(v, k):
        r = np.roll(v, k); r[:k] = np.nan; return r
    m1, a1 = sh(m, 1), sh(a, 1)
    c1, c2 = sh(c, 1), sh(c, 2)
    buy = (c1 > m1) & (c2 < m1) & (a1 > 16)
    sell = (c1 < m1) & (c2 > m1) & (a1 > 16)
    buy = np.nan_to_num(buy); sell = np.nan_to_num(sell)
    sig = np.zeros(n); sl = np.zeros(n); tp = np.zeros(n)
    sig[buy] = 1; sl[buy] = 30 * x.P; tp[buy] = 1300 * x.P
    ss = sell & ~buy
    sig[ss] = -1; sl[ss] = 50 * x.P; tp[ss] = 160 * x.P
    # a single trail parameter for the engine; the EA's two values differ per side,
    # 270/20 -- we use the long one (270) since longs dominate the bracket asymmetry
    return sig, sl, tp, dict(trail=270 * x.P, be=270 * x.P), None


def s_autotrade_bb(x):
    """14209 Auto Trade with BB -- an over-extension FADE inside a session window.
       SELL when Close[1] is above the Bollinger(50, 4.0) upper band with RSI(6)[1]>75
       and Stochastic(14,3,3)[1] > 85;  BUY on the mirror (below the lower band,
       RSI<25).  Hours strictly between 12 and 19.  SL 1000 Point, no TP,
       trailing 20 Point.
       NOTE: the original passes MODE_HIGH/MODE_LOW to iBands (not valid band modes);
       we port the evident intent -- upper band for the sell, lower for the buy."""
    d = x.d
    h = d['high'].to_numpy(); l = d['low'].to_numpy(); c = d['close'].to_numpy()
    n = len(c)
    up, mid, lo = I.bands(c, 50, 4.0)
    r = I.rsi(c, 6)
    k, _ = I.stochastic(h, l, c, 14, 3, 3, I.MODE_SMA, 1)

    def sh(v, kk):
        rr = np.roll(v, kk); rr[:kk] = np.nan; return rr
    up1, lo1, c1, r1, k1 = sh(up, 1), sh(lo, 1), sh(c, 1), sh(r, 1), sh(k, 1)
    hours = d.index.hour.to_numpy()
    gate = (hours > 12) & (hours < 19)
    sell = (c1 > up1) & (r1 > 75) & (k1 > 85) & gate
    buy = (c1 < lo1) & (r1 < 25) & gate
    sig = np.zeros(n)
    sig[np.nan_to_num(buy)] = 1
    sig[np.nan_to_num(sell) & ~np.nan_to_num(buy)] = -1
    return (sig, np.full(n, 1000 * x.P), np.full(n, np.nan),
            dict(trail=20 * x.P, be=20 * x.P), None)


def s_ozfx(x):
    """7994 OzFx -- Accelerator Oscillator crossing zero with the Stochastic on side.
       BUY when Stoch(5,3,3)[1] > 50, AC[1] > AC[2], AC[1] > 0 and AC[2] < 0.
       The EA fires a 5-order basket: TPs at 50/100/150/200 Point plus one runner
       with no TP, all sharing SL 100 Point. Ported as the mean R of those 5 legs."""
    d = x.d
    h = d['high'].to_numpy(); l = d['low'].to_numpy(); c = d['close'].to_numpy()
    n = len(c)
    a = I.ac(h, l)
    k, _ = I.stochastic(h, l, c, 5, 3, 3, I.MODE_SMA, 0)

    def sh(v, kk):
        rr = np.roll(v, kk); rr[:kk] = np.nan; return rr
    a1, a2, k1 = sh(a, 1), sh(a, 2), sh(k, 1)
    buy = (k1 > 50) & (a1 > a2) & (a1 > 0) & (a2 < 0)
    sell = (k1 < 50) & (a1 < a2) & (a1 < 0) & (a2 > 0)
    sig = np.zeros(n)
    sig[np.nan_to_num(buy)] = 1
    sig[np.nan_to_num(sell) & ~np.nan_to_num(buy)] = -1
    return (sig, np.full(n, 100 * x.P), np.full(n, 50 * x.P), None,
            dict(kind='basket', tps=[50, 100, 150, 200, None], unit=x.P))


# name -> (fn, timeframes to run on, one-line description)
STRATS = {
    'cm_RSI':          (s_cm_rsi,        ['H1', 'D1'], 'RSI(14) 30/70 cross, SL100/TP200'),
    'EMA_CROSS':       (s_ema_cross,     ['H1', 'D1'], 'EMA5xEMA60, SL30/TP20 +trail50'),
    'BBands_Breakout': (s_bbands_break,  ['H1', 'D1'], 'BB(20,2) breakout, SL=TP=10pip'),
    'BigDog_Range':    (s_bigdog,        ['H1', 'M30'], '14-16h range straddle, TP50'),
    'ADX_Expert':      (s_adx_expert,    ['H1', 'D1'], 'DI cross + ADX<20, SL200/TP400'),
    'CCI_Expert':      (s_cci_expert,    ['H1', 'D1'], 'CCI(14) 0-cross, SL600/TP150'),
    'MACD_MTF':        (s_macd_mtf,      ['M5'],       'MACD aligned M5/M15/H1/H4'),
    'MACD_Cross':      (s_macd_cross_d1, ['D1', 'H1'], 'MACD cross, SL40pip TP120pip'),
    'MARE5':           (s_mare,          ['M5', 'M30'], 'SMA13/55 shift2 + candle, 8-14h'),
    'MAMACD':          (s_mamacd,        ['H1', 'D1'], 'LWMA85/75(low) vs EMA5 + MACD'),
    'SourceCode2':     (s_sourcecode2,   ['M15', 'H1'], 'EMA3/34 + PSAR + Bulls/Bears'),
    'Trend_Catcher':   (s_trend_catcher, ['H1', 'D1'], 'PSAR flip + MA50/200, 1:1 R'),
    'Envelopes_Fade':  (s_envelopes_fade, ['M5', 'M30'], 'LWMA3 envelope fade, trail120'),
    'ForexProfitSys':  (s_forex_profit,  ['H1', 'D1'], 'EMA10/25/50 + PSAR, SL30/TP50'),
    'Sidus_v1':        (s_sidus,         ['H1', 'D1'], 'EMA23/62 spread + RSI67'),
    'STO_MTF':         (s_sto_mtf,       ['M5'],       'Stoch cross M5+M15+M30'),
    'ADX_System':      (s_adx_system,    ['H1', 'D1'], '+DI x ADX rising, SL30/TP100'),
    'ADX_2MA':         (s_adx_2ma,       ['H1', 'D1'], 'EMA5/12 + ADX(6) DI cross'),
    'ADX_MA':          (s_adx_ma,        ['H1', 'D1'], 'SMMA21 cross + ADX>16, asym TP'),
    'AutoTrade_BB':    (s_autotrade_bb,  ['H1', 'M30'], 'BB(50,4) fade + RSI6 + Stoch'),
    'OzFx':            (s_ozfx,          ['H1', 'D1'], 'AC zero-cross + Stoch, TP basket'),
}


# =============================================================================
#  EXECUTION
# =============================================================================

def simulate(x, gen):
    """One-position-at-a-time bar simulation. Returns a DataFrame of trades in R."""
    d = x.d
    if d is None or len(d) < 300:
        return pd.DataFrame(columns=['exit_time', 'R', 'dir']), np.nan
    o = d['open'].to_numpy(); h = d['high'].to_numpy()
    l = d['low'].to_numpy(); c = d['close'].to_numpy()
    spr = d['spread'].to_numpy() if 'spread' in d else np.zeros(len(d))
    pt = x.point
    floor = SPECS[x.sym]['spread_now']
    rt = (np.maximum(spr, floor) + 2 * SLIP_PTS) * pt
    tms = d.index.to_numpy()

    sig, sld, tpd, manage, extra = gen(x)
    n = len(d)

    # --- applicability gate -------------------------------------------------
    # These EAs hard-code their stop in broker "points". A stop of 100 points is
    # 10 pips on EURUSD but $1 on BTCUSD -- far inside one bar's range and smaller
    # than the spread. Such an (EA, asset) pair is not a strategy that lost, it is a
    # strategy that CANNOT BE RUN there, and folding it into a pooled t would be
    # meaningless. Pre-declared bound: the stop must be between 0.2x and 50x ATR(14).
    a14 = I.atr(h, l, c, 14)
    med_sl = np.nanmedian(np.where(sig != 0, sld, np.nan))
    med_atr = np.nanmedian(a14)
    ratio = med_sl / med_atr if (np.isfinite(med_sl) and np.isfinite(med_atr) and med_atr > 0) else np.nan
    if not np.isfinite(ratio) or ratio < 0.2 or ratio > 50:
        return pd.DataFrame(columns=['exit_time', 'R', 'dir']), ratio
    exit_arr = extra['arr'] if (extra and extra.get('kind') == 'exit_if_profit') else None
    # unconditional signal exit (Pine's strategy.close on an opposite cross)
    exit_any = extra['arr'] if (extra and extra.get('kind') == 'exit_signal') else None
    straddle = extra if (extra and extra.get('kind') == 'straddle') else None
    basket = extra if (extra and extra.get('kind') == 'basket') else None
    # one-sided pending stop order (Pine's strategy.entry(..., stop=level)), re-placed
    # each bar and live until it fills or the signal flips
    pending = extra if (extra and extra.get('kind') == 'stop_entry') else None

    trades = []
    i = 250
    while i < n - 1:
        s = sig[i]
        if s == 0 or not np.isfinite(sld[i]) or sld[i] <= 0:
            i += 1
            continue

        # ---- determine entry ----
        if straddle is not None and s == 2:
            # both stop orders live from bar i+1 until the day ends or one fills
            up = straddle['up'][i]; dn = straddle['dn'][i]
            j = i + 1
            day = pd.Timestamp(tms[i]).normalize()
            dirn = 0
            while j < n and pd.Timestamp(tms[j]).normalize() == day:
                hit_l = h[j] >= up
                hit_s = l[j] <= dn
                if hit_l and hit_s:
                    dirn = 1 if o[j] <= up else -1     # pessimistic-ish: nearer side first
                    entry = up if dirn == 1 else dn
                    break
                if hit_l:
                    dirn, entry = 1, max(up, o[j]); break
                if hit_s:
                    dirn, entry = -1, min(dn, o[j]); break
                j += 1
            if dirn == 0:
                i += 1
                continue
            R1 = sld[i]
            sl = dn if dirn == 1 else up
            tp = entry + dirn * tpd[i]
            start = j
        elif pending is not None:
            # order rests at level[i]; fills on the first later bar that trades through
            # it, and is cancelled the moment the signal changes side.
            dirn = int(s)
            lvl = pending['level'][i]
            if not np.isfinite(lvl):
                i += 1
                continue
            j = i + 1
            filled = False
            while j < n and sig[j - 1] == s:
                if (dirn == 1 and h[j] >= lvl) or (dirn == -1 and l[j] <= lvl):
                    filled = True
                    break
                j += 1
            if not filled:
                i += 1
                continue
            entry = max(lvl, o[j]) if dirn == 1 else min(lvl, o[j])
            R1 = sld[i]
            sl = entry - dirn * sld[i]
            tp = (entry + dirn * tpd[i]) if np.isfinite(tpd[i]) else None
            start = j
        else:
            dirn = int(s)
            entry = o[i + 1]
            R1 = sld[i]
            sl = entry - dirn * sld[i]
            tp = (entry + dirn * tpd[i]) if np.isfinite(tpd[i]) else None
            start = i + 1

        # ---- basket of N legs sharing one stop, each with its own TP ----
        if basket is not None:
            legs = []
            for mult in basket['tps']:
                lt = (entry + dirn * mult * basket['unit']) if mult else None
                legs.append([lt, None])          # [tp price, realised px]
            j = start
            while j < n and any(lg[1] is None for lg in legs):
                hit_sl = (l[j] <= sl) if dirn == 1 else (h[j] >= sl)
                for lg in legs:
                    if lg[1] is not None:
                        continue
                    if hit_sl:
                        lg[1] = min(sl, o[j]) if dirn == 1 else max(sl, o[j])
                        continue
                    if lg[0] is not None:
                        hit_tp = (h[j] >= lg[0]) if dirn == 1 else (l[j] <= lg[0])
                        if hit_tp:
                            lg[1] = max(lg[0], o[j]) if dirn == 1 else min(lg[0], o[j])
                j += 1
            for lg in legs:
                if lg[1] is None:
                    lg[1] = c[n - 1]
            j = min(j, n - 1)
            nets = [dirn * (lg[1] - entry) - rt[i] for lg in legs]
            trades.append((tms[j], float(np.mean(nets)) / R1, dirn))
            i = max(j, i + 1)
            continue

        peak = entry
        exit_px = None
        j = start
        while j < n:
            # PESSIMISTIC (default): when a bar spans both barriers the stop is taken.
            # PESSIMISTIC=False flips the tie to the take-profit, so the gap between the
            # two bounds the whole ambiguity of a bar-resolution backtest.
            if dirn == 1:
                hit_sl, hit_tp = l[j] <= sl, (tp is not None and h[j] >= tp)
                if hit_sl and (PESSIMISTIC or not hit_tp):
                    exit_px = min(sl, o[j]); break
                if hit_tp:
                    exit_px = max(tp, o[j]); break
            else:
                hit_sl, hit_tp = h[j] >= sl, (tp is not None and l[j] <= tp)
                if hit_sl and (PESSIMISTIC or not hit_tp):
                    exit_px = max(sl, o[j]); break
                if hit_tp:
                    exit_px = min(tp, o[j]); break
            # unconditional signal exit: decided at bar j's close, filled at j+1's open
            if exit_any is not None and j > start and exit_any[j] == dirn and j + 1 < n:
                exit_px = o[j + 1]; j += 1; break
            # signal-based exit, only when in profit (CCI_Expert)
            if exit_arr is not None and j > start and exit_arr[j] == dirn:
                if dirn * (c[j] - entry) > 0 and j + 1 < n:
                    exit_px = o[j + 1]; j += 1; break
            # trailing stop, ratcheted at bar close
            if manage:
                if dirn == 1:
                    peak = max(peak, h[j])
                    if peak - entry >= manage['be']:
                        ns = peak - manage['trail']
                        if ns > sl:
                            sl = ns
                else:
                    peak = min(peak, l[j])
                    if entry - peak >= manage['be']:
                        ns = peak + manage['trail']
                        if ns < sl:
                            sl = ns
            j += 1
        if exit_px is None:
            exit_px = c[n - 1]; j = n - 1
        net = dirn * (exit_px - entry) - rt[i]
        trades.append((tms[j], net / R1, dirn))
        i = max(j, i + 1)
    return pd.DataFrame(trades, columns=['exit_time', 'R', 'dir']), ratio


def sharpe(R, dates):
    s = pd.Series(R, index=pd.to_datetime(dates)).sort_index()
    dl = s.groupby(s.index.normalize()).sum()
    if len(dl) < 3:
        return float('nan')
    idx = pd.date_range(dl.index.min(), dl.index.max(), freq='D')
    dd = dl.reindex(idx).fillna(0)
    return dd.mean() / dd.std(ddof=1) * np.sqrt(252) if dd.std(ddof=1) > 0 else float('nan')


def run(name, fn, tf, mode, universe=UNI, verbose=True):
    rows = []
    allt = []
    for sym in universe:
        try:
            x = Ctx(sym, tf, mode)
            t, ratio = simulate(x, fn)
        except Exception as e:
            rows.append((sym, 0, np.nan, np.nan, np.nan, np.nan, np.nan, f'ERR {type(e).__name__}: {e}'))
            continue
        if len(t) == 0 and np.isfinite(ratio) and (ratio < 0.2 or ratio > 50):
            rows.append((sym, 0, np.nan, np.nan, np.nan, np.nan, np.nan,
                         f'N/A: stop={ratio:.3g}x ATR (out of scale)'))
            continue
        if len(t) < 10:
            rows.append((sym, len(t), np.nan, np.nan, np.nan, np.nan, np.nan, 'few trades'))
            continue
        R = t['R'].values
        span = max((pd.to_datetime(t['exit_time']).max() - pd.to_datetime(t['exit_time']).min()).days / 365.25, 1e-9)
        gl = -R[R <= 0].sum()
        pf = R[R > 0].sum() / gl if gl > 0 else float('inf')
        rows.append((sym, len(R), (R > 0).mean(), R.mean(), R.sum() / span, tstat(R), pf, ''))
        t = t.copy(); t['asset'] = sym
        allt.append(t)
    if verbose:
        print(f"\n{'-'*94}\n {name}  [{tf}, mode={mode}]  net of Pepperstone cost, R units\n{'-'*94}")
        print(f"{'asset':<8}{'n':>7}{'win%':>7}{'E[R]':>9}{'R/yr':>8}{'t':>8}{'PF':>7}  note")
        for r in rows:
            if r[7]:
                print(f"{r[0]:<8}{r[1]:>7}{'':>39}  {r[7]}")
            else:
                print(f"{r[0]:<8}{r[1]:>7}{r[2]:>6.0%}{r[3]:>+9.3f}{r[4]:>+8.1f}{r[5]:>8.2f}{r[6]:>7.2f}")
    if not allt:
        return None, rows
    agg = pd.concat(allt).sort_values('exit_time')
    return agg, rows


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--mode', default='pip', choices=['pip', 'literal'])
    ap.add_argument('--only', default=None)
    ap.add_argument('--out', default=None)
    args = ap.parse_args()
    summary = []
    cells = []          # one row per (strategy, tf, asset) -- the real unit of evidence
    for nm, (fn, tfs, desc) in STRATS.items():
        if args.only and args.only.lower() not in nm.lower():
            continue
        for tf in tfs:
            agg, rows = run(f'{nm} -- {desc}', fn, tf, args.mode)
            for r in rows:
                cells.append(dict(strategy=nm, tf=tf, asset=r[0], n=r[1], win=r[2],
                                  ER=r[3], Ryr=r[4], t=r[5], PF=r[6], note=r[7],
                                  mode=args.mode))
            if agg is None or len(agg) < 20:
                print("  POOLED: too few trades")
                summary.append((nm, tf, len(agg) if agg is not None else 0, np.nan, np.nan, np.nan))
                continue
            R = agg['R'].values
            span = max((pd.to_datetime(agg['exit_time']).max() -
                        pd.to_datetime(agg['exit_time']).min()).days / 365.25, 1e-9)
            gl = -R[R <= 0].sum()
            pf = R[R > 0].sum() / gl if gl > 0 else float('inf')
            print(f"  POOLED  n={len(R)}  E[R]={R.mean():+.3f}  R/yr={R.sum()/span:+.1f}  "
                  f"t={tstat(R):.2f}  PF={pf:.2f}  Sharpe={sharpe(R, agg['exit_time']):.2f}")
            summary.append((nm, tf, len(R), R.mean(), tstat(R), pf))

    df = pd.DataFrame(cells)
    if args.out:
        df.to_csv(args.out, index=False)
        print(f"\nwrote per-asset cells -> {args.out}")

    print(f"\n{'='*74}\n POOLED SUMMARY  (mode={args.mode})\n{'='*74}")
    print(f"{'strategy':<18}{'tf':>5}{'n':>8}{'E[R]':>9}{'pooled t':>10}{'PF':>7}")
    for s in sorted(summary, key=lambda r: -(r[4] if np.isfinite(r[4]) else -99)):
        print(f"{s[0]:<18}{s[1]:>5}{s[2]:>8}{s[3]:>+9.3f}{s[4]:>10.2f}{s[5]:>7.2f}"
              if np.isfinite(s[4]) else f"{s[0]:<18}{s[1]:>5}{s[2]:>8}      --        --     --")

    # --- the honest headline: per-(strategy,asset) tests vs what chance gives -----
    v = df[df['t'].notna() & (df['n'] >= 30)]
    k = len(v)
    hits2 = int((v['t'] > 2).sum())
    hits29 = int((v['t'] > 2.9).sum())
    print(f"\n{'='*74}\n PER-ASSET TEST COUNT  (the unit that matters)\n{'='*74}")
    print(f"  runnable (strategy x tf x asset) tests with n>=30 : {k}")
    print(f"  expected by chance at t>2.0  (one-sided, 2.3%)    : {0.023*k:.1f}")
    print(f"  OBSERVED at t>2.0                                 : {hits2}")
    print(f"  expected by chance at t>2.9  (one-sided, 0.19%)   : {0.0019*k:.1f}")
    print(f"  OBSERVED at t>2.9                                 : {hits29}")
    print(f"  median t across all tests                         : {v['t'].median():+.2f}")
    print(f"  share of tests with positive E[R]                 : {(v['ER']>0).mean():.1%}")
    if hits2:
        print("\n  --- every test at t>2 ---")
        print(f"  {'strategy':<18}{'tf':>5}{'asset':>9}{'n':>7}{'E[R]':>9}{'R/yr':>8}{'t':>7}{'PF':>7}")
        for _, r in v[v['t'] > 2].sort_values('t', ascending=False).iterrows():
            print(f"  {r['strategy']:<18}{r['tf']:>5}{r['asset']:>9}{int(r['n']):>7}"
                  f"{r['ER']:>+9.3f}{r['Ryr']:>+8.1f}{r['t']:>7.2f}{r['PF']:>7.2f}")
