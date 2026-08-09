"""MQL4/MQL5 -> Python ENTRY SIGNALS, mechanically.

The MQL corpora are the largest harvested body of code in the project (2202 .mq5 +
1256 .mq4 + 615 from GitHub = 4073 files) and the least exploited: 21 MQL4 and 5 MQL5 EAs
were ever hand-ported. Hand-porting was the binding constraint, exactly as it was for Pine
before `tv_transpile`. This does for MQL what that did for Pine.

WHAT IT EXTRACTS. Not the whole program -- the entry condition. For each buy/sell call
(`OrderSend(...OP_BUY...)`, `trade.Buy(...)`, `PositionOpen(...ORDER_TYPE_BUY...)`) it
walks outward to the enclosing `if (...)` blocks and ANDs their conditions together, then
evaluates that expression vectorised over the bars. Indicator calls (`iMA`, `iRSI`,
`iMACD`, `iStochastic`, `iCCI`, `iADX`, `iBands`, `iSAR`, `iEnvelopes`, `iMomentum`,
`iWPR`, `iATR`, `iAO`, `iDeMarker`, `iForce`, `iBearsPower`, `iBullsPower`) map onto
`mt4_indicators`, which already reproduces MQL's own quirks (SMA signal line in iMACD,
summed slowing in iStochastic, population stdev in iBands, mean-absolute deviation in
iCCI). Price series `Close[k]`/`iClose(...,k)` become shifted arrays.

Bracket, lot sizing, trailing and money management are all DISCARDED -- the bracket is
ours and swept. That is what makes these files testable: the ledger's MQL passes measured
mostly the authors' fixed-POINT stops (a 30-point stop is $0.30 on BTCUSD), not their
entries.

WHAT IT REFUSES, rather than approximate:
  * `iCustom` -- the indicator's source is not in the file, so the rule is unknowable
  * external data: any symbol literal other than the chart symbol, news/calendar calls
  * lot progression (martingale/grid/recovery) -- their edge is sizing, not entry
  * `MathRand` -- not deterministic
  * any construct outside the supported expression grammar

A wrong port is worse than no port, so anything unparsed raises rather than guesses.
"""
import os, re, sys
import numpy as np
import pandas as pd

import mt4_indicators as I


class Unsupported(Exception):
    pass


# --- rejection patterns -----------------------------------------------------------
RE_ICUSTOM = re.compile(r'\biCustom\s*\(')
RE_GRID = re.compile(r'\b(martingal\w*|grid|recovery|averaging|LotMultiplier|'
                     r'lot\s*\*\s*[0-9.]+|Lots\s*\*=|MathPow\s*\(\s*[0-9.]+\s*,\s*[a-z_]*count)',
                     re.I)
RE_RAND = re.compile(r'\bMathRand\b')
RE_NEWS = re.compile(r'\b(Calendar\w*|NewsFilter|WebRequest|SendFTP|iVIX|DXY)\b', re.I)
RE_ML = re.compile(r'\b(NeuralNet|Perceptron|MLP|GeneticAlgo)\b', re.I)
# a hard-coded OTHER symbol = external data
RE_SYMLIT = re.compile(r'"(EURUSD|GBPUSD|USDJPY|USDCHF|USDCAD|AUDUSD|NZDUSD|XAUUSD|'
                       r'XAGUSD|US30|US500|NAS100|GER40|SPX500|DAX|BTCUSD|ETHUSD)"')

# Match only order-OPENING calls. A bare `OP_BUY` also appears in order-MANAGEMENT code
# (`if (OrderType() == OP_BUY)` inside a trailing-stop loop), and matching that walks up
# the wrong if-chain and returns the management guard as if it were the entry rule.
BUY = re.compile(r'OrderSend\s*\([^;]{0,200}?\bOP_BUY\b|\btrade\s*\.\s*Buy\s*\(|'
                 r'PositionOpen\s*\([^;]{0,200}?ORDER_TYPE_BUY\b|'
                 r'OrderSend\s*\([^;]{0,200}?ORDER_TYPE_BUY\b')
SELL = re.compile(r'OrderSend\s*\([^;]{0,200}?\bOP_SELL\b|\btrade\s*\.\s*Sell\s*\(|'
                  r'PositionOpen\s*\([^;]{0,200}?ORDER_TYPE_SELL\b|'
                  r'OrderSend\s*\([^;]{0,200}?ORDER_TYPE_SELL\b')
