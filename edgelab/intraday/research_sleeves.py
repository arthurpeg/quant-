"""RVWAP et RSKEW — les deux sleeves issues de la chaine `research/` (2026-08-18).

    RVWAP : GER40 H1, distance au VWAP ancre a la session NY, sortie a 24 barres,
            1R = 3.0 x ATR14.
    RSKEW : US30  H4, asymetrie des 50 derniers log-rendements, sortie a 5 barres,
            1R = 4.0 x ATR14.

D'OU ELLES VIENNENT. `research/` a mesure 28 300 cellules d'IC, garde les 173 qui
avaient un bord brut superieur au peage, puis balaye leur geometrie de sortie
(2 595 configurations) et enfin classe les survivantes par RoMaD standalone NET
des couts FTMO releves sur le terminal le 2026-08-18. Ces deux-la sont
respectivement la 3e (RoMaD 0,86) et la 5e (0,73) de ce classement, et la
seconde est la seule DECORRELEE du book (corr -0,004 contre +0,218).

LE POINT QUI GOUVERNE CE FICHIER : LA PARITE EST UNE PROPRIETE DU CHEMIN DE CODE.
`signal_series()` et `stop_distance()` ci-dessous sont appelees par le backtest
(`run_research_sleeve`) ET par le scan live (`edgelab.live.signals.research_scan`).
Il n'y a donc pas deux definitions a garder d'accord : il y en a une. C'est la
regle que `propresearch/data.py` enonce deja pour son propre perimetre, et les
deux fois ou ce depot a perdu la parite, c'est faute de l'avoir suivie.

TROIS REGLES DE DECISION, identiques des deux cotes.

1. LE RANG D'ENTREE COMPTE LES OCCURRENCES DU SIGNAL, PAS LES BARRES. Le signal
   VWAP n'existe que pendant la session NY (~7 barres H1 sur 24). Une fenetre de
   1 000 BARRES n'y contient jamais les 500 valeurs exigees et le rang sortirait
   entierement NaN -- defaut deja paye en recherche, ou il annulait 39 % de la
   grille en silence.
2. LE SENS VIENT DU SIGNE DE L'IC MESURE, pre-enregistre ici en dur
   (`ic_sign`), jamais recalcule en live : un signe qui se retourne en
   production serait un degre de liberte invisible.
3. LA DECISION EST PRISE A LA CLOTURE DE LA BARRE, L'ENTREE EST A L'OUVERTURE DE
   LA SUIVANTE. Le stop est fige a l'entree ; la sortie est le stop ou la
   barriere de temps a `max_bars` barres du CADRE DU BROKER (un index, pas des
   heures d'horloge -- les flux ont des trous, et compter des heures ferait
   diverger le live du backtest exactement comme sur KELT).

CE QU'ELLES NE SONT PAS. Ni des briques, ni des sleeves validees : elles sont
IN-SAMPLE, tirees d'une grille de 28 300 cellules, et n'ont **aucun forward-test**.
KAER, HMASTO et TLF sont toutes entrees en forward-test a 0,5R avant d'etre
jugees, et HMASTO a ete retiree de FUNDED pour avoir echoue son seul
hors-echantillon. Le deploiement a 1R est une instruction utilisateur du
2026-08-18, pas une conclusion de mesure.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

MT5_DIR = Path(__file__).resolve().parents[2] / "data_cache_mt5"
RESEARCH_DIR = Path(__file__).resolve().parents[2] / "research" / "data"
SERVER_TZ = "Europe/Athens"


@dataclass
class SleeveParams:
    """Tout ce qui definit une sleeve. Aucun de ces champs n'est optimise en live."""
    name: str
    symbol: str
    timeframe: str              # "H1" ou "H4"
    bar_minutes: int
    kind: str                   # "vwap_z" ou "skew"
    max_bars: int               # barriere de temps, en barres du cadre broker
    k_stop: float               # 1R = k_stop * ATR14
    ic_sign: int                # signe de l'IC mesure : +1 ou -1
    q: float = 0.90             # seuil de rang causal, PRE-ENREGISTRE
    rank_win: int = 1000        # fenetre du rang, en OCCURRENCES du signal
    rank_min: int = 500
    atr_n: int = 14
    session: str = "NY"         # pour vwap_z
    skew_n: int = 50            # pour skew (la cellule gagnante, pas 20)
    size_R: float = 1.0
    warmup: int = 60            # garde-fou ; c'est le RANG CAUSAL qui gate
                                # vraiment (NaN tant que `rank_min` occurrences
                                # ne sont pas reunies)


