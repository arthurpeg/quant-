"""
pipeline.py
===========
Orchestration : valide symbole → charge → nettoie → resample 1H → features → labeling → (X, y).

Garantit :
  - séparation stricte X (features causales, ≤ t) / y (labels triple barrier, futur) ;
  - split TEMPOREL walk-forward (jamais aléatoire) avec embargo entre train et test ;
  - déterminisme : ordre de traitement stable, seeds fixés, hash reproductible de (X, y).

Exécuter `python pipeline.py` lance une démo complète sur données synthétiques EURUSD 1H
(avec week-end simulé) et prouve la reproductibilité par un double run (hash identique).
"""

from __future__ import annotations

import hashlib
import logging
import random
from dataclasses import dataclass
from typing import Tuple

import numpy as np
import pandas as pd

import config
import data_loader
from features import momentum, volatility, volume, structure, temporal, mtf
import labeling


# ───────────────────────────────────────────────────────────────────────────
# Déterminisme global
# ───────────────────────────────────────────────────────────────────────────
def set_seeds(seed: int = config.SEED) -> None:
    """Fixe tous les seeds (propagé à numpy et à la stdlib). XGBoost : random_state=seed."""
    random.seed(seed)
    np.random.seed(seed)


# ───────────────────────────────────────────────────────────────────────────
# Construction des features (ordre STABLE → déterministe)
# ───────────────────────────────────────────────────────────────────────────
# L'ordre des modules est figé : il détermine l'ordre des colonnes de X, donc le hash.
_FEATURE_MODULES = (
    ("momentum", momentum),
    ("volatility", volatility),
    ("volume", volume),
    ("structure", structure),
    ("temporal", temporal),
)


