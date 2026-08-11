"""Coût FTMO réel — commission + swap — appliqué trade par trade, en R.

POURQUOI CE FICHIER EXISTE
--------------------------
`books_report` publiait des courbes **brutes** de frais FTMO, avec un avertissement en
bas de page. C'est la mauvaise façon de traiter un coût de cette taille : sur la brique 3
le swap vaut **5,71 R/an contre 5,72 R/an de brut gagné depuis juillet 2022**, c'est-à-dire
qu'il l'annule exactement. Un chiffre brut n'est pas une approximation du net, c'est une
autre grandeur.

`scratchpad/ftmo_swaps.py` faisait déjà ce calcul, mais le rapport ne doit dépendre
d'aucun scratchpad (il se donne pour règle de ne se reconstruire que depuis les modules
canoniques). Les taux et la logique d'unités sont donc réimplémentés ici.

LES TAUX, VÉRIFIÉS EN DIRECT
----------------------------
Relevés sur le terminal **FTMO-Demo 1514234500** le 2026-08-10 par
`scratchpad/ftmo_verify_swaps.py`, en lecture seule :

  * crypto : ``swap_mode=5`` (INTEREST_CURRENT = % ANNUEL du prix, année bancaire 360 j),
    **long −30,00 et court −30,00**, triple le vendredi. Aucun côté gratuit ;
  * indices et or : ``swap_mode=1`` (points × taille du point). Point mesuré à **0,01**,
    ce qui confirme la déduction que le projet portait sans l'avoir relevée. Convertis au
    prix courant : US100 −7,52 %/an long et **+0,04 % court**, XAUUSD −7,65 / −1,24.

QUI PAIE QUOI
-------------
Seules les sleeves qui **portent la nuit** paient un swap. b1, HMASTO et TLF sont
intraday pures (100 % des trades ouverts et fermés le même jour), donc **zéro unité de
swap**, et les indices sont sans commission sur ce compte : elles conservent 100 % de
leur R. Le coût ne frappe que b2 (or), b3 (crypto) et b4 (IBS).

    coût_en_R = unités × taux_par_unité / stop_pct

Il est donc **invariant à la taille de position** — on ne le dilue pas en risquant moins.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

BANK_YEAR = 360.0

# commission FTMO, fraction du notionnel PAR CÔTÉ (confirmée par FTMO)
COMMISSION = {"NAS100": 0.0, "US500": 0.0, "XAUUSD": 0.000007,
              "BTCUSD": 0.000325, "ETHUSD": 0.000325}

# swap en % ANNUEL du prix. Mesuré le 2026-08-10 (cf. en-tête).
SWAP_ANNUAL_PCT = {
    ("BTCUSD", +1): 30.0, ("BTCUSD", -1): 30.0,
    ("ETHUSD", +1): 30.0, ("ETHUSD", -1): 30.0,
    ("NAS100", +1): 7.52, ("NAS100", -1): -0.04,     # court NÉGATIF = on est payé
    ("XAUUSD", +1): 7.65, ("XAUUSD", -1): 1.24,
}
# jour du triple swap : 4 = vendredi, 2 = mercredi (lundi = 0)
TRIPLE_DAY = {"BTCUSD": 4, "ETHUSD": 4, "NAS100": 4, "US500": 4, "XAUUSD": 2}


def swap_units(entry, exit_, triple_day: int) -> np.ndarray:
    """Unités de swap facturées entre ``entry`` et ``exit_``, coefficients MT5.

    Un rollover est facturé à la fin de chaque jour de semaine où la position est encore
    ouverte ; ``triple_day`` compte triple ; samedi et dimanche ne sont pas facturés (le
    jour triple les couvre). Contrôle : une semaine pleine donne 1+1+1+1+3 = 7 unités,
    soit une par nuit calendaire.

    ⚠️ Une sortie le JOUR de l'entrée vaut 0 unité — c'est ce qui rend les sleeves
    intraday gratuites, et c'est la ligne qu'il ne faut pas casser.
    """
    out = np.zeros(len(entry), dtype=float)
    for i, (a, b) in enumerate(zip(entry, exit_)):
        d0 = pd.Timestamp(a).tz_localize(None).normalize() if pd.Timestamp(a).tz \
            else pd.Timestamp(a).normalize()
        d1 = pd.Timestamp(b).tz_localize(None).normalize() if pd.Timestamp(b).tz \
            else pd.Timestamp(b).normalize()
        if (d1 - d0).days <= 0:
            continue
        days = pd.date_range(d0, d1 - pd.Timedelta(days=1), freq="D")
        wd = days.dayofweek.to_numpy()
        u = np.where(wd >= 5, 0.0, 1.0)
        u[wd == triple_day] = 3.0
        out[i] = u.sum()
    return out


def trade_cost_R(symbol: str, entry_time, exit_time, entry_px, sl_dist,
                 direction=None, sides: int = 2) -> np.ndarray:
    """Coût FTMO par trade, en R. ``sl_dist`` est 1R en PRIX.

    ``direction`` None -> sleeve bidirectionnelle : on prend la MOYENNE des deux côtés
    (c'est le cas de b3, dont le taux est de toute façon symétrique). Sinon on prend le
    côté effectivement porté — ce qui compte pour b2 et b4, long-only, qui paient le côté
    cher.
    """
    entry_px = np.asarray(entry_px, float)
    sl_dist = np.asarray(sl_dist, float)
    stop_pct = np.where(entry_px > 0, sl_dist / entry_px, np.nan)

    if direction is None:
        pct = 0.5 * (SWAP_ANNUAL_PCT[(symbol, +1)] + SWAP_ANNUAL_PCT[(symbol, -1)])
        rate = np.full(len(entry_px), pct)
    else:
        d = np.asarray(direction, int)
        rate = np.where(d > 0, SWAP_ANNUAL_PCT[(symbol, +1)],
                        SWAP_ANNUAL_PCT[(symbol, -1)])
    per_unit = rate / 100.0 / BANK_YEAR

    units = swap_units(entry_time, exit_time, TRIPLE_DAY[symbol])
    swap = units * per_unit / stop_pct
    comm = sides * COMMISSION[symbol] / stop_pct
    return np.nan_to_num(swap + comm, nan=0.0, posinf=0.0, neginf=0.0)


def daily_cost(exit_time, cost_R, idx: pd.DatetimeIndex) -> pd.Series:
    """Agrège un coût par trade sur l'index calendaire du rapport (jour de SORTIE)."""
    t = pd.DatetimeIndex(pd.to_datetime(exit_time))
    t = t.tz_convert("UTC") if t.tz is not None else t.tz_localize("UTC")
    s = pd.Series(np.asarray(cost_R, float), index=t.tz_localize(None).normalize())
    return s.groupby(level=0).sum().reindex(idx).fillna(0.0)