# guards that merely say "am I flat / how many orders do I have" -- the engine already
# enforces one position at a time, so these are structurally satisfied, not signal.
RE_POSCOUNT = re.compile(
    r'^\s*\(?\s*(total|totals|cnt|count|orders?|numorders|OrdersTotal\s*\(\s*\)|'
    r'PositionsTotal\s*\(\s*\)|CountTrades\s*\(\s*\)|OrdersTotalMagic\s*\([^)]*\))'
    r'\s*(==|<|<=|!=)\s*[01]\s*\)?\s*$', re.I)

MODE = {'MODE_SMA': I.MODE_SMA, 'MODE_EMA': I.MODE_EMA,
        'MODE_SMMA': getattr(I, 'MODE_SMMA', 2), 'MODE_LWMA': getattr(I, 'MODE_LWMA', 3),
        '0': I.MODE_SMA, '1': I.MODE_EMA, '2': getattr(I, 'MODE_SMMA', 2),
        '3': getattr(I, 'MODE_LWMA', 3)}
PRICE = {'PRICE_CLOSE': 0, 'PRICE_OPEN': 1, 'PRICE_HIGH': 2, 'PRICE_LOW': 3,
         'PRICE_MEDIAN': 4, 'PRICE_TYPICAL': 5, 'PRICE_WEIGHTED': 6}


def strip_comments(t):
    t = re.sub(r'/\*.*?\*/', ' ', t, flags=re.S)
    return re.sub(r'//[^\n]*', '', t)


def split_args(s):
    out, d, q, buf = [], 0, None, ''
    for ch in s:
        if q:
            buf += ch
            if ch == q:
                q = None
            continue
        if ch in '"\'':
            q = ch
        elif ch in '([':
            d += 1
        elif ch in ')]':
            d -= 1
        elif ch == ',' and d == 0:
            out.append(buf.strip()); buf = ''
            continue
        buf += ch
    if buf.strip():
        out.append(buf.strip())
    return out


def find_call(t, i):
    """Given index of '(' return (inner, index_after_close)."""
    d, j = 0, i
    while j < len(t):
        if t[j] == '(':
            d += 1
        elif t[j] == ')':
            d -= 1
            if d == 0:
                return t[i + 1:j], j + 1
        j += 1
    raise Unsupported('unbalanced call')


# MQL period constants, in minutes. 0 / PERIOD_CURRENT means "the chart's timeframe".
PERIOD = {'PERIOD_M1': 1, 'PERIOD_M5': 5, 'PERIOD_M15': 15, 'PERIOD_M30': 30,
          'PERIOD_H1': 60, 'PERIOD_H4': 240, 'PERIOD_D1': 1440, 'PERIOD_W1': 10080,
          'PERIOD_MN1': 43200}
TF_NAME = {5: 'M5', 10: 'M10', 15: 'M15', 30: 'M30', 60: 'H1', 1440: 'D1'}
TF_MIN = {'M5': 5, 'M10': 10, 'M15': 15, 'M30': 30, 'H1': 60, 'D1': 1440}


