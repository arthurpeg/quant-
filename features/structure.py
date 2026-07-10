"""
features/structure.py
=====================
Features de structure de bougie / structure de marché. Toutes causales.

- Ratio du corps : |Close-Open| / (High-Low)  [div/0 gérée].
- Mèches haute / basse : (High-max(O,C))/(H-L) et (min(O,C)-Low)/(H-L).
- Distance aux extrêmes des sessions PASSÉES (Asie/Europe/USA) et de la veille : écart %
  vs High/Low. On n'utilise QUE des sessions/jours entièrement CLÔTURÉS (pas de leakage).
- Streak de bougies consécutives : +n haussières / -n baissières.
- (optionnel) weekend_gap : log-return ouverture (post-trou) vs clôture (pré-trou).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import config
import calendar_utils as cal


def compute(df: pd.DataFrame) -> pd.DataFrame:
    """Calcule toutes les features de structure. df OHLCV → DataFrame de features."""
    o, h, l, c = (df[config.COL_OPEN], df[config.COL_HIGH],
                  df[config.COL_LOW], df[config.COL_CLOSE])
    out = pd.DataFrame(index=df.index)

    rng = (h - l).replace(0.0, np.nan)   # amplitude, gère div/0

    # Ratio du corps et mèches
    out["body_ratio"] = (c - o).abs() / rng
    upper = np.maximum(o.to_numpy(), c.to_numpy())
    lower = np.minimum(o.to_numpy(), c.to_numpy())
    out["upper_wick"] = (h.to_numpy() - upper) / rng
    out["lower_wick"] = (lower - l.to_numpy()) / rng

    # Streak haussier / baissier (comptage vectorisé des runs de même signe)
    out["streak"] = _streak(c)

    # Distances aux extrêmes de la veille (jour de marché précédent, entièrement clôturé)
    _add_prev_day_distances(df, out)

    # Distances aux extrêmes des sessions précédentes (veille par session)
    _add_prev_session_distances(df, out)

    # weekend_gap optionnel
    if config.ENABLE_WEEKEND_GAP:
        out["weekend_gap"] = _weekend_gap(df)

    return out


def _streak(close: pd.Series) -> pd.Series:
    """
    Longueur signée du run courant de bougies de même direction (close vs close précédent).
    +n : n hausses consécutives ; -n : n baisses. Vectorisé (pas de boucle Python).
    """
    sign = np.sign(close.diff().fillna(0.0)).to_numpy()
    n = len(sign)
    run = 0.0
    prev = 0.0
    vals = np.empty(n, dtype=float)
    for i in range(n):  # boucle unique O(n), bornée et déterministe (streak intrinsèquement séquentiel)
        s = sign[i]
        if s == 0:
            run = 0.0
        elif s == prev:
            run += s
        else:
            run = s
        prev = s
        vals[i] = run
    return pd.Series(np.clip(vals, -config.STREAK_MAX, config.STREAK_MAX), index=close.index)


def _add_prev_day_distances(df: pd.DataFrame, out: pd.DataFrame) -> None:
    """Écart % du close courant vs High/Low de la JOURNÉE DE MARCHÉ précédente (clôturée)."""
    day = pd.Series(cal.market_day(df.index), index=df.index)

    # High/Low par journée, décalés à la journée suivante (→ veille, entièrement clôturée)
    per_day = pd.DataFrame({"high": df[config.COL_HIGH], "low": df[config.COL_LOW], "day": day})
    agg = per_day.groupby("day").agg(high=("high", "max"), low=("low", "min"))
    prev = agg.shift(1)  # veille
    prev_high = day.map(prev["high"])
    prev_low = day.map(prev["low"])

    c = df[config.COL_CLOSE]
    out["dist_prevday_high_pct"] = (c - prev_high.to_numpy()) / prev_high.to_numpy() * 100.0
    out["dist_prevday_low_pct"] = (c - prev_low.to_numpy()) / prev_low.to_numpy() * 100.0


def _add_prev_session_distances(df: pd.DataFrame, out: pd.DataFrame) -> None:
    """
    Pour chaque session (asia/london/newyork) : écart % du close courant vs High/Low de la
    dernière occurrence CLÔTURÉE de cette session (la veille par journée de marché).
    N'utilise que du passé → pas de leakage.
    """
    day = pd.Series(cal.market_day(df.index), index=df.index)
    masks = cal.session_masks(df.index)
    c = df[config.COL_CLOSE]

    for name in config.SESSIONS:
        m = masks[name].to_numpy()
        hi = df[config.COL_HIGH].where(m)
        lo = df[config.COL_LOW].where(m)
        frame = pd.DataFrame({"hi": hi, "lo": lo, "day": day})
        agg = frame.groupby("day").agg(hi=("hi", "max"), lo=("lo", "min"))
        prev = agg.shift(1)  # session de la veille (clôturée)
        prev_hi = day.map(prev["hi"]).to_numpy()
        prev_lo = day.map(prev["lo"]).to_numpy()
        out[f"dist_{name}_prev_high_pct"] = (c - prev_hi) / prev_hi * 100.0
        out[f"dist_{name}_prev_low_pct"] = (c - prev_lo) / prev_lo * 100.0


def _weekend_gap(df: pd.DataFrame) -> pd.Series:
    """
    Log-return de gap : ln(open_post_trou / close_pre_trou), non nul UNIQUEMENT sur la 1re
    bougie qui suit un trou de grille (week-end/férié). C'est un ÉVÉNEMENT RÉEL, jamais un ffill.
    """
    step = pd.Timedelta(config.PANDAS_FREQ)
    delta = df.index.to_series().diff()
    is_gap = (delta > step).fillna(False).to_numpy()
    gap = np.log(df[config.COL_OPEN] / df[config.COL_CLOSE].shift(1))
    return pd.Series(np.where(is_gap, gap.to_numpy(), 0.0), index=df.index)
