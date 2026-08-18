"""Bibliotheque de signaux : la formule exacte de chaque S_t, et rien d'autre.

Un seul fichier definit les formules, pour la recherche ET pour l'execution
future. C'est deliberé : dans ce depot la parite backtest/live a deja ete
perdue deux fois parce que deux fichiers calculaient "le meme" indicateur.

REGLE UNIQUE ET NON NEGOCIABLE : toute fonction de ce module rend un tableau
dont la case i n'utilise QUE des barres d'indice <= i. Aucune moyenne centree,
aucun `shift(-1)`, aucun `bfill`, aucune normalisation par une statistique de
l'echantillon entier. Les seules statistiques globales autorisees sont celles
qui servent a RANGER (etape 3), jamais a construire S_t.

LES SESSIONS SONT ANCREES SUR L'HEURE LOCALE DE LEUR PLACE, PAS SUR UNE HEURE
UTC FIXE. L'ouverture de New York est 09h30 America/New_York : c'est 13h30 UTC
en ete et 14h30 UTC en hiver. Un seuil UTC fixe se decale d'une heure deux fois
par an et fabrique une fausse saisonnalite (ou detruit la vraie).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# ------------------------------------------------------------------ sessions
# (tz de la place, heure de debut, minute de debut, heure de fin, minute de fin)
SESSIONS = {
    "NY":     ("America/New_York", 9, 30, 16, 0),
    "LONDON": ("Europe/London", 8, 0, 16, 30),
    "ASIA":   ("Asia/Tokyo", 9, 0, 15, 0),
}
LONDON_FIX = ("Europe/London", 16, 0)     # fixing 16h heure de Londres


def _clock(bars, tz: str):
    """(minutes depuis minuit local, identifiant de jour local), en cache."""
    key = f"clock:{tz}"
    if key not in bars.cache:
        loc = bars.t.tz_convert(tz)
        mins = np.asarray(loc.hour) * 60 + np.asarray(loc.minute)
        day = np.asarray(loc.normalize().tz_localize(None).astype("int64"))
        bars.cache[key] = (mins, day)
    return bars.cache[key]


def session_mask(bars, name: str):
    """(dans la session, identifiant de jour local) pour une place donnee."""
    tz, h0, m0, h1, m1 = SESSIONS[name]
    mins, day = _clock(bars, tz)
    lo, hi = h0 * 60 + m0, h1 * 60 + m1
    return (mins >= lo) & (mins < hi), day, mins


def _grp_first(x: np.ndarray, g: np.ndarray, valid: np.ndarray) -> np.ndarray:
    """Premiere valeur valide du groupe, propagee vers l'avant seulement."""
    s = pd.Series(np.where(valid, x, np.nan))
    return s.groupby(pd.Series(g)).transform("first").to_numpy()


def _grp_cum(x: np.ndarray, g: np.ndarray, how: str) -> np.ndarray:
    s = pd.Series(x).groupby(pd.Series(g))
    return getattr(s, how)().to_numpy()


def _rolling(x: np.ndarray, n: int, how: str, minp=None) -> np.ndarray:
    """`copy=True` : pandas peut rendre une vue en LECTURE SEULE, et plusieurs
    signaux ecrivent ensuite dans le resultat (masquage des n premieres cases)."""
    r = pd.Series(x).rolling(n, min_periods=minp or n)
    return np.asarray(getattr(r, how)().to_numpy(), dtype=float).copy()


def _ema(x: np.ndarray, n: int) -> np.ndarray:
    return pd.Series(x).ewm(span=n, adjust=False, min_periods=n).mean().to_numpy()


def _rsi(c: np.ndarray, n: int) -> np.ndarray:
    d = np.diff(c, prepend=c[0])
    up = pd.Series(np.clip(d, 0, None)).ewm(alpha=1.0 / n, adjust=False,
                                            min_periods=n).mean().to_numpy()
    dn = pd.Series(-np.clip(d, None, 0)).ewm(alpha=1.0 / n, adjust=False,
                                             min_periods=n).mean().to_numpy()
    out = np.full(c.shape, np.nan)
    ok = dn > 0
    out[ok] = 100.0 - 100.0 / (1.0 + up[ok] / dn[ok])
    out[np.isfinite(dn) & ~ok] = 100.0
    return out