class Ctx:
    """Bars + multi-timeframe indicator evaluation for one file's expressions.

    MULTI-TIMEFRAME IS THE POINT. Measured over 500 MQL4 files, 1099 entry conditions call
    an indicator on a DIFFERENT timeframe than the chart (`iMA(NULL, PERIOD_H4, ...)`).
    Evaluating those on the chart's bars would be a silent mis-port, and refusing them
    outright rejects most of the corpus -- so they are computed on their own timeframe and
    aligned back.

    The alignment is causal by construction: a bar of the other timeframe stamped `t`
    covers [t, t+dt) and is only COMPLETE at t+dt, so the value visible when the base bar
    at time `ti` closes is the last other-TF bar whose CLOSE time is <= ti + base_dt. Same
    rule as `mt4_backtest.align`, which the earlier hand ports used. Getting this wrong is
    exactly the look-ahead trap the ledger records for daily-conditions-on-intraday-entries.
    """

    def __init__(self, b):
        self.b = b
        self.n = b.n
        self.o, self.h, self.l, self.c = b.o, b.h, b.l, b.c
        self.base_min = TF_MIN.get(b.tf, 1440)
        self._tfcache = {}

    # --- base-timeframe accessors (kept for the emitters' simple path) -----------
    def price(self, code):
        return self._px(self.o, self.h, self.l, self.c, code)

    @staticmethod
    def _px(o, h, l, c, code):
        return {0: c, 1: o, 2: h, 3: l, 4: (h + l) / 2, 5: (h + l + c) / 3,
                6: (h + l + 2 * c) / 4}[int(code)]

    def shift(self, arr, k):
        k = int(k)
        if k == 0:
            return np.asarray(arr, float)
        out = np.full(self.n, np.nan)
        a = np.asarray(arr, float)
        if k > 0:
            out[k:] = a[:-k]
        else:
            out[:k] = a[-k:]
        return out

    # --- other timeframes ---------------------------------------------------------
    def _tf(self, tfmin):
        """Load another timeframe of the SAME symbol + the base->that-TF index map."""
        if tfmin in self._tfcache:
            return self._tfcache[tfmin]
        name = TF_NAME.get(int(tfmin))
        if name is None:
            raise Unsupported(f'timeframe {tfmin} not available')
        from mt4_backtest import load
        d = load(self.b.sym, name)
        if d is None or len(d) < 100:
            raise Unsupported(f'no {name} bars for {self.b.sym}')
        o = d['open'].to_numpy(float); h = d['high'].to_numpy(float)
        l = d['low'].to_numpy(float); c = d['close'].to_numpy(float)
        oi = d.index.to_numpy()
        other_close = oi + np.timedelta64(int(tfmin), 'm')
        base_close = self.b.d.index.to_numpy() + np.timedelta64(int(self.base_min), 'm')
        idx = np.searchsorted(other_close, base_close, side='right') - 1
        self._tfcache[tfmin] = (o, h, l, c, idx)
        return self._tfcache[tfmin]

    def P(self, tfmin, code):
        """Price series ON timeframe `tfmin` (not yet aligned to base)."""
        if int(tfmin) == 0 or int(tfmin) == self.base_min:
            return self.price(code)
        o, h, l, c, _ = self._tf(tfmin)
        return self._px(o, h, l, c, code)

    def H(self, tfmin):
        return self.P(tfmin, 2)

    def L(self, tfmin):
        return self.P(tfmin, 3)

    def C(self, tfmin):
        return self.P(tfmin, 0)

    def A(self, tfmin, arr, k):
        """Shift `arr` by k bars ON ITS OWN timeframe, then align to the base bars."""
        if int(tfmin) == 0 or int(tfmin) == self.base_min:
            return self.shift(arr, k)
        _, _, _, _, idx = self._tf(tfmin)
        a = np.asarray(arr, float)
        j = idx - int(k)
        out = np.full(self.n, np.nan)
        ok = (j >= 0) & (j < len(a)) & (idx >= 0)
        out[ok] = a[j[ok]]
        return out


def _num(x):
    try:
        return float(x)
    except Exception:
        return None


