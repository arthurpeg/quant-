"""
calendar_utils.py
=================
Logique calendaire du marché : semaine forex (ouverture dimanche → clôture vendredi),
week-ends, jours fériés, pause de maintenance quotidienne, sessions (DST-aware), et
"journée de marché" pour les resets intra-session (VWAP, extrêmes de session).

Principe clé : la GRILLE DE MARCHÉ ne contient QUE des bougies réellement ouvertes.
Une fois le DataFrame réindexé sur cette grille, deux lignes consécutives sont deux
bougies de marché consécutives — le "timeout en bougies de marché" du labeling devient
alors un simple décalage de lignes (pas de week-end à enjamber).

Tout est en UTC en interne. Les sessions sont définies en heure locale et converties par
timestamp via zoneinfo → gère automatiquement les décalages d'heure d'été (DST).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import config


# ───────────────────────────────────────────────────────────────────────────
# Ouverture / fermeture du marché
# ───────────────────────────────────────────────────────────────────────────
def market_open_mask(index: pd.DatetimeIndex) -> np.ndarray:
    """
    Renvoie un masque booléen : True si la bougie horodatée `ts` est en séance ouverte.

    Fermé : week-end (vendredi ≥ WEEK_CLOSE_HOUR → dimanche < WEEK_OPEN_HOUR),
    jours fériés (dates complètes), et heures de maintenance quotidienne.
    """
    if index.tz is None:
        raise ValueError("L'index doit être tz-aware (UTC).")
    idx = index.tz_convert("UTC")

    dow = idx.dayofweek.to_numpy()          # Lundi=0 ... Dimanche=6
    hour = idx.hour.to_numpy()
    dates = idx.normalize()                 # minuit UTC de chaque bougie

    closed = np.zeros(len(idx), dtype=bool)

    # --- Week-end : de vendredi WEEK_CLOSE_HOUR à dimanche WEEK_OPEN_HOUR ---
    closed |= (dow == config.WEEK_CLOSE_DOW) & (hour >= config.WEEK_CLOSE_HOUR_UTC)  # ven. soir
    closed |= (dow == 5)                                                             # samedi entier
    closed |= (dow == config.WEEK_OPEN_DOW) & (hour < config.WEEK_OPEN_HOUR_UTC)     # dim. matin

    # --- Jours fériés (dates UTC complètes) ---
    if config.HOLIDAYS_UTC:
        holidays = pd.to_datetime(list(config.HOLIDAYS_UTC), utc=True).normalize()
        closed |= np.isin(dates.to_numpy(), holidays.to_numpy())

    # --- Maintenance quotidienne (~1h), trou légitime ---
    if config.DAILY_MAINTENANCE_HOURS_UTC:
        closed |= np.isin(hour, np.asarray(config.DAILY_MAINTENANCE_HOURS_UTC))

    return ~closed


def market_grid(start: pd.Timestamp, end: pd.Timestamp) -> pd.DatetimeIndex:
    """
    Construit la grille des bougies de marché (au TIMEFRAME config) entre start et end.
    N'inclut AUCUNE bougie de week-end / férié / maintenance : les trous restent des trous.
    """
    start = pd.Timestamp(start).tz_convert("UTC") if start.tz else pd.Timestamp(start, tz="UTC")
    end = pd.Timestamp(end).tz_convert("UTC") if end.tz else pd.Timestamp(end, tz="UTC")

    full = pd.date_range(start=start.floor(config.PANDAS_FREQ),
                         end=end.ceil(config.PANDAS_FREQ),
                         freq=config.PANDAS_FREQ, tz="UTC")
    return full[market_open_mask(full)]


# ───────────────────────────────────────────────────────────────────────────
# Journée de marché (pour resets intra-session : VWAP, extrêmes)
# ───────────────────────────────────────────────────────────────────────────
def market_day(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """
    Étiquette chaque bougie par sa "journée de marché" : une nouvelle journée commence au
    roll journalier DAILY_RESET_UTC (clôture NY). Les bougies à/au-delà du reset appartiennent
    à la journée suivante. Sert de clé de groupby pour VWAP et extrêmes de session.
    """
    idx = index.tz_convert("UTC")
    reset_h, reset_m = (int(x) for x in config.DAILY_RESET_UTC.split(":"))
    shifted = idx - pd.Timedelta(hours=reset_h, minutes=reset_m)
    return shifted.normalize()


# ───────────────────────────────────────────────────────────────────────────
# Sessions (DST-aware)
# ───────────────────────────────────────────────────────────────────────────
def session_masks(index: pd.DatetimeIndex) -> pd.DataFrame:
    """
    Renvoie un DataFrame booléen (colonnes = noms de sessions) indiquant, pour chaque
    bougie, si elle tombe dans la session. Les bornes sont en heure LOCALE et converties
    par timestamp → le DST est géré automatiquement par zoneinfo.

    Les sessions peuvent se chevaucher (Londres/NY) : plusieurs colonnes True possibles.
    Gère les sessions à cheval sur minuit (start > end).
    """
    idx = index.tz_convert("UTC")
    out = pd.DataFrame(index=index)

    for name, spec in config.SESSIONS.items():
        local = idx.tz_convert(spec.tz)
        lt = local.hour.to_numpy() + local.minute.to_numpy() / 60.0
        s_h, s_m = (int(x) for x in spec.start_local.split(":"))
        e_h, e_m = (int(x) for x in spec.end_local.split(":"))
        start = s_h + s_m / 60.0
        end = e_h + e_m / 60.0
        if start <= end:
            mask = (lt >= start) & (lt < end)
        else:  # session traversant minuit (ex : Sydney)
            mask = (lt >= start) | (lt < end)
        out[name] = mask
    return out


def primary_session(index: pd.DatetimeIndex) -> pd.Series:
    """
    Session 'principale' de chaque bougie (première session active dans l'ordre de config).
    'closed' si aucune. Utile pour un one-hot mutuellement exclusif ou du diagnostic.
    """
    masks = session_masks(index)
    result = pd.Series("closed", index=index, dtype=object)
    for name in reversed(list(config.SESSIONS.keys())):
        result = result.mask(masks[name].to_numpy(), name)
    return result