def _safe(num: np.ndarray, den: np.ndarray) -> np.ndarray:
    den = np.where(np.abs(den) < 1e-12, np.nan, den)
    return num / den


# ============================================================ FAMILLE 1
# Intraday time-series momentum & breakout
def f_tsmom(b, n: int, **_):
    """Momentum normalise : somme des n derniers log-rendements / (ATR/close * sqrt(n))."""
    lr = b.logret()
    cum = _rolling(np.nan_to_num(lr, nan=0.0), n, "sum")
    cum[:n] = np.nan
    return _safe(cum, b.vol_unit() * np.sqrt(n))


def f_donchian_pos(b, n: int, **_):
    """Position dans le canal de Donchian, recentree : (C - LL)/(HH - LL) - 0.5."""
    hh = _rolling(b.h, n, "max")
    ll = _rolling(b.l, n, "min")
    return _safe(b.c - ll, hh - ll) - 0.5


def f_session_move(b, session: str, atr_period: int, **_):
    """(Close - Open de la session en cours) / ATR(p). Nul hors session."""
    ins, day, _ = session_mask(b, session)
    op = _grp_first(b.o, day, ins)
    out = _safe(b.c - op, b.atr(atr_period))
    return np.where(ins, out, np.nan)


def f_orb_break(b, session: str, orb_bars: int, atr_period: int, **_):
    """Cassure de l'Opening Range : distance signee au bord franchi, en ATR.

    L'OR est le haut/bas des `orb_bars` PREMIERES barres de la session ; le
    signal n'existe qu'apres, donc il ne peut pas contenir sa propre fenetre.
    """
    ins, day, _ = session_mask(b, session)
    g = pd.Series(np.where(ins, day, -1))
    idx = g.groupby(g).cumcount().to_numpy()
    early = ins & (idx < orb_bars)
    hi = pd.Series(np.where(early, b.h, -np.inf)).groupby(g).cummax().to_numpy()
    lo = pd.Series(np.where(early, b.l, np.inf)).groupby(g).cummin().to_numpy()
    a = b.atr(atr_period)
    up = _safe(b.c - hi, a)
    dn = _safe(b.c - lo, a)
    out = np.where(b.c > hi, up, np.where(b.c < lo, dn, 0.0))
    return np.where(ins & (idx >= orb_bars) & np.isfinite(hi) & np.isfinite(lo),
                    out, np.nan)


def f_range_expansion(b, n: int, **_):
    """Expansion signee : (C - C[-n]) / (moyenne des n vrais ranges)."""
    tr = b.atr(n)
    prev = np.concatenate([np.full(n, np.nan), b.c[:-n]]) if n < len(b) else np.full(len(b), np.nan)
    return _safe(b.c - prev, tr * np.sqrt(n))


# ============================================================ FAMILLE 2
# Mean reversion aux extremes statistiques
def f_vwap_z(b, session: str, atr_period: int, **_):
    """Distance au VWAP ancre a l'ouverture de session, en ATR. Signe de reversion."""
    ins, day, _ = session_mask(b, session)
    tp = (b.h + b.l + b.c) / 3.0
    v = np.where(ins, np.maximum(b.v, 1.0), 0.0)
    g = pd.Series(np.where(ins, day, -1))
    num = pd.Series(tp * v).groupby(g).cumsum().to_numpy()
    den = pd.Series(v).groupby(g).cumsum().to_numpy()
    vwap = _safe(num, den)
    return np.where(ins, -_safe(b.c - vwap, b.atr(atr_period)), np.nan)


def f_boll_z(b, n: int, **_):
    """-(C - EMA(n)) / ecart-type(n) : bande de Bollinger a base EMA."""
    m = _ema(b.c, n)
    s = _rolling(b.c, n, "std")
    return -_safe(b.c - m, s)