RVWAP = SleeveParams(name="RVWAP", symbol="GER40", timeframe="H1", bar_minutes=60,
                     kind="vwap_z", max_bars=24, k_stop=3.0, ic_sign=-1)
RSKEW = SleeveParams(name="RSKEW", symbol="US30", timeframe="H4", bar_minutes=240,
                     kind="skew", max_bars=5, k_stop=4.0, ic_sign=+1, skew_n=50)
SLEEVES = {"RVWAP": RVWAP, "RSKEW": RSKEW}

# Session NY en heure LOCALE de la place : 09h30-16h00 America/New_York. Un seuil
# UTC fixe se decalerait d'une heure deux fois par an et deplacerait l'ancrage du
# VWAP -- exactement la saisonnalite qu'on croirait mesurer.
NY_TZ, NY_OPEN_M, NY_CLOSE_M = "America/New_York", 9 * 60 + 30, 16 * 60


@dataclass
class SleeveResult:
    params: SleeveParams
    trades: pd.DataFrame
    metrics: dict = field(default_factory=dict)


# ---------------------------------------------------------------- indicateurs
def wilder_atr(high, low, close, n: int) -> np.ndarray:
    """ATR de Wilder en EWM alpha=1/n, min_periods=n — la forme exacte de `research`."""
    high, low, close = (np.asarray(x, float) for x in (high, low, close))
    pc = np.concatenate(([close[0]], close[:-1]))
    tr = np.maximum(high - low, np.maximum(np.abs(high - pc), np.abs(low - pc)))
    return pd.Series(tr).ewm(alpha=1.0 / n, adjust=False,
                             min_periods=n).mean().to_numpy()


def _safe(num: np.ndarray, den: np.ndarray) -> np.ndarray:
    den = np.where(np.abs(den) < 1e-12, np.nan, den)
    return num / den


def signal_series(bars: pd.DataFrame, p: SleeveParams) -> np.ndarray:
    """S_t pour chaque barre. La case i n'utilise QUE des barres d'indice <= i.

    C'EST LA FONCTION UNIQUE : le backtest et le live l'appellent tous les deux.
    """
    c = bars["close"].to_numpy(float)
    h = bars["high"].to_numpy(float)
    lo = bars["low"].to_numpy(float)
    atr = wilder_atr(h, lo, c, p.atr_n)

    if p.kind == "vwap_z":
        v = bars["tick_volume"].to_numpy(float) if "tick_volume" in bars \
            else np.ones(len(bars))
        loc = bars.index.tz_convert(NY_TZ)
        mins = np.asarray(loc.hour) * 60 + np.asarray(loc.minute)
        day = np.asarray(loc.normalize().tz_localize(None).astype("int64"))
        ins = (mins >= NY_OPEN_M) & (mins < NY_CLOSE_M)
        tp = (h + lo + c) / 3.0
        vv = np.where(ins, np.maximum(v, 1.0), 0.0)
        g = pd.Series(np.where(ins, day, -1))
        num = pd.Series(tp * vv).groupby(g).cumsum().to_numpy()
        den = pd.Series(vv).groupby(g).cumsum().to_numpy()
        vwap = _safe(num, den)
        out = np.where(ins, -_safe(c - vwap, atr), np.nan)
    elif p.kind == "skew":
        # PAS DE SIGNE MOINS ICI. `research/scripts/signals.py::f_skew` rend
        # l'asymetrie BRUTE ; c'est sa chaine `FORMULA` qui annonce un moins et
        # qui a tort (le code est la verite, la doc a derive). Negater ici
        # retournerait le sens et faisait passer la sleeve de +2,4 a -0,4 R/an.
        lr = np.concatenate(([np.nan], np.diff(np.log(c))))
        out = pd.Series(lr).rolling(p.skew_n).skew().to_numpy()
    else:                                              # pragma: no cover
        raise ValueError(p.kind)

    # `copy=True` : `rolling(...).skew()` peut rendre une vue en LECTURE SEULE.
    out = np.array(out, dtype=float, copy=True)
    out[~np.isfinite(out)] = np.nan
    return out


