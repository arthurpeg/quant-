"""Regles INTRADAY ANCREES SUR LA SEANCE — le trou que `tsam_rules` ne couvre pas.

Pourquoi ce fichier. `tsam_rules.py` (153 regles) est le canon des INDICATEURS et il
est agnostique au timeframe: une moyenne mobile, un MACD ou un Keltner ne savent pas
qu'une seance existe. Verifie: zero occurrence de opening range, VWAP, pivot de
plancher, PDH/PDL, balance initiale ou Supertrend/Heikin-Ashi/Ichimoku dedans.
Or **ce sont precisement les mecanismes qui n'ont de sens qu'en intraday** — ceux qui
utilisent l'HORLOGE (l'ouverture, la premiere heure, le milieu de seance) et les
NIVEAUX DE LA VEILLE. Les passer, c'est passer a cote de la moitie intraday du sujet.

  A. ANCRAGE SEANCE — ouverture / balance initiale / niveaux de la veille / VWAP de
     seance / milieu de seance (le "TSM Midday Support and Resistance" de Kaufman) /
     gap d'ouverture / momentum de seance.
  B. LES FAMILLES DU CORPUS DE CODE ABSENTES DU CANON — Supertrend, Heikin-Ashi,
     Ichimoku, pivots de plancher. `RESEARCH_LOG_CODE.md` les a testees en D1
     seulement, alors que **293 des 353 strategies freqtrade qui declarent un
     timeframe sont en 1m/5m/15m** — elles n'ont jamais tourne a leur granularite.

⚠️ TOUT SE CALCULE SUR LE SOUS-ENSEMBLE EN SEANCE, PAS SUR LE JOUR CALENDAIRE.
C'est le piege de ce fichier et il est silencieux: les barres M5/M15 reconstruites
du cache M1 couvrent 23 h, donc "la premiere barre de la seance" prise sur le jour
local est une barre de MINUIT, pas l'ouverture. Un opening range calcule ainsi est
faux sans jamais lever d'erreur. On restreint donc a `b.in_window`, on calcule tout
dans cet espace compacte, puis on redisperse vers la longueur complete.

CAUSALITE: chaque signal est decide a la CLOTURE de sa barre et ne lit que des barres
<= elle. Les niveaux de la veille sont ceux de la seance PRECEDENTE, l'opening range
est fige des que ses k barres sont closes, et rien n'est lu sur la barre d'entree.
Le moteur (`kauf_lib.Table`) remplit ensuite a l'ouverture de la barre suivante.

Chaque regle rend un tableau int8 de longueur n: +1 long, -1 short, 0 rien.
"""
import numpy as np
import pandas as pd

BAR_MIN = {'M5': 5, 'M10': 10, 'M15': 15, 'M30': 30}


def _state(long_c, short_c):
    s = np.zeros(len(long_c), np.int8)
    lc = np.nan_to_num(long_c, nan=0).astype(bool)
    sc = np.nan_to_num(short_c, nan=0).astype(bool)
    s[lc] = 1
    s[sc & ~lc] = -1
    return s


def _atr(h, l, c, n=14):
    pc = np.concatenate(([c[0]], c[:-1]))
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    out = np.full(len(c), np.nan)
    if len(c) > n:
        out[n - 1] = tr[:n].mean()
        for i in range(n, len(c)):
            out[i] = (out[i - 1] * (n - 1) + tr[i]) / n
    return out


def _heikin(o, h, l, c):
    ha_c = (o + h + l + c) / 4.0
    ha_o = np.empty_like(ha_c)
    ha_o[0] = (o[0] + c[0]) / 2.0
    for i in range(1, len(c)):
        ha_o[i] = (ha_o[i - 1] + ha_c[i - 1]) / 2.0
    return ha_o, ha_c


def _supertrend(h, l, c, n=10, mult=3.0):
    atr = _atr(h, l, c, n)
    hl2 = (h + l) / 2.0
    up, dn = hl2 + mult * atr, hl2 - mult * atr
    trend = np.ones(len(c), np.int8)
    fu, fd = up.copy(), dn.copy()
    for i in range(1, len(c)):
        fu[i] = min(up[i], fu[i - 1]) if (c[i - 1] <= fu[i - 1]) else up[i]
        fd[i] = max(dn[i], fd[i - 1]) if (c[i - 1] >= fd[i - 1]) else dn[i]
        if c[i] > fu[i - 1]:
            trend[i] = 1
        elif c[i] < fd[i - 1]:
            trend[i] = -1
        else:
            trend[i] = trend[i - 1]
    return trend