class Expr:
    """Translate one MQL expression into Python source over numpy arrays.

    Deliberately small: the supported grammar is indicator calls, price series,
    numeric/`input` constants, comparisons and and/or/not. Anything else raises."""

    def __init__(self, consts, ctxname='X'):
        self.consts = consts
        self.X = ctxname
        self.uses_ind = False
        self.tfs = set()          # every timeframe the expression reads, for the manifest

    def translate(self, s):
        s = s.strip()
        if not s:
            raise Unsupported('empty expression')
        s = self._mathfns(s)
        s = self._indicators(s)
        s = self._series(s)
        s = self._consts(s)
        s = self._ops(s)
        # Validate on a copy with OUR OWN generated calls stripped. Checking the raw
        # string flags `X.shift(...)`/`I.rsi(...)` -- the very code this compiler emits --
        # as "unresolved", which silently rejected ~1000 correctly-translated conditions.
        probe = re.sub(r'\b(?:np|pd|X|I)\.\w+', '@', s)
        if re.search(r'[A-Za-z_]\w*\s*\(', probe):
            raise Unsupported('unresolved call in: ' + s[:60])
        if re.search(r'(?<![\w.])[A-Za-z_]\w*(?![\w(])',
                     re.sub(r'\b(True|False|nan|PT)\b', '', probe)):
            raise Unsupported('unresolved name in: ' + s[:60])
        return s

    # --- MQL library maths -> numpy ------------------------------------------------
    _MATH = {'MathAbs': 'np.abs', 'MathMax': 'np.maximum', 'MathMin': 'np.minimum',
             'MathSqrt': 'np.sqrt', 'MathFloor': 'np.floor', 'MathCeil': 'np.ceil',
             'MathPow': 'np.power', 'MathLog': 'np.log', 'MathExp': 'np.exp',
             'fabs': 'np.abs'}

    # Broker/account state, always satisfied in a backtest. These are operational guards,
    # not signal -- an EA that refuses to trade when the terminal is offline is not
    # expressing a view on the market. Replaced by True rather than making the file
    # unportable. (Position-count guards are handled separately, in RE_POSCOUNT.)
    _OPERATIONAL = (
        'IsTradeAllowed', 'IsConnected', 'IsTesting', 'IsExpertEnabled', 'IsDemo',
        'IsOptimization', 'IsVisualMode', 'IsStopped', 'IsTradeContextBusy',
        'AccountFreeMargin', 'AccountBalance', 'AccountEquity', 'AccountMargin',
        'CheckMoneyForTrade', 'CheckVolumeValue', 'CheckStopLoss_Takeprofit',
        'MarketInfo', 'AccountNumber', 'GetLastError', 'TerminalInfoInteger')

    def _mathfns(self, s):
        for fn in self._OPERATIONAL:
            while True:
                m = re.search(rf'(?<![\w.])){fn}\s*\(' if False else rf'(?<![\w.]){fn}\s*\(', s)
                if not m:
                    break
                _, end = find_call(s, m.end() - 1)
                s = s[:m.start()] + 'True' + s[end:]
        # a comparison against a now-boolean operational term is itself just True
        s = re.sub(r'True\s*(==|!=|>|<|>=|<=)\s*[-\w.]+', 'True', s)
        s = re.sub(r'[-\w.]+\s*(==|!=|>|<|>=|<=)\s*True(?![\w])', 'True', s)
        for k, v in self._MATH.items():
            s = re.sub(rf'\b{k}\s*\(', v + '(', s)
        # NormalizeDouble(x, digits) only rounds for display; the comparison is unaffected
        while True:
            m = re.search(r'\bNormalizeDouble\s*\(', s)
            if not m:
                break
            inner, end = find_call(s, m.end() - 1)
            s = s[:m.start()] + '(' + split_args(inner)[0] + ')' + s[end:]
        return s

    # --- indicator calls ---------------------------------------------------------
    def _indicators(self, s):
        pat = re.compile(r'\bi([A-Z]\w*)\s*\(')
        while True:
            m = pat.search(s)
            if not m:
                return s
            name = m.group(1)
            inner, end = find_call(s, m.end() - 1)
            args = split_args(inner)
            rep = self._one_indicator(name, args)
            s = s[:m.start()] + rep + s[end:]
            self.uses_ind = True

    def _arg(self, a, default=None):
        a = a.strip()
        v = _num(a)
        if v is not None:
            return v
        if a in self.consts:
            return self.consts[a]
        if a in MODE:
            return MODE[a]
        if a in PRICE:
            return PRICE[a]
        if default is not None:
            return default
        raise Unsupported(f'non-constant indicator arg: {a}')

    def _one_indicator(self, name, args):
        X = self.X
        n = name.upper()
        # every iXxx starts (symbol, timeframe, ...) -- reject another symbol / another TF
        TF = 0
        if len(args) >= 2:
            sym, tfa = args[0].strip(), args[1].strip()
            if sym not in ('NULL', '0', 'Symbol()', '_Symbol', 'symbol', 'Sym'):
                raise Unsupported('indicator on another symbol')
            # The timeframe may be a PERIOD_* constant, a literal minute count, or an
            # input constant. Resolve it and honour it -- computing an H4 indicator on
            # D1 bars would be a silent mis-port, and refusing every multi-timeframe EA
            # would reject most of the corpus.
            if tfa in self.consts:
                v = self.consts[tfa]
                tfa = str(int(v)) if float(v).is_integer() else str(v)
            if tfa in ('0', 'PERIOD_CURRENT', '_Period', 'Period()'):
                TF = 0
            elif tfa in PERIOD:
                TF = PERIOD[tfa]
            else:
                v = _num(tfa)
                if v is None:
                    raise Unsupported('non-constant timeframe')
                TF = int(v)
            if TF and TF not in TF_NAME:
                raise Unsupported(f'timeframe {TF} not in the data cache')
            rest = args[2:]
        else:
            rest = args
        g = self._arg
        self.tfs.add(TF)

        # Every emitter computes on timeframe TF and aligns back with X.A(TF, ..., shift).
        # X.P/H/L/C(TF) are that timeframe's own series.
        P = f'{X}.P({TF},'
        HLC = f'{X}.H({TF}),{X}.L({TF}),{X}.C({TF})'
        HL = f'{X}.H({TF}),{X}.L({TF})'

        if n in ('CLOSE', 'OPEN', 'HIGH', 'LOW'):
            k = g(rest[0], 0) if rest else 0
            return f'{X}.A({TF},{P}{PRICE["PRICE_"+n]}),{int(k)})'
        if n == 'MA':
            p, sh, meth, pr, k = (int(g(rest[0])), int(g(rest[1], 0)),
                                  int(g(rest[2], 0)), int(g(rest[3], 0)), int(g(rest[4], 0)))
            return f'{X}.A({TF},I.ma({P}{pr}),{p},{meth},{sh}),{k})'
        if n == 'RSI':
            p, pr, k = int(g(rest[0])), int(g(rest[1], 0)), int(g(rest[2], 0))
            return f'{X}.A({TF},I.rsi({P}{pr}),{p}),{k})'
        if n == 'ATR':
            p, k = int(g(rest[0])), int(g(rest[1], 0))
            return f'{X}.A({TF},I.atr({HLC},{p}),{k})'
        if n == 'MOMENTUM':
            p, pr, k = int(g(rest[0])), int(g(rest[1], 0)), int(g(rest[2], 0))
            return f'{X}.A({TF},I.momentum({P}{pr}),{p}),{k})'
        if n == 'CCI':
            p, pr, k = int(g(rest[0])), int(g(rest[1], 0)), int(g(rest[2], 0))
            return f'{X}.A({TF},I.cci({HLC},{p}),{k})'
        if n == 'MACD':
            f_, sl, sg = int(g(rest[0])), int(g(rest[1])), int(g(rest[2]))
            pr, mode, k = int(g(rest[3], 0)), rest[4].strip(), int(g(rest[5], 0))
            sel = 0 if 'MAIN' in mode or mode == '0' else 1
            return f'{X}.A({TF},I.macd({P}{pr}),{f_},{sl},{sg})[{sel}],{k})'
        if n == 'BANDS':
            p, dev, sh = int(g(rest[0])), float(g(rest[1])), int(g(rest[2], 0))
            pr, mode, k = int(g(rest[3], 0)), rest[4].strip(), int(g(rest[5], 0))
            sel = {'MODE_UPPER': 0, 'MODE_MAIN': 1, 'MODE_LOWER': 2,
                   '1': 0, '0': 1, '2': 2}.get(mode)
            if sel is None:
                raise Unsupported('iBands mode')
            return f'{X}.A({TF},I.bands({P}{pr}),{p},{dev})[{sel}],{k})'
        if n == 'STOCHASTIC':
            kp, dp, sl_ = int(g(rest[0])), int(g(rest[1])), int(g(rest[2]))
            meth, pf, mode = int(g(rest[3], 0)), int(g(rest[4], 0)), rest[5].strip()
            k = int(g(rest[6], 0))
            sel = 0 if 'MAIN' in mode or mode == '0' else 1
            return (f'{X}.A({TF},I.stochastic({HLC},{kp},{dp},{sl_},'
                    f'{meth},{pf})[{sel}],{k})')
        if n == 'ADX':
            p, pr, mode, k = (int(g(rest[0])), int(g(rest[1], 0)),
                              rest[2].strip(), int(g(rest[3], 0)))
            sel = {'MODE_MAIN': 0, 'MODE_PLUSDI': 1, 'MODE_MINUSDI': 2,
                   '0': 0, '1': 1, '2': 2}.get(mode)
            if sel is None:
                raise Unsupported('iADX mode')
            return f'{X}.A({TF},I.adx({HLC},{p})[{sel}],{k})'
        if n == 'SAR':
            st, mx, k = float(g(rest[0])), float(g(rest[1])), int(g(rest[2], 0))
            return f'{X}.A({TF},I.sar({HL},{st},{mx}),{k})'
        if n == 'ENVELOPES':
            p, meth, sh = int(g(rest[0])), int(g(rest[1], 0)), int(g(rest[2], 0))
            pr, dev, mode = int(g(rest[3], 0)), float(g(rest[4])), rest[5].strip()
            k = int(g(rest[6], 0))
            sel = 0 if 'UPPER' in mode or mode == '1' else 1
            return f'{X}.A({TF},I.envelopes({P}{pr}),{p},{meth},{dev})[{sel}],{k})'
        if n == 'WPR':
            p, k = int(g(rest[0])), int(g(rest[1], 0))
            return (f'{X}.A({TF},np.asarray(-100*(pd.Series({X}.H({TF})).rolling({p}).max()'
                    f'-pd.Series({X}.C({TF})))/'
                    f'(pd.Series({X}.H({TF})).rolling({p}).max()-'
                    f'pd.Series({X}.L({TF})).rolling({p}).min()).replace(0,np.nan)),{k})')
        if n in ('BEARSPOWER', 'BULLSPOWER'):
            p, pr, k = int(g(rest[0])), int(g(rest[1], 0)), int(g(rest[2], 0))
            fn = 'bears_power' if n == 'BEARSPOWER' else 'bulls_power'
            return f'{X}.A({TF},I.{fn}({HLC},{p}),{k})'
        if n == 'AO':
            k = int(g(rest[0], 0)) if rest else 0
            return f'{X}.A({TF},I.ao({HL}),{k})'
        if n == 'AC':
            k = int(g(rest[0], 0)) if rest else 0
            return f'{X}.A({TF},I.ac({HL}),{k})'
        if n in ('VOLUME', 'OBV', 'MFI', 'AD', 'BWMFI'):
            raise Unsupported('volume-dependent indicator')
        raise Unsupported(f'indicator i{name}')

    # --- price series -------------------------------------------------------------
    def _series(self, s):
        X = self.X
        for nm, code in (('Close', 0), ('Open', 1), ('High', 2), ('Low', 3)):
            s = re.sub(rf'\b{nm}\s*\[\s*([0-9]+)\s*\]',
                       lambda m, c=code: f'{X}.shift({X}.price({c}),{int(m.group(1))})', s)
        s = re.sub(r'\bBid\b|\bAsk\b', f'{X}.price(0)', s)
        s = re.sub(r'\bPoint\b|\b_Point\b', 'PT', s)
        return s

    def _consts(self, s):
        def rep(m):
            nm = m.group(0)
            if nm in ('and', 'or', 'not', 'np', 'X', 'I', 'pd', 'PT', 'True', 'False'):
                return nm
            if nm in self.consts:
                return repr(self.consts[nm])
            return nm
        return re.sub(r'(?<![\w.])[A-Za-z_]\w*(?![\w(])', rep, s)

    def _ops(self, s):
        s = s.replace('&&', ' and ').replace('||', ' or ')
        s = re.sub(r'(?<![<>=!])!(?!=)', ' not ', s)
        s = s.replace('true', 'True').replace('false', 'False')
        # numpy needs bitwise ops on arrays
        s = s.replace(' and ', ' & ').replace(' or ', ' | ').replace(' not ', ' ~')
        return s