def causal_rank(x: np.ndarray, p: SleeveParams) -> np.ndarray:
    """Rang de x_t parmi ses `rank_win` DERNIERES OCCURRENCES, en [0, 1].

    La fenetre compte les OCCURRENCES et non les barres : le VWAP de session
    n'existe que ~7 barres sur 24, et une fenetre en barres ne reunirait jamais
    `rank_min` valeurs.
    """
    out = np.full(x.size, np.nan)
    idx = np.flatnonzero(np.isfinite(x))
    if idx.size < p.rank_min:
        return out
    out[idx] = (pd.Series(x[idx]).rolling(p.rank_win, min_periods=p.rank_min)
                .rank(pct=True).to_numpy())
    return out


def stop_distance(bars: pd.DataFrame, i: int, p: SleeveParams) -> float:
    """1R pour un signal a la barre `i` : k_stop x ATR14[i], lu A LA BARRE DE SIGNAL."""
    a = wilder_atr(bars["high"], bars["low"], bars["close"], p.atr_n)[i]
    if not np.isfinite(a) or a <= 0:
        return 0.0
    return float(p.k_stop * a)


def decide(bars: pd.DataFrame, p: SleeveParams) -> tuple[int, float] | None:
    """La DECISION a la derniere barre de `bars` (deja privee de la barre en cours).

    Rend (sens, distance de stop) ou None. Appelee identiquement par le backtest
    et par le scan live -- c'est ici que la parite se joue.
    """
    if len(bars) < p.warmup:
        return None
    sig = signal_series(bars, p)
    pr = causal_rank(sig, p)
    i = len(bars) - 1
    if not np.isfinite(pr[i]):
        return None
    if pr[i] >= p.q:
        side = p.ic_sign
    elif pr[i] <= (1.0 - p.q):
        side = -p.ic_sign
    else:
        return None
    dist = stop_distance(bars, i, p)
    if dist <= 0:
        return None
    return int(side), float(dist)