def f_atr_band_z(b, n: int, atr_period: int, **_):
    """-(C - EMA(n)) / ATR(p) : la meme deviation, echelle ATR."""
    return -_safe(b.c - _ema(b.c, n), b.atr(atr_period))


def f_ibs(b, n: int, **_):
    """Internal Bar Strength moyen sur n barres, recentre : -(IBS - 0.5)."""
    ibs = _safe(b.c - b.l, b.h - b.l)
    v = ibs if n == 1 else _rolling(ibs, n, "mean")
    return -(v - 0.5)


def f_rsi_dev(b, n: int, **_):
    """-(RSI(n) - 50)/50."""
    return -(_rsi(b.c, n) - 50.0) / 50.0


def f_ret_zscore(b, n: int, **_):
    """-z-score du rendement cumule sur n barres, contre sa propre histoire (250n)."""
    lr = np.nan_to_num(b.logret(), nan=0.0)
    cum = _rolling(lr, n, "sum")
    w = max(50, 20 * n)
    mu = _rolling(cum, w, "mean", minp=w // 2)
    sd = _rolling(cum, w, "std", minp=w // 2)
    return -_safe(cum - mu, sd)


# ============================================================ FAMILLE 3
# Microstructure / saisonnalite de session
def f_prior_session_ret(b, session: str, atr_period: int, **_):
    """Rendement de la session PRECEDENTE, en ATR, lisible pendant la session en cours."""
    ins, day, _ = session_mask(b, session)
    op = pd.Series(np.where(ins, b.o, np.nan)).groupby(pd.Series(day)).first()
    cl = pd.Series(np.where(ins, b.c, np.nan)).groupby(pd.Series(day)).last()
    # rendement de la session du jour, puis decalage d'un JOUR local : la barre
    # de la session en cours ne lit donc que la session DEJA CLOSE.
    prev = ((cl - op) / pd.Series(b.atr(atr_period)).groupby(pd.Series(day)).last()).shift(1)
    return np.where(ins, pd.Series(day).map(prev).to_numpy(), np.nan)


def f_overnight_gap(b, session: str, atr_period: int, **_):
    """Gap d'ouverture de session : (Open_session - Close_session_precedente)/ATR."""
    ins, day, _ = session_mask(b, session)
    op = pd.Series(np.where(ins, b.o, np.nan)).groupby(pd.Series(day)).first()
    cl = pd.Series(np.where(ins, b.c, np.nan)).groupby(pd.Series(day)).last()
    gap = (op - cl.shift(1))
    mapped = pd.Series(day).map(gap).to_numpy()
    return np.where(ins, _safe(mapped, b.atr(atr_period)), np.nan)


def f_fix_window(b, window_min: int, atr_period: int, **_):
    """Signal actif seulement autour du fixing de 16h Londres : derive recente / ATR."""
    tz, fh, fm = LONDON_FIX
    mins, _day = _clock(b, tz)
    target = fh * 60 + fm
    near = np.abs(mins - target) <= window_min
    n = 4
    prev = np.concatenate([np.full(n, np.nan), b.c[:-n]])
    return np.where(near, _safe(b.c - prev, b.atr(atr_period)), np.nan)


def f_tod_volume_z(b, **_):
    """Volume tick relatif a la moyenne EXPANSIVE du meme creneau horaire.

    La moyenne est expansive (donc n'utilise que le passe) : une moyenne pleine
    par creneau serait une fuite parfaitement invisible dans le resultat.
    """
    slot = np.asarray(b.t.hour) * 60 + np.asarray(b.t.minute)
    s = pd.Series(np.maximum(b.v, 1.0))
    g = pd.Series(slot)
    mu = s.groupby(g).transform(lambda x: x.shift(1).expanding(20).mean()).to_numpy()
    sd = s.groupby(g).transform(lambda x: x.shift(1).expanding(20).std()).to_numpy()
    return _safe(s.to_numpy() - mu, sd)


def f_asia_range_pos(b, **_):
    """Position dans le range asiatique, lue a Londres : (C - milieu)/ (range/2)."""
    ins_a, day_a, _ = session_mask(b, "ASIA")
    hi = pd.Series(np.where(ins_a, b.h, np.nan)).groupby(pd.Series(day_a)).max()
    lo = pd.Series(np.where(ins_a, b.l, np.nan)).groupby(pd.Series(day_a)).min()
    mid = (hi + lo) / 2.0
    half = (hi - lo) / 2.0
    ins_l, day_l, _ = session_mask(b, "LONDON")
    m = pd.Series(day_l).map(mid).to_numpy()
    hf = pd.Series(day_l).map(half).to_numpy()
    return np.where(ins_l, _safe(b.c - m, hf), np.nan)


def f_turn_of_month(b, days: int, **_):
    """Fenetre de fin/debut de mois : +1 dans la fenetre, 0 sinon (anomalie de flux)."""
    dom = np.asarray(b.t.day)
    dim = np.asarray(b.t.days_in_month)
    return ((dom > dim - days) | (dom <= days)).astype(float)


# ============================================================ FAMILLE 4
# Cross-asset & lead-lag
def f_leadlag_mom(b, n: int, driver: np.ndarray, **_):
    """Momentum du MENEUR sur n barres, normalise par sa propre volatilite."""
    lr = np.concatenate([[np.nan], np.diff(np.log(driver))])
    cum = _rolling(np.nan_to_num(lr, nan=0.0), n, "sum")
    sd = _rolling(lr, max(50, 10 * n), "std", minp=25)
    cum[:n] = np.nan
    return _safe(cum, sd * np.sqrt(n))


def f_resid_rev(b, n: int, beta_win: int, driver: np.ndarray, **_):
    """-residu de la regression glissante cible ~ meneur : reversion de l'ecart.

    Beta estime sur les `beta_win` barres PRECEDENTES (covariance / variance
    glissantes), residu evalue sur le rendement cumule a n barres. Aucun
    parametre n'est estime sur la fenetre qu'il explique.
    """
    ry = np.nan_to_num(b.logret(), nan=0.0)
    rx = np.nan_to_num(np.concatenate([[np.nan], np.diff(np.log(driver))]), nan=0.0)
    sy, sx = pd.Series(ry), pd.Series(rx)
    cov = sy.rolling(beta_win).cov(sx).shift(1).to_numpy()
    var = sx.rolling(beta_win).var().shift(1).to_numpy()
    beta = _safe(cov, var)
    cy = _rolling(ry, n, "sum")
    cx = _rolling(rx, n, "sum")
    resid = cy - beta * cx
    sd = _rolling(resid, max(50, 20 * n), "std", minp=25)
    return -_safe(resid, sd)


# ============================================================ FAMILLE 5
# Volatilite & skewness dynamique
def f_rv_ratio(b, n: int, mult: int, **_):
    """log( RV(n) / RV(n*mult) ) : expansion/compression de volatilite."""
    lr = b.logret()
    a = _rolling(lr, n, "std")
    c = _rolling(lr, n * mult, "std")
    r = _safe(a, c)
    return np.log(np.where(r > 0, r, np.nan))


def f_atr_ratio(b, n: int, mult: int, **_):
    a = b.atr(n)
    c = b.atr(n * mult)
    r = _safe(a, c)
    return np.log(np.where(r > 0, r, np.nan))


def f_skew(b, n: int, **_):
    """Asymetrie de l'echantillon des n derniers rendements."""
    return pd.Series(b.logret()).rolling(n).skew().to_numpy()


def f_vol_of_vol(b, n: int, **_):
    """Ecart-type de l'ATR/close sur n barres, rapporte a son niveau."""
    vu = b.vol_unit()
    return _safe(_rolling(vu, n, "std"), _rolling(vu, n, "mean"))


def f_intraday_overnight_rv(b, **_):
    """log( RV de la session NY / RV hors session ), lu pendant la session NY."""
    ins, day, _ = session_mask(b, "NY")
    lr2 = np.square(np.nan_to_num(b.logret(), nan=0.0))
    d = pd.Series(day)
    inn = pd.Series(np.where(ins, lr2, np.nan)).groupby(d).mean()
    out = pd.Series(np.where(~ins, lr2, np.nan)).groupby(d).mean()
    ratio = np.log((inn.shift(1) + 1e-18) / (out.shift(1) + 1e-18))
    return np.where(ins, pd.Series(day).map(ratio).to_numpy(), np.nan)


# ------------------------------------------------------------------ registre
BUILDERS = {
    "tsmom": f_tsmom, "donchian_pos": f_donchian_pos,
    "session_move": f_session_move, "orb_break": f_orb_break,
    "range_expansion": f_range_expansion,
    "vwap_z": f_vwap_z, "boll_z": f_boll_z, "atr_band_z": f_atr_band_z,
    "ibs": f_ibs, "rsi_dev": f_rsi_dev, "ret_zscore": f_ret_zscore,
    "prior_session_ret": f_prior_session_ret, "overnight_gap": f_overnight_gap,
    "fix_window": f_fix_window, "tod_volume_z": f_tod_volume_z,
    "asia_range_pos": f_asia_range_pos, "turn_of_month": f_turn_of_month,
    "leadlag_mom": f_leadlag_mom, "resid_rev": f_resid_rev,
    "rv_ratio": f_rv_ratio, "atr_ratio": f_atr_ratio, "skew": f_skew,
    "vol_of_vol": f_vol_of_vol, "intraday_overnight_rv": f_intraday_overnight_rv,
}

FAMILY_OF = {
    "tsmom": "intraday_momentum_breakout", "donchian_pos": "intraday_momentum_breakout",
    "session_move": "intraday_momentum_breakout", "orb_break": "intraday_momentum_breakout",
    "range_expansion": "intraday_momentum_breakout",
    "vwap_z": "mean_reversion_extreme", "boll_z": "mean_reversion_extreme",
    "atr_band_z": "mean_reversion_extreme", "ibs": "mean_reversion_extreme",
    "rsi_dev": "mean_reversion_extreme", "ret_zscore": "mean_reversion_extreme",
    "prior_session_ret": "microstructure_session_seasonality",
    "overnight_gap": "microstructure_session_seasonality",
    "fix_window": "microstructure_session_seasonality",
    "tod_volume_z": "microstructure_session_seasonality",
    "asia_range_pos": "microstructure_session_seasonality",
    "turn_of_month": "microstructure_session_seasonality",
    "leadlag_mom": "cross_asset_lead_lag", "resid_rev": "cross_asset_lead_lag",
    "rv_ratio": "volatility_skew_dynamics", "atr_ratio": "volatility_skew_dynamics",
    "skew": "volatility_skew_dynamics", "vol_of_vol": "volatility_skew_dynamics",
    "intraday_overnight_rv": "volatility_skew_dynamics",
}

# Signe PRE-ENREGISTRE par le mecanisme. La porte du mandat porte sur |IC|,
# donc elle ne l'utilise pas ; il est mesure quand meme, parce qu'un facteur
# qui ressort au signe oppose n'a pas "trouve le contraire", il a REFUTE son
# mecanisme, et confondre les deux est un degre de liberte cache.
SIGN_PRIOR = {
    "tsmom": +1, "donchian_pos": +1, "session_move": +1, "orb_break": +1,
    "range_expansion": +1,
    "vwap_z": +1, "boll_z": +1, "atr_band_z": +1, "ibs": +1, "rsi_dev": +1,
    "ret_zscore": +1,
    "prior_session_ret": +1, "overnight_gap": -1, "fix_window": -1,
    "tod_volume_z": +1, "asia_range_pos": +1, "turn_of_month": +1,
    "leadlag_mom": +1, "resid_rev": +1,
    "rv_ratio": -1, "atr_ratio": -1, "skew": -1, "vol_of_vol": -1,
    "intraday_overnight_rv": -1,
}

FORMULA = {
    "tsmom": "S_t = (sum_{i=0}^{n-1} log(C_{t-i}/C_{t-i-1})) / ((ATR14_t/C_t) * sqrt(n))",
    "donchian_pos": "S_t = (C_t - min(L_{t-n+1..t})) / (max(H_{t-n+1..t}) - min(L_{t-n+1..t})) - 0.5",
    "session_move": "S_t = (C_t - O_session(t)) / ATR_p(t), defini seulement pendant la session",
    "orb_break": "OR = [max H, min L] des `orb_bars` premieres barres de session ; "
                 "S_t = (C_t - OR_high)/ATR_p si C_t > OR_high, (C_t - OR_low)/ATR_p si C_t < OR_low, 0 sinon",
    "range_expansion": "S_t = (C_t - C_{t-n}) / (ATR_n(t) * sqrt(n))",
    "vwap_z": "VWAP_t = sum(TP*V)/sum(V) ancre a l'ouverture de session ; S_t = -(C_t - VWAP_t)/ATR_p(t)",
    "boll_z": "S_t = -(C_t - EMA_n(C)_t) / stdev_n(C)_t",
    "atr_band_z": "S_t = -(C_t - EMA_n(C)_t) / ATR_p(t)",
    "ibs": "IBS_t = (C_t - L_t)/(H_t - L_t) ; S_t = -(moyenne_n(IBS) - 0.5)",
    "rsi_dev": "S_t = -(RSI_n(t) - 50)/50",
    "ret_zscore": "r_n(t) = sum des n derniers log-rendements ; S_t = -(r_n - mu_w(r_n))/sigma_w(r_n), w = max(50, 20n)",
    "prior_session_ret": "S_t = (C_fin - O_debut) de la session PRECEDENTE / ATR_p(t)",
    "overnight_gap": "S_t = -(O_session(t) - C_session(t-1)) / ATR_p(t)",
    "fix_window": "S_t = -(C_t - C_{t-4}) / ATR_p(t), defini seulement a +/- `window_min` du fixing 16h Londres",
    "tod_volume_z": "S_t = (V_t - mu_expansive(V | meme creneau horaire, passe seul)) / sigma_expansive",
    "asia_range_pos": "S_t = (C_t - milieu du range asiatique du jour) / (demi-range), lu pendant Londres",
    "turn_of_month": "S_t = 1 si jour du mois <= d ou > (jours_du_mois - d), 0 sinon",
    "leadlag_mom": "S_t = (somme des n derniers log-rendements du MENEUR) / (sigma_meneur * sqrt(n))",
    "resid_rev": "beta_t = cov_w(r_cible, r_meneur)/var_w(r_meneur) estime sur [t-w, t-1] ; "
                 "e_t = r_n(cible) - beta_t * r_n(meneur) ; S_t = -e_t/sigma(e)",
    "rv_ratio": "S_t = -log( stdev_n(logret) / stdev_{n*m}(logret) )",
    "atr_ratio": "S_t = -log( ATR_n(t) / ATR_{n*m}(t) )",
    "skew": "S_t = asymetrie d'echantillon des n derniers log-rendements (PAS de signe moins : `f_skew` rend l'asymetrie brute, le prior de signe est porte a part par SIGN_PRIOR)",
    "vol_of_vol": "S_t = -stdev_n(ATR14/C) / moyenne_n(ATR14/C)",
    "intraday_overnight_rv": "S_t = -log( RV_session_NY(j-1) / RV_hors_session(j-1) ), lu pendant la session NY",
}


# ------------------------------------------------------------------ grilles
def _p(**kw):
    return kw


PARAM_GRID = {
    "tsmom": [_p(n=n) for n in (6, 12, 24, 48, 96)],
    "donchian_pos": [_p(n=n) for n in (12, 24, 48, 96)],
    "session_move": [_p(session=s, atr_period=14) for s in ("NY", "LONDON", "ASIA")],
    "orb_break": [_p(session=s, orb_bars=ob, atr_period=14)
                  for s in ("NY", "LONDON") for ob in (3, 6)],
    "range_expansion": [_p(n=n) for n in (5, 10, 20)],
    "vwap_z": [_p(session=s, atr_period=14) for s in ("NY", "LONDON")],
    "boll_z": [_p(n=n) for n in (20, 50, 100)],
    "atr_band_z": [_p(n=n, atr_period=14) for n in (20, 50, 100)],
    "ibs": [_p(n=n) for n in (1, 2, 3)],
    "rsi_dev": [_p(n=n) for n in (2, 7, 14)],
    "ret_zscore": [_p(n=n) for n in (3, 6, 12, 24)],
    "prior_session_ret": [_p(session=s, atr_period=14) for s in ("NY", "ASIA")],
    "overnight_gap": [_p(session=s, atr_period=14) for s in ("NY", "LONDON")],
    "fix_window": [_p(window_min=w, atr_period=14) for w in (30, 60)],
    "tod_volume_z": [_p(n=1)],
    "asia_range_pos": [_p(atr_period=14)],
    "turn_of_month": [_p(days=d) for d in (2, 3)],
    "leadlag_mom": [_p(n=n) for n in (6, 12, 24, 48)],
    "resid_rev": [_p(n=n, beta_win=w) for n in (6, 12, 24) for w in (250, 500)],
    "rv_ratio": [_p(n=n, mult=4) for n in (10, 20, 50)],
    "atr_ratio": [_p(n=n, mult=4) for n in (10, 20)],
    "skew": [_p(n=n) for n in (20, 50, 100)],
    "vol_of_vol": [_p(n=n) for n in (20, 50)],
    "intraday_overnight_rv": [_p(atr_period=14)],
}

CROSS_TYPES = {"leadlag_mom", "resid_rev"}

# Meneurs pre-enregistres par mecanisme economique, PAS balayes.
# Le mandat cite US10Y : aucun CFD obligataire n'est servi par ce terminal, la
# substitution est donc explicite (USDJPY comme relais taux/risque) et non
# silencieuse.
DRIVERS = {
    "EURUSD": ["USDIDX"], "GBPUSD": ["USDIDX"], "AUDUSD": ["USDIDX", "XAUUSD"],
    "NZDUSD": ["USDIDX", "AUDUSD"], "USDCAD": ["USDIDX", "USOIL"],
    "USDCHF": ["USDIDX", "XAUUSD"], "USDJPY": ["USDIDX", "US500"],
    "EURGBP": ["EURUSD"], "EURJPY": ["USDJPY", "US500"], "GBPJPY": ["USDJPY", "US500"],
    "US100": ["US500"], "US30": ["US500"], "GER40": ["US500"],
    "UK100": ["GER40", "US500"], "US500": ["US100"],
    "XAUUSD": ["USDIDX", "XAGUSD"], "XAGUSD": ["XAUUSD"], "USOIL": ["USDIDX"],
    "BTCUSD": ["US100"], "ETHUSD": ["BTCUSD"],
}


def instantiate(sym: str) -> list[dict]:
    """Toutes les definitions de signal applicables a un symbole."""
    out = []
    for typ, grid in PARAM_GRID.items():
        for params in grid:
            if typ in CROSS_TYPES:
                for drv in DRIVERS.get(sym, []):
                    p = dict(params, driver=drv)
                    out.append(dict(type=typ, family=FAMILY_OF[typ],
                                    sign_prior=SIGN_PRIOR[typ], params=p))
            else:
                out.append(dict(type=typ, family=FAMILY_OF[typ],
                                sign_prior=SIGN_PRIOR[typ], params=dict(params)))
    return out


def spec_key(spec: dict) -> str:
    ps = ",".join(f"{k}={spec['params'][k]}" for k in sorted(spec["params"]))
    return f"{spec['type']}({ps})"


def compute(bars, spec: dict, driver_prices: np.ndarray | None = None) -> np.ndarray:
    fn = BUILDERS[spec["type"]]
    kw = dict(spec["params"])
    if spec["type"] in CROSS_TYPES:
        if driver_prices is None:
            return np.full(len(bars), np.nan)
        kw.pop("driver", None)
        kw["driver"] = driver_prices
    x = np.array(fn(bars, **kw), dtype=float, copy=True)
    x[~np.isfinite(x)] = np.nan
    return x