def parse_consts(t):
    """`input`/`extern`/`#define` numeric constants -- the author's published settings."""
    consts = {}
    for m in re.finditer(r'(?:input|extern|static)\s+(?:const\s+)?'
                         r'(?:int|double|float|bool|long)\s+(\w+)\s*=\s*([^;,]+)[;,]', t):
        v = _num(m.group(2).strip())
        if v is None:
            low = m.group(2).strip().lower()
            if low in ('true', 'false'):
                v = 1.0 if low == 'true' else 0.0
        if v is not None:
            consts[m.group(1)] = v
    for m in re.finditer(r'#define\s+(\w+)\s+([-\d.]+)', t):
        v = _num(m.group(2))
        if v is not None:
            consts[m.group(1)] = v
    for m in re.finditer(r'(?:^|\n)\s*(?:int|double|float|bool)\s+(\w+)\s*=\s*([-\d.]+)\s*;', t):
        consts[m.group(1)] = float(m.group(2))
    return consts


def local_assignments(t, consts):
    """`double ma = iMA(...);` -> name -> expression source, resolved in order."""
    out = {}
    for m in re.finditer(r'\b(?:double|int|bool)\s+(\w+)\s*=\s*([^;]+);', t):
        out[m.group(1)] = m.group(2).strip()
    for m in re.finditer(r'(?<![\w.])(\w+)\s*=\s*(i[A-Z]\w*\s*\([^;]+)\s*;', t):
        out.setdefault(m.group(1), m.group(2).strip())
    return out


