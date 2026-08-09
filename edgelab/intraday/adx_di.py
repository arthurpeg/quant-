"""ADXDI — croisement DI/ADX en intraday, sleeve de forward-test (GER40 M15).

⚠️ LE NOM DU FICHIER SOURCE EST TROMPEUR ET IL FAUT LE DIRE UNE FOIS POUR TOUTES.
La regle vient de la condition d'entree de `ADX_System.mq4` (MQL4 Code Base, entree
8830), trouvee par la campagne intraday du 2026-08-09/10 sur 3458 fichiers MQL. Mais
l'EA d'origine **n'a aucune logique de seance** (il tourne 24/5 et porte la nuit) et
son bracket est fixe (SL 30 points / TP 100 points). **Ce qui a ete valide, et ce que
ce module implemente, c'est la CONDITION D'ENTREE de cet EA encapsulee dans le
dispositif intraday du projet** — entrees en seance seulement, stop de STRUCTURE,
sortie forcee avant la cloture. Ce n'est pas "ADX_System.mq4"; l'appeler ainsi
ferait croire a une reproduction de l'EA.

LA REGLE, telle que le source la donne (shift 2 = avant-derniere barre close,
shift 1 = derniere barre close; la barre en formation n'est jamais lue):

    ADX_p   = ADX(14)[2]      ADX_c   = ADX(14)[1]
    DIplus_p= +DI(14)[2]      DIplus_c= +DI(14)[1]
    DIminus_p=-DI(14)[2]      DIminus_c=-DI(14)[1]

    LONG  si  ADX_p < ADX_c  ET  DIplus_p  < ADX_p  ET  DIplus_c  > ADX_c
    SHORT si  ADX_p < ADX_c  ET  DIminus_p < ADX_p  ET  DIminus_c > ADX_c

soit: **l'ADX monte, et le DI directionnel traverse la ligne ADX par le bas**.

CE QUE LE PROJET AJOUTE (et qui fait partie de la regle, pas d'un reglage):
  * entrees uniquement dans la fenetre de seance, **sortie forcee avant la cloture**
    (une position ouverte 3 barres avant la fin meurt a la fin);
  * **stop de STRUCTURE**: distance au plus-bas/plus-haut des `struct_n` dernieres
    barres, plancher a 0.25 x ATR14. C'est ce bracket qui porte le resultat — a
    1.5 x ATR14 le R/an est plus gros (+22.4 contre +14.3) mais le maxDD DOUBLE
    (27.2 contre 12.8 R) et le RoMaD tombe de 1.12 a 0.82;
  * **plancher 1R >= 25 spreads** (lecon KELT): sans lui on prend des trades dont
    le peage mange le R;
  * pas de cible: la sortie est le stop ou la cloture de seance.

POURQUOI 0.5R. Test d'admission du projet, net de tous couts FTMO: livre actuel
15.2 %/an a 1.6 % de ruine; **+ADXDI@0.5R -> 17.6 %/an a 1.4 %** (RoMaD du livre
2.39 -> 2.52); a 1R le RoMaD du livre RETOMBE a 2.25. Meme lecon que KAER et KELT:
une sleeve se dose a la moitie quand sa valeur est sa decorrelation.

CE QUE CE N'EST PAS. In-sample, tete de 654 signaux; ce qui la distingue n'est pas
son t mais sa REPLICATION (GER40 2.98 / NAS100 2.15 / US500 1.90, les deux nulls
franchis sur les trois). Correlations mensuelles au livre: b1 +0.157, KAER +0.146,
or -0.038, crypto -0.002, IBS -0.044.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class AdxDiParams:
    adx_n: int = 14            # periode ADX/DI, celle du source
    struct_n: int = 10         # stop de structure: plus-bas/haut des n dernieres barres
    atr_n: int = 14            # ATR du plancher de structure
    struct_floor_atr: float = 0.25
    floor_spread: float = 25.0  # 1R >= 25 spreads (lecon KELT)
    size_R: float = 0.5


def wilder_rma(x: np.ndarray, n: int) -> np.ndarray:
    """Lissage de Wilder (celui de MQL4: iADX/iATR l'utilisent)."""
    x = np.asarray(x, float)
    out = np.full(len(x), np.nan)
    if len(x) <= n:
        return out
    out[n - 1] = np.nanmean(x[:n])
    for i in range(n, len(x)):
        out[i] = (out[i - 1] * (n - 1) + x[i]) / n
    return out


def adx_di(high, low, close, n: int = 14):
    """(ADX, +DI, -DI) a la MQL4 — lissage de Wilder partout."""
    h, l, c = (np.asarray(v, float) for v in (high, low, close))
    pc = np.concatenate(([c[0]], c[:-1]))
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    up, dn = np.diff(h, prepend=h[0]), -np.diff(l, prepend=l[0])
    plus = np.where((up > dn) & (up > 0), up, 0.0)
    minus = np.where((dn > up) & (dn > 0), dn, 0.0)
    atr = wilder_rma(tr, n)
    with np.errstate(invalid='ignore', divide='ignore'):
        pdi = 100.0 * wilder_rma(plus, n) / atr
        mdi = 100.0 * wilder_rma(minus, n) / atr
        dx = 100.0 * np.abs(pdi - mdi) / (pdi + mdi)
    return wilder_rma(dx, n), pdi, mdi


def adxdi_signals(high, low, close, p: AdxDiParams | None = None) -> np.ndarray:
    """+1 / -1 / 0 par barre, decide a la CLOTURE de la barre courante.

    Le source lit shift 2 et shift 1, c'est-a-dire les DEUX dernieres barres
    CLOSES vues depuis la barre en formation. A la cloture de la barre i, ces deux
    barres sont i-1 et i. On lit donc adx[i-1] (le "p" du source) et adx[i] (le
    "c"), jamais une barre future — et le moteur remplit a l'ouverture de i+1.
    """
    p = p or AdxDiParams()
    adx, pdi, mdi = adx_di(high, low, close, p.adx_n)
    prev = lambda a: np.concatenate(([np.nan], a[:-1]))
    adx_p, pdi_p, mdi_p = prev(adx), prev(pdi), prev(mdi)
    rising = adx_p < adx
    long_c = rising & (pdi_p < adx_p) & (pdi > adx)
    short_c = rising & (mdi_p < adx_p) & (mdi > adx)
    s = np.zeros(len(adx), np.int8)
    s[np.nan_to_num(long_c, nan=0).astype(bool)] = 1
    s[np.nan_to_num(short_c, nan=0).astype(bool) & (s == 0)] = -1
    return s


def stop_distance(high, low, close, spread_px, p: AdxDiParams | None = None) -> np.ndarray:
    """1R = max( structure(struct_n), 0.25 x ATR14, floor_spread x spread )."""
    p = p or AdxDiParams()
    h, l, c = (np.asarray(v, float) for v in (high, low, close))
    pc = np.concatenate(([c[0]], c[:-1]))
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    atr = wilder_rma(tr, p.atr_n)
    lo = pd.Series(l).rolling(p.struct_n, min_periods=p.struct_n).min().to_numpy()
    hi = pd.Series(h).rolling(p.struct_n, min_periods=p.struct_n).max().to_numpy()
    d = np.fmax(c - lo, hi - c)
    d = np.fmax(d, p.struct_floor_atr * atr)
    return np.fmax(d, p.floor_spread * np.asarray(spread_px, float))
