"""Calendrier des séances US ÉCOURTÉES, pour les sleeves intraday sur indices.

LE PROBLÈME QU'IL RÉSOUT
------------------------
Les sleeves intraday (brique 1, HMASTO, TLF) se mettent à plat quand l'horloge atteint
``session_close`` (15:55 ET). Sur une séance écourtée le flux s'arrête à 13:00 : à 15:55
le marché est **déjà fermé**, la clôture est refusée (``MarketClosed``) et la position
est **portée jusqu'à la réouverture**. Le backtest, lui, sort à la dernière barre. Mesuré
sur la brique 1 : 6 trades sur 830 (0,7 %), et HMASTO et TLF ont la même exposition.

CE N'EST PAS UN CALENDRIER NYSE, ET C'EST LE POINT
--------------------------------------------------
Ces instruments sont des **CFD Pepperstone sur indice cash**, pas le NYSE. Extraction de
8 ans de M1 : le flux trade une **séance partielle 09:30→13:00 les jours fériés US** où
le NYSE est totalement fermé (MLK, Presidents' Day, Memorial, Juneteenth, 4 juillet,
Labor Day, Thanksgiving), en plus des demi-séances classiques (3 juillet, lendemain de
Thanksgiving, 24 décembre) et du 31 décembre (~14:55). Un calendrier « NYSE fermé =
pas de séance » aurait donc été faux dans les deux sens.

Tout est déduit de la DATE — aucune liste à maintenir, aucune donnée externe. Les règles
sont validées contre le flux réel par ``validate_against_feed()`` et par ``verify.py``.

CONSERVATISME ASSUMÉ : on rend 12:55 pour toutes les séances à 13:00-13:15, soit la même
marge de 5 minutes que le 15:55 des séances pleines (clôture cash 16:00). Sortir 5 à 20
minutes trop tôt coûte quelques points ; rester coincé long sur un week-end de Noël coûte
un gap.
"""
from __future__ import annotations

import datetime as _dt
from functools import lru_cache

ET = "America/New_York"

# heure d'aplat sur une séance écourtée, en minutes depuis minuit ET
EARLY_FLAT = 12 * 60 + 55        # séances 13:00 / 13:15  -> plat à 12:55
NYE_FLAT = 14 * 60 + 50          # 31 décembre (~14:55)   -> plat à 14:50


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> _dt.date:
    """n-ième `weekday` (0=lundi) du mois. n<0 compte depuis la fin."""
    if n > 0:
        d = _dt.date(year, month, 1)
        d += _dt.timedelta(days=(weekday - d.weekday()) % 7)
        return d + _dt.timedelta(weeks=n - 1)
    nxt = _dt.date(year + (month == 12), month % 12 + 1, 1)
    d = nxt - _dt.timedelta(days=1)
    d -= _dt.timedelta(days=(d.weekday() - weekday) % 7)
    return d + _dt.timedelta(weeks=n + 1)


def _observed(d: _dt.date) -> _dt.date:
    """Report d'un férié tombant un week-end (règle US : samedi -> vendredi, dimanche -> lundi)."""
    if d.weekday() == 5:
        return d - _dt.timedelta(days=1)
    if d.weekday() == 6:
        return d + _dt.timedelta(days=1)
    return d