def _match_back(t, j):
    """`j` indexes a ')'. Return the index of its matching '('."""
    d, k = 0, j
    while k >= 0:
        if t[k] == ')':
            d += 1
        elif t[k] == '(':
            d -= 1
            if d == 0:
                return k
        k -= 1
    raise Unsupported('unbalanced paren')


def _chain_from_paren(t, jclose, conds):
    """Given a ')' that may close an `if (...)`, consume it and every brace-less `if`
    chained immediately before it. Returns the index to continue scanning from.

    MQL4 EAs overwhelmingly write guards as `if (a)\\n if (b)\\n if (c)\\n { trade }` with
    no braces on the outer levels; treating only the innermost `if` as the condition
    silently drops most of the rule, which is worse than not porting it."""
    while True:
        kk = _match_back(t, jclose)
        head = t[max(0, kk - 14):kk]
        if re.search(r'\belse\s+if\s*$', head):
            raise Unsupported('trade in an else-if branch')
        if re.search(r'\b(for|while|switch)\s*$', head):
            raise Unsupported('trade inside a loop')
        m = re.search(r'\bif\s*$', head)
        if not m:
            return kk
        conds.append(t[kk + 1:jclose])
        # continue from BEFORE the `if` keyword, not before its '(' -- otherwise the
        # scan lands on the "f" of "if" and the brace-less chain stops after one level.
        if_start = kk - (len(head) - m.start())
        p = if_start - 1
        while p > 0 and t[p] in ' \t\r\n':
            p -= 1
        # another brace-less `if (...)` immediately before this one?
        if p > 0 and t[p] == ')':
            jclose = p
            continue
        return if_start


