"""Socle commun de la chaine `research/` : univers, horloges, chemins, journal.

TROIS DECISIONS DE SOCLE, toutes prises ici pour qu'aucun script ne les reprenne.

1. L'HORLOGE SERVEUR EST CONVERTIE EN UTC, ELLE N'EST PAS SUPPOSEE UTC. MT5
   estampille en heure serveur (Pepperstone = Europe/Athens, EET/EEST). Le reste
   du depot approxime "serveur = UTC" ; ici c'est interdit, parce que la moitie
   des familles du mandat sont des signaux de SESSION (ouverture NY 13h30/14h30
   UTC selon la saison, fixing de Londres 15h/16h UTC). Une erreur d'une heure
   deux fois par an suffit a fabriquer ou detruire une saisonnalite.

2. LE SIGNAL EST LU A LA CLOTURE DE t, LE RENDEMENT VA DE CLOTURE t A CLOTURE
   t+k. C'est la lettre du mandat. Toute serie derivee est donc calculee sur les
   barres <= t inclus, jamais au-dela, et `fwd(k)` est le SEUL tableau du depot
   autorise a regarder devant lui.

3. LE PEAGE N'INTERVIENT PAS DANS CETTE PHASE. Il est neanmoins MESURE et
   stocke (`_costs.json`) parce que la phase suivante en aura besoin et que le
   spread median d'un symbole est une propriete du terminal, pas du backtest.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent          # .../research
DATA = ROOT / "data"
LOGS = ROOT / "logs"
SCRIPTS = ROOT / "scripts"
REPO = ROOT.parent
for _d in (DATA, LOGS):
    _d.mkdir(parents=True, exist_ok=True)

SERVER_TZ = "Europe/Athens"

# ------------------------------------------------------------------ univers
# Cle = nom logique du mandat, valeur = nom EXACT sur le terminal Pepperstone.
# Resolu contre `mt5.symbols_get()` : US100 -> NAS100, SPX500 -> US500,
# USOIL/WTI -> SpotCrude. Ne rien ajouter : ce que le terminal ne sert pas ne
# peut pas etre teste.
SYMBOLS = {
    # Forex majors & minors (10)
    "EURUSD": "EURUSD", "GBPUSD": "GBPUSD", "USDJPY": "USDJPY",
    "AUDUSD": "AUDUSD", "USDCAD": "USDCAD", "USDCHF": "USDCHF",
    "NZDUSD": "NZDUSD", "EURGBP": "EURGBP", "EURJPY": "EURJPY",
    "GBPJPY": "GBPJPY",
    # Indices CFD cash (5)
    "US100": "NAS100", "US500": "US500", "US30": "US30",
    "GER40": "GER40", "UK100": "UK100",
    # Matieres premieres (3)
    "XAUUSD": "XAUUSD", "XAGUSD": "XAGUSD", "USOIL": "SpotCrude",
    # Crypto (2)
    "BTCUSD": "BTCUSD", "ETHUSD": "ETHUSD",
}
FX = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD",
      "EURGBP", "EURJPY", "GBPJPY"]
INDICES = ["US100", "US500", "US30", "GER40", "UK100"]
COMMOD = ["XAUUSD", "XAGUSD", "USOIL"]
CRYPTO = ["BTCUSD", "ETHUSD"]
UNIVERSE = FX + INDICES + COMMOD + CRYPTO
CLASS_OF = ({s: "fx" for s in FX} | {s: "index" for s in INDICES} |
            {s: "commodity" for s in COMMOD} | {s: "crypto" for s in CRYPTO})
assert len(UNIVERSE) == 20

# ------------------------------------------------------------------ horloges
# Profondeur choisie par UT : assez de barres pour que le decoupage en blocs
# trimestriels laisse >= 8 blocs, sans demander au terminal un historique M5
# qu'il ne sert pas.
TIMEFRAMES = ["M5", "M15", "H1", "H4"]
TF_START = {"M5": "2020-01-01", "M15": "2018-01-01",
            "H1": "2012-01-01", "H4": "2010-01-01"}
BARS_PER_DAY = {"M5": 288.0, "M15": 96.0, "H1": 24.0, "H4": 6.0}
# Un bloc = ~un trimestre de barres de marche. Unite statistique de la t-stat.
BLOCK_BARS = {"M5": 18_000, "M15": 6_000, "H1": 1_512, "H4": 378}

HORIZONS = [1, 3, 5, 12, 24]

# ------------------------------------------------------------------ porte du mandat
GATE_MIN_ABS_IC = 0.03
GATE_MIN_ABS_T = 2.50
GATE_MIN_SUBPERIODS = 3        # sous-periodes de meme signe
N_SUBPERIODS = 4               # decoupage temporel en quarts
GATE_MIN_INDEP_OBS = 500       # occurrences INDEPENDANTES = n_obs / k
FDR_Q = 0.10                   # controle ajoute (hors lettre du mandat)

ATR_LEN = 14


# ------------------------------------------------------------------ journal
def get_logger(name: str = "research") -> logging.Logger:
    lg = logging.getLogger(name)
    if lg.handlers:
        return lg
    lg.setLevel(logging.INFO)
    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)-14s | %(message)s",
        "%Y-%m-%d %H:%M:%S")
    fh = logging.FileHandler(LOGS / "research_execution.log", encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    lg.addHandler(fh)
    lg.addHandler(sh)
    return lg


# ------------------------------------------------------------------ chemins
def bars_path(sym: str, tf: str) -> Path:
    return DATA / f"{sym}_{tf}.parquet"


def meta_path() -> Path:
    return DATA / "_symbols_meta.json"


def costs_path() -> Path:
    return DATA / "_costs.json"


# ------------------------------------------------------------------ chargement
def to_utc(t) -> pd.DatetimeIndex:
    """Estampille serveur -> UTC vraie, DST comprise.

    `ambiguous='NaT'` : l'heure repetee du passage a l'heure d'hiver tombe un
    dimanche matin ; le forex est ferme, la crypto ne l'est pas. Une barre
    ambigue est jetee plutot que datee au hasard.
    """
    idx = pd.DatetimeIndex(t)
    if idx.tz is None:
        idx = idx.tz_localize(SERVER_TZ, ambiguous="NaT",
                              nonexistent="shift_forward")
    return idx.tz_convert("UTC")


class Bars:
    """Une (symbole, UT) chargee : prix UTC + cache d'indicateurs.

    `atr`, `logret`, ... rendent l'indicateur DATE DE LA BARRE i, calcule sur
    les barres <= i. C'est exactement ce que le mandat autorise : le signal S_t
    est lu a la cloture de t. La seule methode qui regarde devant est `fwd`.
    """

    def __init__(self, sym: str, tf: str, df: pd.DataFrame):
        self.sym, self.tf = sym, tf
        self.t = pd.DatetimeIndex(df["time"])
        self.o = df["open"].to_numpy(float)
        self.h = df["high"].to_numpy(float)
        self.l = df["low"].to_numpy(float)
        self.c = df["close"].to_numpy(float)
        self.v = df["tick_volume"].to_numpy(float)
        self.spread = df["spread"].to_numpy(float)
        self.cache: dict = {}
        # horloge UTC pre-decoupee, utilisee par toute la famille "session"
        self.hour = np.asarray(self.t.hour)
        self.minute = np.asarray(self.t.minute)
        self.dow = np.asarray(self.t.dayofweek)
        self.dom = np.asarray(self.t.day)
        self.dayid = np.asarray(self.t.normalize().astype("int64"))

    def __len__(self) -> int:
        return int(self.c.size)

    # -------------------------------------------------------------- outils
    def _get(self, key: str, fn):
        if key not in self.cache:
            self.cache[key] = fn()
        return self.cache[key]

    def atr(self, n: int = ATR_LEN) -> np.ndarray:
        def f():
            pc = np.concatenate([[self.c[0]], self.c[:-1]])
            tr = np.maximum(self.h - self.l,
                            np.maximum(np.abs(self.h - pc), np.abs(self.l - pc)))
            return pd.Series(tr).ewm(alpha=1.0 / n, adjust=False,
                                     min_periods=n).mean().to_numpy()
        return self._get(f"atr:{n}", f)

    def logret(self) -> np.ndarray:
        return self._get("logret", lambda: np.concatenate(
            [[np.nan], np.diff(np.log(self.c))]))

    def fwd(self, k: int) -> np.ndarray:
        """R_{t+k} = close[t+k]/close[t] - 1. Du futur, assume, jamais feature."""
        def f():
            out = np.full(self.c.shape, np.nan)
            if k < len(self):
                out[:-k] = self.c[k:] / self.c[:-k] - 1.0
            return out
        return self._get(f"fwd:{k}", f)

    def vol_unit(self) -> np.ndarray:
        """ATR14/close CONNUE a t (donc calculee sur <= t).

        Le rendement futur est divise par elle pour rendre les 20 actifs
        comparables. Normaliser par la volatilite REALISEE sur la fenetre
        future serait une fuite classique et invisible dans le resultat.
        """
        return self._get("vu", lambda: self.atr(ATR_LEN) / self.c)


_META_CACHE = None


def symbols_meta() -> dict:
    global _META_CACHE
    if _META_CACHE is None:
        p = meta_path()
        _META_CACHE = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    return _META_CACHE


def load(sym: str, tf: str):
    p = bars_path(sym, tf)
    if not p.exists():
        return None
    df = pd.read_parquet(p)
    if len(df) < 500:
        return None
    return Bars(sym, tf, df)


def available() -> list:
    return [(s, tf) for s in UNIVERSE for tf in TIMEFRAMES
            if bars_path(s, tf).exists()]