def build_features(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """Assemble toutes les features dans un ordre déterministe. df OHLCV nettoyé → X brut."""
    spec = config.validate_symbol(symbol)
    frames = []
    for name, mod in _FEATURE_MODULES:
        if name == "volume":
            # coupe la section si config OU si le symbole n'a pas de volume fiable
            enabled = config.VOLUME_FEATURES_ENABLED and spec.tick_volume
            frames.append(mod.compute(df, enabled=enabled))
        else:
            frames.append(mod.compute(df))
    if config.ENABLE_MTF:                       # features multi-timeframe (sans leakage)
        frames.append(mtf.compute(df))
    feats = pd.concat(frames, axis=1)
    # tri des colonnes désactivé volontairement : on conserve l'ordre métier stable ci-dessus
    return feats


# ───────────────────────────────────────────────────────────────────────────
# Pipeline complet
# ───────────────────────────────────────────────────────────────────────────
@dataclass
class Dataset:
    X: pd.DataFrame
    y: pd.Series
    meta: pd.DataFrame          # colonnes de labeling (barrier_bars, prices, ...) + OHLCV utile
    symbol: str


def run(
    df_raw: pd.DataFrame,
    symbol: str,
    do_resample: bool = True,
    dropna_features: bool = True,
) -> Dataset:
    """
    Exécute le pipeline complet et renvoie un Dataset (X, y, meta).

    - X : features causales (aucune donnée > t).
    - y : label triple barrier (entier, config.LABEL_MAP).
    - Les lignes sans label (warm-up features / événements censurés) sont retirées.
    """
    set_seeds()

    # 1-2. validation + nettoyage + resample + grille de marché
    df = data_loader.clean(df_raw, symbol, do_resample=do_resample)

    # 3. features (X, causal)
    X = build_features(df, symbol)

    # 4. labeling (y, futur)
    labels = labeling.triple_barrier(df)
    y = labels["label"]

    # 5. alignement + retrait des NaN (warm-up des features + labels censurés)
    valid = y.notna()
    if dropna_features:
        valid &= X.notna().all(axis=1)
    X = X.loc[valid].copy()
    y = y.loc[valid].astype(int)
    meta = labels.loc[valid].join(df[list(config.OHLCV_COLS)])

    _sanity_checks(X, y, df)
    return Dataset(X=X, y=y, meta=meta, symbol=symbol)


# ───────────────────────────────────────────────────────────────────────────
# Walk-forward split (temporel, jamais aléatoire)
# ───────────────────────────────────────────────────────────────────────────
def walk_forward_split(
    ds: Dataset,
    test_fraction: float = config.TEST_SIZE_FRACTION,
    embargo: int = config.EMBARGO_BARS,
) -> Tuple[Dataset, Dataset]:
    """
    Découpe temporelle train/test avec embargo. Le test est la fin de la série ; un embargo
    de `embargo` bougies est retiré à la fin du train pour éviter le chevauchement des
    fenêtres de labeling (qui regardent jusqu'à TIMEOUT_BARS dans le futur).
    """
    n = len(ds.X)
    n_test = int(round(n * test_fraction))
    n_train = n - n_test - embargo
    if n_train <= 0:
        raise ValueError("Série trop courte pour ce split/embargo.")

    tr = slice(0, n_train)
    te = slice(n_train + embargo, n)

    train = Dataset(ds.X.iloc[tr], ds.y.iloc[tr], ds.meta.iloc[tr], ds.symbol)
    test = Dataset(ds.X.iloc[te], ds.y.iloc[te], ds.meta.iloc[te], ds.symbol)
    return train, test


# ───────────────────────────────────────────────────────────────────────────
# Hash reproductible de (X, y)
# ───────────────────────────────────────────────────────────────────────────
def dataset_hash(ds: Dataset) -> str:
    """
    SHA-256 déterministe de (X, y) : intègre l'ordre des colonnes, l'index (timestamps) et
    les valeurs (arrondies pour absorber le bruit flottant non significatif). Un même input
    doit produire exactement le même hash entre deux runs → preuve de reproductibilité.
    """
    h = hashlib.sha256()
    h.update(",".join(map(str, ds.X.columns)).encode())
    h.update(ds.X.index.asi8.tobytes())              # timestamps ns
    Xv = np.ascontiguousarray(np.round(ds.X.to_numpy(dtype=np.float64), 10))
    h.update(Xv.tobytes())
    h.update(np.ascontiguousarray(ds.y.to_numpy(dtype=np.int64)).tobytes())
    return h.hexdigest()


# ───────────────────────────────────────────────────────────────────────────
# Sanity checks
# ───────────────────────────────────────────────────────────────────────────
def _sanity_checks(X: pd.DataFrame, y: pd.Series, df: pd.DataFrame) -> None:
    log = logging.getLogger("pipeline")

    if X.isna().any().any():
        cols = X.columns[X.isna().any()].tolist()
        raise AssertionError(f"NaN inattendus dans X : {cols}")
    if np.isinf(X.to_numpy()).any():
        raise AssertionError("Valeurs infinies dans X.")

    # Aucune bougie de week-end fabriquée : chaque timestamp doit être en séance ouverte
    import calendar_utils as cal
    if not cal.market_open_mask(df.index).all():
        raise AssertionError("Des bougies hors séance sont présentes (week-end fabriqué ?).")

    # ~24 bougies par jour ouvré (tolérance large)
    per_day = df.groupby(df.index.normalize()).size()
    workdays = per_day[per_day > 0]
    if len(workdays):
        med = float(workdays.median())
        if not (config.BARS_PER_DAY * 0.6 <= med <= config.BARS_PER_DAY * 1.2):
            log.warning("Médiane bougies/jour = %.1f (attendu ~%d)", med, config.BARS_PER_DAY)

    log.info("Sanity OK — X:%s y:%s | classes=%s",
             X.shape, y.shape, dict(pd.Series(y).value_counts().sort_index()))


def feature_label_corr(ds: Dataset, top: int = 15) -> pd.Series:
    """
    Rapport de corrélation feature/label : |corr(feature, TP=1 vs SL=0)| trié décroissant.
    Diagnostic uniquement (ne PAS utiliser pour sélectionner sur tout le dataset avant split).
    """
    mask = ds.y.isin([config.LABEL_MAP["sl"], config.LABEL_MAP["tp"]])
    yb = (ds.y[mask] == config.LABEL_MAP["tp"]).astype(float)
    corr = ds.X[mask].apply(lambda s: s.corr(yb)).abs().sort_values(ascending=False)
    return corr.head(top)


# ═══════════════════════════════════════════════════════════════════════════
# DÉMO — données synthétiques EURUSD 1H avec week-end simulé + double run (hash)
# ═══════════════════════════════════════════════════════════════════════════
def _make_synthetic_eurusd(n_days: int = 30, seed: int = config.SEED) -> pd.DataFrame:
    """
    Génère un OHLCV 1H synthétique plausible pour EURUSD, incluant naturellement des trous
    de week-end (on ne génère QUE les heures de marché). Marche aléatoire + micro-volatilité.
    On injecte volontairement quelques doublons et une bougie hors séance pour tester le clean.
    """
    import calendar_utils as cal
    rng = np.random.default_rng(seed)

    start = pd.Timestamp("2024-01-01 00:00", tz="UTC")
    end = start + pd.Timedelta(days=n_days)
    grid = cal.market_grid(start, end)              # heures de marché uniquement

    n = len(grid)
    ret = rng.normal(0, 0.0006, n)                  # ~6 pips de vol horaire
    # gap de week-end plus marqué sur la 1re bougie après chaque trou
    step = pd.Timedelta("1h")
    is_gap = grid.to_series().diff().gt(step).fillna(False).to_numpy()
    ret = np.where(is_gap, ret + rng.normal(0, 0.0015, n), ret)

    close = 1.1000 * np.exp(np.cumsum(ret))
    open_ = np.empty(n)
    open_[0] = 1.1000
    open_[1:] = close[:-1]
    open_ = np.where(is_gap, close * np.exp(rng.normal(0, 0.001, n)), open_)
    spread = np.abs(rng.normal(0, 0.0008, n))
    high = np.maximum(open_, close) + spread
    low = np.minimum(open_, close) - spread
    vol = rng.integers(50, 500, n).astype(float)    # tick volume

    df = pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": vol},
        index=grid,
    )

    # Salir volontairement : un doublon + une bougie hors séance (samedi) → testent le clean
    dirty = pd.concat([df, df.iloc[[100]]])                                   # doublon
    sat = pd.Timestamp("2024-01-06 12:00", tz="UTC")                          # samedi
    dirty.loc[sat] = [1.10, 1.101, 1.099, 1.1005, 999.0]
    dirty = dirty.sort_index()
    return dirty