def simple_functions(t):
    """Zero-arg user helpers whose whole body is `return <expr>;` -> inlinable source.

    MQL EAs routinely wrap a piece of the entry rule in a helper (`BuySignal()`,
    `TrendUp()`). Refusing every file that has one would reject most of the corpus;
    inlining the single-expression ones keeps the port faithful. Helpers with real control
    flow are NOT inlined -- they make the file unsupported, which is the safe direction."""
    out = {}
    for m in re.finditer(r'\b(?:bool|int|double)\s+(\w+)\s*\(\s*\)\s*\{', t):
        name = m.group(1)
        d, i = 0, m.end() - 1
        while i < len(t):
            if t[i] == '{':
                d += 1
            elif t[i] == '}':
                d -= 1
                if d == 0:
                    break
            i += 1
        body = t[m.end():i].strip()
        rm = re.fullmatch(r'return\s*\(?\s*(.+?)\s*\)?\s*;', body, re.S)
        if rm and 'if' not in body and 'for' not in body and 'while' not in body:
            out[name] = rm.group(1)
    return out


def enclosing_conditions(t, pos):
    """Walk backwards from a trade call, collecting every `if (...)` that governs it.

    Handles both braced blocks and MQL's very common brace-less nested `if` chains.
    Brace-matched rather than indentation-based: MQL has no significant whitespace."""
    conds, depth, i = [], 0, pos

    # case 1: the call is the un-braced body of `if (...) OrderSend(...);` -- possibly
    # via an assignment, `if (...) ticket = OrderSend(...);`
    j = pos - 1
    while j > 0 and t[j] in ' \t\r\n':
        j -= 1
    if j > 0 and t[j] == '=' and t[j - 1] not in '=!<>':
        j -= 1
        while j > 0 and (t[j].isalnum() or t[j] in ' \t\r\n_[].'):
            j -= 1
    if j > 0 and t[j] == ')':
        try:
            i = _chain_from_paren(t, j, conds)
        except Unsupported:
            raise

    # case 2: walk out through enclosing braces
    while i > 0:
        ch = t[i]
        if ch == '}':
            depth += 1
        elif ch == '{':
            if depth == 0:
                j = i - 1
                while j > 0 and t[j] in ' \t\r\n':
                    j -= 1
                if j > 0 and t[j] == '}':
                    raise Unsupported('trade in an else branch')
                if j > 0 and t[j] == ')':
                    i = _chain_from_paren(t, j, conds)
                    continue
            else:
                depth -= 1
        i -= 1
    return list(reversed(conds))