# ---------------------------------------------------------------- donnees
def to_true_utc(idx: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Estampille SERVEUR -> UTC vraie. Le cache porte l'heure du broker."""
    if idx.tz is not None:
        return idx
    return (idx.tz_localize(SERVER_TZ, ambiguous="NaT", nonexistent="shift_forward")
            .tz_convert("UTC"))


def load_bars(p: SleeveParams, data_dir: Path | None = None) -> pd.DataFrame:
    """Les barres de la sleeve, index UTC. `research/data` d'abord (deja nettoye)."""
    for d in ([Path(data_dir)] if data_dir else [RESEARCH_DIR, MT5_DIR]):
        f = d / f"{p.symbol}_{p.timeframe}.parquet"
        if f.exists():
            df = pd.read_parquet(f)
            df.columns = [c.lower() for c in df.columns]
            idx = pd.DatetimeIndex(pd.to_datetime(df["time"], utc=True)) \
                if pd.DatetimeIndex(pd.to_datetime(df["time"])).tz is not None \
                else to_true_utc(pd.DatetimeIndex(pd.to_datetime(df["time"])))
            df = df.set_index(idx).sort_index()
            cols = [c for c in ("open", "high", "low", "close", "tick_volume", "spread")
                    if c in df.columns]
            return df[cols].astype(float)
    raise FileNotFoundError(f"{p.symbol}_{p.timeframe}.parquet introuvable")


# ---------------------------------------------------------------- backtest
def run_research_sleeve(name: str, p: SleeveParams | None = None,
                        bars: pd.DataFrame | None = None) -> SleeveResult:
    """Le backtest, ecrit sur EXACTEMENT les fonctions que le live appelle.

    Une position a la fois (balayage glouton causal), entree a l'ouverture de la
    barre suivante, sortie au stop ou a `max_bars` barres. Le gap est honore :
    une barre qui OUVRE au-dela du stop sort a l'ouverture, donc a pire que -1R.
    """
    p = p or SLEEVES[name]
    b = bars if bars is not None else load_bars(p)
    o = b["open"].to_numpy(float)
    h = b["high"].to_numpy(float)
    lo = b["low"].to_numpy(float)
    c = b["close"].to_numpy(float)
    n = len(b)

    sig = signal_series(b, p)
    pr = causal_rank(sig, p)
    atr = wilder_atr(h, lo, c, p.atr_n)

    rows = []
    i = p.warmup
    while i < n - 1:
        if not np.isfinite(pr[i]):
            i += 1
            continue
        if pr[i] >= p.q:
            side = p.ic_sign
        elif pr[i] <= (1.0 - p.q):
            side = -p.ic_sign
        else:
            i += 1
            continue
        dist = p.k_stop * atr[i]
        if not np.isfinite(dist) or dist <= 0:
            i += 1
            continue

        e = i + 1                                   # barre d'entree
        px_in = o[e]
        stop = px_in - side * dist
        exit_i, px_out, why = None, None, None
        for j in range(p.max_bars):
            k = e + j
            if k >= n:
                break
            if side * (o[k] - stop) <= 0:           # gap a travers le stop
                exit_i, px_out, why = k, o[k], "gap_stop"
                break
            worst = lo[k] if side > 0 else h[k]
            if side * (worst - stop) <= 0:
                exit_i, px_out, why = k, stop, "stop"
                break
        if exit_i is None:
            k = min(e + p.max_bars, n - 1)
            exit_i, px_out, why = k, o[k], "time_exit"

        rows.append(dict(signal_time=b.index[i], entry_time=b.index[e],
                         exit_time=b.index[exit_i], direction=int(side),
                         entry=float(px_in), exit=float(px_out),
                         sl_dist=float(dist), reason=why,
                         bars=int(exit_i - e),
                         R=float(side * (px_out - px_in) / dist)))
        # UNE POSITION A LA FOIS, avec la convention EXACTE de `research`
        # (`06_stop_geometry.nonoverlap`) : le poste est libre DES la barre de
        # sortie, donc un signal a `exit_i - 1` peut entrer a `exit_i`. Un
        # `i = exit_i` decalerait tout d'une barre et changerait le jeu de trades.
        i = max(exit_i - 1, i + 1)
    tr = pd.DataFrame(rows)
    m = {}
    if len(tr):
        r = tr["R"].to_numpy()
        yrs = max((tr["exit_time"].max() - tr["entry_time"].min()).days / 365.25, 1e-9)
        eq = np.cumsum(r)
        m = dict(n=len(r), ER=float(r.mean()), R_per_yr=float(r.sum() / yrs),
                 maxdd=float((np.maximum.accumulate(eq) - eq).max()),
                 win=float((r > 0).mean()),
                 pf=float(r[r > 0].sum() / -r[r < 0].sum()) if (r < 0).any() else np.inf)
    return SleeveResult(params=p, trades=tr, metrics=m)