def _demo() -> None:
    import sys
    for stream in (sys.stdout, sys.stderr):
        try:  # console Windows (cp1252) : forcer l'UTF-8 pour les accents / box-drawing
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    logging.basicConfig(level=logging.INFO, format="%(name)s | %(message)s")
    print("═" * 70)
    print("DÉMO PIPELINE — EURUSD 1H synthétique (week-end simulé)")
    print("═" * 70)

    raw = _make_synthetic_eurusd(n_days=40)
    print(f"Données brutes : {len(raw)} lignes "
          f"({raw.index[0]} → {raw.index[-1]})\n")

    # Double run pour prouver le déterminisme
    ds1 = run(raw.copy(), "EURUSD")
    h1 = dataset_hash(ds1)

    ds2 = run(raw.copy(), "EURUSD")
    h2 = dataset_hash(ds2)

    print("\n" + "─" * 70)
    print(f"X shape : {ds1.X.shape}  | y shape : {ds1.y.shape}")
    print(f"Features ({len(ds1.X.columns)}) : {list(ds1.X.columns)}")
    print(f"Répartition classes : "
          f"{ {list(config.LABEL_MAP)[int(k)]: int(v) for k, v in ds1.y.value_counts().sort_index().items()} }")

    # Walk-forward split
    train, test = walk_forward_split(ds1)
    print(f"\nWalk-forward : train={train.X.shape[0]}  embargo={config.EMBARGO_BARS}  test={test.X.shape[0]}")

    # Corrélation feature/label (diagnostic)
    print("\nTop corrélations |feature ↔ TP/SL| :")
    print(feature_label_corr(ds1).round(3).to_string())

    # Vérification hash
    print("\n" + "─" * 70)
    print(f"hash run #1 : {h1}")
    print(f"hash run #2 : {h2}")
    print(f"REPRODUCTIBLE : {'✅ OUI (hash identique)' if h1 == h2 else '❌ NON'}")
    print("═" * 70)

    assert h1 == h2, "Non déterministe : les hash diffèrent."


if __name__ == "__main__":
    _demo()