def compile_file(path, max_bytes=400_000):
    """One MQL file -> (long_expr_src, short_expr_src, meta). Raises Unsupported."""
    raw = open(path, encoding='utf-8', errors='replace').read()
    if len(raw) > max_bytes:
        raise Unsupported('file too large')
    t = strip_comments(raw)
    if RE_ICUSTOM.search(t):
        raise Unsupported('iCustom')
    if RE_GRID.search(t):
        raise Unsupported('lot progression')
    if RE_RAND.search(t):
        raise Unsupported('MathRand')
    if RE_NEWS.search(t) or RE_SYMLIT.search(t):
        raise Unsupported('external data')
    if RE_ML.search(t):
        raise Unsupported('ML')

    consts = parse_consts(t)
    locs = local_assignments(t, consts)
    helpers = simple_functions(t)

    def resolve(src, depth=0):
        if depth > 12:
            raise Unsupported('assignment recursion')
        # inline zero-argument user helpers with a single `return <expr>;`
        for nm, body in helpers.items():
            if re.search(rf'(?<![\w.]){nm}\s*\(\s*\)', src):
                src = re.sub(rf'(?<![\w.]){nm}\s*\(\s*\)', f'({body})', src)
                return resolve(src, depth + 1)
        names = set(re.findall(r'(?<![\w.])([A-Za-z_]\w*)(?![\w(])', src))
        for nm in names:
            if nm in locs and nm not in consts:
                src = re.sub(rf'(?<![\w.]){nm}(?![\w(])', f'({locs[nm]})', src)
                return resolve(src, depth + 1)
        return src

    sides = {}
    for tag, pat in (('long', BUY), ('short', SELL)):
        exprs = []
        for m in pat.finditer(t):
            try:
                conds = enclosing_conditions(t, m.start())
            except Unsupported:
                continue
            if not conds:
                continue
            E = Expr(consts)
            parts = []
            for c in conds:
                # "am I flat" guards are enforced by the engine, not by the rule
                if RE_POSCOUNT.match(c.strip()):
                    continue
                try:
                    parts.append('(' + E.translate(resolve(c)) + ')')
                except Unsupported:
                    parts = []
                    break
            # 2026-08-09: la garde etait `parts and E.uses_ind`, ce qui exigeait que la
            # condition d'entree appelle un INDICATEUR et jetait donc en silence toute
            # strategie en pur PRICE ACTION (cassure, chandelier, niveau de la veille,
            # heure de seance) — precisement la classe visee par le mandat intraday.
            # On accepte maintenant toute condition traduite; la degenerescence (un
            # signal qui tire sur ~toutes les barres, ou sur presque aucune) est
            # filtree en aval, empiriquement, dans corpus_mqlrun.py.
            if parts:
                exprs.append(' & '.join(parts))
        if exprs:
            sides[tag] = ' | '.join(f'({e})' for e in set(exprs))
    if not sides:
        raise Unsupported('no compilable entry condition')
    return sides, dict(consts=len(consts), path=path)


def run_compiled(sides, b):
    """Evaluate compiled sides on one Bars -> int8 signal array."""
    X = Ctx(b)
    env = {'X': X, 'I': I, 'np': np, 'pd': pd, 'PT': b.point,
           'nan': np.nan, 'True': True, 'False': False}
    n = b.n

    def ev(src):
        v = eval(src, env)
        if np.isscalar(v):
            return np.zeros(n, bool) if not v else np.ones(n, bool)
        v = np.asarray(v)
        if v.dtype != bool:
            v = np.nan_to_num(v, nan=0.0) != 0
        return v[:n] if len(v) >= n else np.pad(v, (0, n - len(v)))

    L = ev(sides['long']) if 'long' in sides else np.zeros(n, bool)
    S = ev(sides['short']) if 'short' in sides else np.zeros(n, bool)
    sig = np.zeros(n, np.int8)
    sig[L] = 1
    sig[S & ~L] = -1
    return sig