def _easter(year: int) -> _dt.date:
    """Computus grégorien — nécessaire au seul Vendredi saint."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    g = (8 * b + 13) // 25
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 19 * l) // 433
    mo, day = divmod(h + l - 7 * m + 90, 25)
    day = (h + l - 7 * m + 33 * mo + 19) % 32
    return _dt.date(year, mo, day)


@lru_cache(maxsize=64)
def us_holidays(year: int) -> frozenset:
    """Fériés du marché US. Le flux CFD y trade une séance PARTIELLE 09:30-13:00."""
    h = {
        _observed(_dt.date(year, 1, 1)),                       # New Year's Day
        _nth_weekday(year, 1, 0, 3),                           # MLK
        _nth_weekday(year, 2, 0, 3),                           # Presidents' Day
        _easter(year) - _dt.timedelta(days=2),                 # Good Friday
        _nth_weekday(year, 5, 0, -1),                          # Memorial Day
        _observed(_dt.date(year, 7, 4)),                       # Independence Day
        _nth_weekday(year, 9, 0, 1),                           # Labor Day
        _nth_weekday(year, 11, 3, 4),                          # Thanksgiving
        _observed(_dt.date(year, 12, 25)),                     # Christmas
    }
    if year >= 2022:                                           # Juneteenth, férié depuis 2021/22
        h.add(_observed(_dt.date(year, 6, 19)))
    return frozenset(h)


@lru_cache(maxsize=64)
def early_closes(year: int) -> frozenset:
    """Demi-séances classiques : veille du 4 juillet, lendemain de Thanksgiving, 24 décembre."""
    out = set()
    jul4 = _dt.date(year, 7, 4)
    if jul4.weekday() < 5:                       # pas de demi-séance si le 4 tombe le week-end
        d = jul4 - _dt.timedelta(days=1)
        if d.weekday() < 5:
            out.add(d)
    out.add(_nth_weekday(year, 11, 3, 4) + _dt.timedelta(days=1))     # Black Friday
    dec24 = _dt.date(year, 12, 24)
    if dec24.weekday() < 5:
        out.add(dec24)
    return frozenset(out)


def flat_minute(day: _dt.date, normal_flat_min: int) -> int:
    """Minute d'aplat EFFECTIVE (depuis minuit ET) pour ``day``.

    Rend ``normal_flat_min`` sur une séance pleine, une valeur plus PRÉCOCE sinon.
    Jamais plus tardive : ce calendrier ne peut qu'avancer la sortie.
    """
    if day.weekday() >= 5:
        return normal_flat_min
    if day in us_holidays(day.year) or day in early_closes(day.year):
        return min(normal_flat_min, EARLY_FLAT)
    if (day.month, day.day) == (12, 31):
        return min(normal_flat_min, NYE_FLAT)
    return normal_flat_min


def is_short_session(day: _dt.date) -> bool:
    return flat_minute(day, 24 * 60) < 24 * 60


# ---------------------------------------------------------------------------
def validate_against_feed(symbol: str = "NAS100", open_min: int = 9 * 60 + 30,
                          normal_flat: int = 15 * 60 + 55, verbose: bool = True):
    """Confronte les règles au FLUX RÉEL : le calendrier est-il sûr, et suffisant ?

    Deux fautes possibles, et elles ne se valent pas :
      * DANGEREUSE — une séance écourtée que le calendrier ignore : le driver attend
        15:55, le marché est déjà clos, la position part à la nuit ;
      * bénigne — un jour marqué écourté qui ne l'était pas : on sort quelques heures
        trop tôt, ce qui coûte du rendement mais aucun risque de gap.
    """
    import numpy as np
    import pandas as pd
    from edgelab.intraday.orb import load_bars

    d = load_bars(symbol, "M1")
    loc = d.index.tz_convert(ET)
    mins = (loc.hour * 60 + loc.minute).to_numpy()
    day = loc.tz_localize(None).normalize()
    m = (mins >= open_min) & (mins <= normal_flat) & (np.asarray(loc.dayofweek) < 5)
    g = pd.DataFrame({"d": day[m], "m": mins[m]}).groupby("d")["m"].agg(["max", "count"])
    g = g[g["count"] >= 30]                      # ignore les trous de flux (< 30 barres)

    missed, spurious, ok_short = [], [], []
    for ts, row in g.iterrows():
        dd = ts.date()
        last, cal = int(row["max"]), flat_minute(ts.date(), normal_flat)
        short_feed = last < normal_flat - 5
        if short_feed and cal >= normal_flat:
            missed.append((dd, last))
        elif short_feed:
            ok_short.append((dd, last, cal))
        elif cal < normal_flat:
            spurious.append((dd, last, cal))
    if verbose:
        print(f"  CALENDRIER vs FLUX {symbol} : {len(g)} seances")
        print(f"    ecourtees vues par le calendrier   : {len(ok_short)}")
        print(f"    ecourtees MANQUEES (dangereux)     : {len(missed)}"
              + ("  " + ", ".join(f"{a} (fin {b//60:02d}:{b%60:02d})"
                                  for a, b in missed[:10]) if missed else ""))
        print(f"    marquees a tort (benin, sort tot)  : {len(spurious)}"
              + ("  " + ", ".join(str(a) for a, _, _ in spurious[:10]) if spurious else ""))
        for dd, last, cal in ok_short[:3]:
            print(f"      ex. {dd}: flux jusqu'a {last//60:02d}:{last%60:02d}, "
                  f"plat calendrier {cal//60:02d}:{cal%60:02d}")
    return missed, spurious, ok_short


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    bad = 0
    for sym in ("NAS100", "US500"):
        missed, _, _ = validate_against_feed(sym)
        bad += len(missed)
    print(f"\n{'OK' if bad == 0 else 'INCOMPLET'} : {bad} seance(s) ecourtee(s) non couverte(s)")