def _first_k(g, x, k, how):
    """max/min des k PREMIERES barres de chaque groupe, diffuse sur le groupe."""
    pos = g.cumcount()
    masked = np.where(pos.to_numpy() < k, x, -np.inf if how == 'max' else np.inf)
    s = pd.Series(masked).groupby(g.obj.to_numpy() if hasattr(g, 'obj') else None)
    return s


def all_rules(b):
    """b = kauf_lib.Bars. -> dict nom -> tableau int8 de longueur b.n."""
    n = b.n
    win = np.asarray(b.in_window, bool)
    idx = np.flatnonzero(win)                    # indices des barres EN SEANCE
    if len(idx) < 500:
        return {}

    # --- espace compacte: uniquement les barres en seance ---------------------
    o, h, l, c = b.o[idx], b.h[idx], b.l[idx], b.c[idx]
    sess = np.asarray(b.sess)[idx]
    atr = np.asarray(b.atr)[idx]
    m = len(idx)
    S = pd.Series(sess)
    grp = S.groupby(S, sort=False)
    pos = grp.cumcount().to_numpy()              # rang DANS LA SEANCE
    sess_len = grp.transform('size').to_numpy()

    def bcast(series_by_sess):
        return series_by_sess.reindex(sess).to_numpy()

    def prev_agg(x, how):
        a = pd.Series(x).groupby(sess).agg(how)
        return bcast(a.shift(1))

    def first_k(x, k, how):
        """agg des k premieres barres de la seance, NaN tant qu'elles ne sont pas closes"""
        masked = np.where(pos < k, x, -np.inf if how == 'max' else np.inf)
        a = pd.Series(masked).groupby(sess).agg(how)
        v = bcast(a)
        return np.where(pos >= k, v, np.nan)

    R = {}
    # ---- A1. OPENING RANGE BREAKOUT / FADE ------------------------------------
    per_h = max(1, int(round(60 / BAR_MIN[b.tf])))
    widths = sorted({1, 2, 3, 6, per_h})
    or_rng = {}
    for k in widths:
        hi, lo = first_k(h, k, 'max'), first_k(l, k, 'min')
        or_rng[k] = (hi, lo)
        R[f'ORB_break_{k}'] = _state(c > hi, c < lo)
        R[f'ORB_fade_{k}'] = _state(c < lo, c > hi)
    # precondition de Crabel: une seance qui s'ouvre SERREE casse mieux
    k = per_h
    hi, lo = or_rng[k]
    rng = hi - lo
    ref = pd.Series(rng).rolling(4000, min_periods=200).median().to_numpy()
    narrow, wide = rng < ref, rng > ref
    R[f'ORB_break_{k}_narrow'] = _state((c > hi) & narrow, (c < lo) & narrow)
    R[f'ORB_break_{k}_wide'] = _state((c > hi) & wide, (c < lo) & wide)

    # ---- A2. NIVEAUX DE LA VEILLE (PDH / PDL / PDC), en SEANCE ---------------
    pdh, pdl, pdc = prev_agg(h, 'max'), prev_agg(l, 'min'), prev_agg(c, 'last')
    R['PDHL_break'] = _state(c > pdh, c < pdl)
    R['PDHL_fade'] = _state(c < pdl, c > pdh)
    R['PDC_side'] = _state(c > pdc, c < pdc)

    # ---- A3. GAP D'OUVERTURE de seance ---------------------------------------
    sopen = bcast(pd.Series(o).groupby(sess).first())
    gap = (sopen - pdc) / np.where(np.abs(pdc) > 0, np.abs(pdc), np.nan)
    gthr = pd.Series(np.abs(gap)).rolling(4000, min_periods=200).quantile(0.7).to_numpy()
    big = np.abs(gap) > gthr
    R['SessGap_fade'] = _state(big & (gap > 0) & (pos > 0) & (c < sopen),
                               big & (gap < 0) & (pos > 0) & (c > sopen))
    R['SessGap_follow'] = _state(big & (gap > 0) & (pos > 0) & (c > sopen),
                                 big & (gap < 0) & (pos > 0) & (c < sopen))

    # ---- A4. VWAP DE SEANCE ---------------------------------------------------
    vol = (b.d['tick_volume'].to_numpy(float)[idx] if 'tick_volume' in b.d
           else np.ones(m))
    tp = (h + l + c) / 3.0
    cpv = pd.Series(tp * vol).groupby(sess).cumsum().to_numpy()
    cv = pd.Series(vol).groupby(sess).cumsum().to_numpy()
    vwap = np.where(cv > 0, cpv / np.maximum(cv, 1e-9), np.nan)
    R['VWAP_side'] = _state((pos > 2) & (c > vwap), (pos > 2) & (c < vwap))
    dev = (c - vwap) / np.where(np.isfinite(atr) & (atr > 0), atr, np.nan)
    R['VWAP_revert'] = _state((pos > 2) & (dev < -1.0), (pos > 2) & (dev > 1.0))
    R['VWAP_follow'] = _state((pos > 2) & (dev > 1.0), (pos > 2) & (dev < -1.0))

    # ---- A5. MIDDAY SUPPORT/RESISTANCE (Kaufman TSaM ch.16) ------------------
    half = int(max(2, np.median(sess_len) // 2))
    mh, ml = first_k(h, half, 'max'), first_k(l, half, 'min')
    mr = mh - ml
    R['MiddaySR'] = _state(c <= ml + 0.25 * mr, c >= mh - 0.25 * mr)
    R['MiddayBreak'] = _state(c > mh, c < ml)

    # ---- A6. MOMENTUM DE SEANCE ----------------------------------------------
    rs = (c - sopen) / np.where(np.isfinite(atr) & (atr > 0), atr, np.nan)
    R['SessMom_follow'] = _state((pos > 2) & (rs > 0.5), (pos > 2) & (rs < -0.5))
    R['SessMom_fade'] = _state((pos > 2) & (rs < -0.5), (pos > 2) & (rs > 0.5))

    # ---- A7. PREMIERE BARRE de seance ----------------------------------------
    fb_up = bcast(pd.Series((c > o).astype(float)).groupby(sess).first()) > 0.5
    R['FirstBar_follow'] = _state((pos == 1) & fb_up, (pos == 1) & ~fb_up)
    R['FirstBar_fade'] = _state((pos == 1) & ~fb_up, (pos == 1) & fb_up)

    # ---- B1. PIVOTS DE PLANCHER ----------------------------------------------
    P = (pdh + pdl + pdc) / 3.0
    R1, S1 = 2 * P - pdl, 2 * P - pdh
    R['FloorPivot_side'] = _state(c > P, c < P)
    R['FloorPivot_break'] = _state(c > R1, c < S1)
    R['FloorPivot_fade'] = _state(c < S1, c > R1)

    # ---- B2. SUPERTREND / HEIKIN-ASHI / ICHIMOKU ------------------------------
    for nn, mm in ((10, 3.0), (10, 2.0), (20, 3.0)):
        st = _supertrend(h, l, c, nn, mm)
        R[f'Supertrend_{nn}_{mm}'] = _state(st > 0, st < 0)
    ha_o, ha_c = _heikin(o, h, l, c)
    R['HeikinAshi_dir'] = _state(ha_c > ha_o, ha_c < ha_o)
    ts = (pd.Series(h).rolling(9).max() + pd.Series(l).rolling(9).min()).to_numpy() / 2
    ks = (pd.Series(h).rolling(26).max() + pd.Series(l).rolling(26).min()).to_numpy() / 2
    spa = np.full(m, np.nan); spa[26:] = ((ts + ks) / 2)[:-26]
    spb_ = (pd.Series(h).rolling(52).max() + pd.Series(l).rolling(52).min()).to_numpy() / 2
    spb = np.full(m, np.nan); spb[26:] = spb_[:-26]
    R['Ichimoku_cloud'] = _state(c > np.fmax(spa, spb), c < np.fmin(spa, spb))
    R['Ichimoku_tk'] = _state(ts > ks, ts < ks)

    # --- redispersion vers la longueur complete --------------------------------
    out = {}
    for name, v in R.items():
        full = np.zeros(n, np.int8)
        full[idx] = np.asarray(v, np.int8)
        out[name] = full
    return out
