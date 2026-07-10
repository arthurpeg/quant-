"""
config.py
=========
Point unique de configuration du pipeline. TOUT paramètre "magique" doit vivre ici :
fenêtres, horizons, R multiple, TP multiple, timeout, colonnes OHLCV, timezone,
whitelist de symboles, définition des sessions, calendrier fériés, seeds, déterminisme.

Aucune logique métier ici — uniquement des constantes / structures de données.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Tuple, List

# ═══════════════════════════════════════════════════════════════════════════
# REPRODUCTIBILITÉ / DÉTERMINISME
# ═══════════════════════════════════════════════════════════════════════════
SEED: int = 42

# Si True : on force XGBoost à n_jobs=1 pour un résultat bit-à-bit reproductible.
# hist + multithread peut introduire des micro-écarts d'ordre de sommation flottante.
STRICT_DETERMINISM: bool = False

# ═══════════════════════════════════════════════════════════════════════════
# TIMEFRAME
# ═══════════════════════════════════════════════════════════════════════════
# Paramétrable pour extension future (ex : "15min", "4H"). En 1H : 24 bougies ≈ 1 jour.
TIMEFRAME: str = "1H"
PANDAS_FREQ: str = "1h"          # alias pandas correspondant au TIMEFRAME
BARS_PER_DAY: int = 24           # sanity check : ~24 bougies par jour ouvré en 1H

# Origine du resampling (respecter l'ancrage horaire du broker). "start_day" = ancré minuit.
RESAMPLE_ORIGIN: str = "start_day"

# ═══════════════════════════════════════════════════════════════════════════
# COLONNES / TIMEZONE
# ═══════════════════════════════════════════════════════════════════════════
COL_OPEN: str = "open"
COL_HIGH: str = "high"
COL_LOW: str = "low"
COL_CLOSE: str = "close"
COL_VOLUME: str = "volume"
OHLCV_COLS: Tuple[str, ...] = (COL_OPEN, COL_HIGH, COL_LOW, COL_CLOSE, COL_VOLUME)

# Tout est manipulé en UTC en interne. L'index d'entrée DOIT être tz-aware UTC.
TIMEZONE: str = "UTC"

# ═══════════════════════════════════════════════════════════════════════════
# UNIVERS D'ACTIFS (CONTRAINTE PROPFIRM) — whitelist + mapping
# ═══════════════════════════════════════════════════════════════════════════
# classes : "forex", "index", "metal", "energy"
# profil de session : détermine quelles sessions comptent le plus (indicatif/feature).
#   - "fx"       : actif 24/5, sessions Asie/Londres/NY pertinentes
#   - "index_us" : indices US, sessions cash US dominantes
#   - "index_eu" : indices EU, sessions Europe dominantes
#   - "metal"    : métaux, comportement FX-like
#   - "energy"   : énergies
@dataclass(frozen=True)
class SymbolSpec:
    asset_class: str
    session_profile: str
    # "volume" fiable ? Pour FOREX/CFD c'est du TICK VOLUME (proxy), pas un vrai volume.
    tick_volume: bool = True


WHITELIST: Dict[str, SymbolSpec] = {
    # --- FOREX ---
    "EURUSD": SymbolSpec("forex", "fx", tick_volume=True),
    "GBPUSD": SymbolSpec("forex", "fx", tick_volume=True),
    "USDJPY": SymbolSpec("forex", "fx", tick_volume=True),
    "AUDUSD": SymbolSpec("forex", "fx", tick_volume=True),
    "USDCAD": SymbolSpec("forex", "fx", tick_volume=True),
    "USDCHF": SymbolSpec("forex", "fx", tick_volume=True),
    "NZDUSD": SymbolSpec("forex", "fx", tick_volume=True),
    "EURJPY": SymbolSpec("forex", "fx", tick_volume=True),
    "GBPJPY": SymbolSpec("forex", "fx", tick_volume=True),
    # --- INDICES ---
    "US30":   SymbolSpec("index", "index_us", tick_volume=True),
    "NAS100": SymbolSpec("index", "index_us", tick_volume=True),
    "SPX500": SymbolSpec("index", "index_us", tick_volume=True),
    "GER40":  SymbolSpec("index", "index_eu", tick_volume=True),
    "UK100":  SymbolSpec("index", "index_eu", tick_volume=True),
    "JP225":  SymbolSpec("index", "index_eu", tick_volume=True),
    # --- MÉTAUX ---
    "XAUUSD": SymbolSpec("metal", "metal", tick_volume=True),
    "XAGUSD": SymbolSpec("metal", "metal", tick_volume=True),
    # --- ÉNERGIES (optionnel) ---
    "USOIL":  SymbolSpec("energy", "energy", tick_volume=True),
    "WTI":    SymbolSpec("energy", "energy", tick_volume=True),
}

# ═══════════════════════════════════════════════════════════════════════════
# CALENDRIER MARCHÉ — semaine forex, week-ends, maintenance, fériés
# ═══════════════════════════════════════════════════════════════════════════
# Semaine forex : ouverture ~dimanche 22:00 UTC → fermeture ~vendredi 22:00 UTC.
# dayofweek : Lundi=0 ... Dimanche=6.
WEEK_OPEN_DOW: int = 6            # dimanche
WEEK_OPEN_HOUR_UTC: int = 22     # ouvre à 22:00 UTC
WEEK_CLOSE_DOW: int = 4          # vendredi
WEEK_CLOSE_HOUR_UTC: int = 22    # ferme à 22:00 UTC

# Pause de maintenance quotidienne (~1h). Trou LÉGITIME, jamais comblé par ffill.
# Vide par défaut pour respecter le sanity check ~24 bougies/jour. Ex : (22,) pour 21-22h.
DAILY_MAINTENANCE_HOURS_UTC: Tuple[int, ...] = ()

# Roll journalier (clôture NY). Sert de reset pour VWAP intra-session & "journée de marché".
# ⚠️ DST-dépendant en réalité ; on fige 22:00 UTC en V1 (heure d'hiver), documenté.
DAILY_RESET_UTC: str = "22:00"

# Jours fériés fermés complets (dates UTC). À compléter selon le broker / l'actif.
HOLIDAYS_UTC: Tuple[str, ...] = (
    "2023-01-01", "2023-12-25",
    "2024-01-01", "2024-12-25",
    "2025-01-01", "2025-12-25",
)

# ═══════════════════════════════════════════════════════════════════════════
# SESSIONS — définies en HEURE LOCALE puis converties en UTC par zoneinfo (gère le DST)
# ═══════════════════════════════════════════════════════════════════════════
# ⚠️ Londres/New York décalent d'~1h l'été (dates différentes), Tokyo non.
# En définissant les bornes en heure locale, la conversion UTC par timestamp gère le DST.
@dataclass(frozen=True)
class SessionSpec:
    tz: str                       # timezone IANA (zoneinfo)
    start_local: str              # "HH:MM" heure locale
    end_local: str                # "HH:MM" heure locale

SESSIONS: Dict[str, SessionSpec] = {
    "asia":    SessionSpec("Asia/Tokyo",       "09:00", "17:00"),
    "london":  SessionSpec("Europe/London",    "08:00", "16:00"),
    "newyork": SessionSpec("America/New_York", "08:00", "17:00"),
}

# Quick-start heure d'hiver (fallback purement indicatif, non utilisé si SESSIONS actif) :
SESSIONS_UTC_WINTER = {
    "asia":    ("00:00", "08:00"),
    "london":  ("08:00", "16:00"),
    "newyork": ("13:00", "22:00"),
}

# ═══════════════════════════════════════════════════════════════════════════
# NETTOYAGE / OUTLIERS
# ═══════════════════════════════════════════════════════════════════════════
OUTLIER_LOGRET_STD: float = 10.0     # |log-return| > k*std → flag/suppression
FFILL_INTRASESSION: bool = True      # ffill OHLC pour micro-coupures intra-séance
VOLUME_FILL_VALUE: float = 0.0       # volume manquant → 0 (jamais ffill)

# ═══════════════════════════════════════════════════════════════════════════
# FEATURES — fenêtres & horizons (en NOMBRE DE BOUGIES)
# ═══════════════════════════════════════════════════════════════════════════
# momentum
LOGRET_HORIZONS: Tuple[int, ...] = (1, 3, 5, 10, 20, 50)
CUM_RETURN_WINDOW: int = 20
SLOPE_WINDOWS: Tuple[int, ...] = (10, 20)
RSI_PERIOD: int = 14
ROC_PERIOD: int = 10

# volatility
ZSCORE_PRICE_WINDOW: int = 20
ATR_PERIOD: int = 14
PARKINSON_WINDOW: int = 20
GARMAN_KLASS_WINDOW: int = 20
VOL_RATIO_FAST: int = 5
VOL_RATIO_SLOW: int = 30
BOLLINGER_WINDOW: int = 20
BOLLINGER_K: float = 2.0

# volume (désactivable — voir tick_volume)
VOLUME_FEATURES_ENABLED: bool = True   # coupe TOUTE la section volume si False
VOLUME_ZSCORE_WINDOW: int = 20
OBV_MA_WINDOW: int = 20
CMF_PERIOD: int = 21
MFI_PERIOD: int = 14

# structure
STREAK_MAX: int = 50                    # borne d'affichage du streak (évite l'explosion)

# ═══════════════════════════════════════════════════════════════════════════
# LABELING — TRIPLE BARRIER (López de Prado)
# ═══════════════════════════════════════════════════════════════════════════
# 1R (unité de prix) = R_ATR_MULT * ATR(ATR_PERIOD).
R_ATR_MULT: float = 1.0          # k : SL = k * ATR(14) définit 1R
TP_R_MULTIPLE: float = 1.5       # TP = +X R (X). Défaut 1.5 (ou 2).
SL_R_MULTIPLE: float = 1.0       # SL = -1R (fixé à 1R par la consigne).
TIMEOUT_BARS: int = 24           # barrière temporelle N, en BOUGIES DE MARCHÉ (~1 jour en 1H)
TRADE_SIDE: int = +1             # +1 = long, -1 = short. Sens du trade évalué.

# Convention si une bougie touche TP ET SL simultanément : "sl" = conservateur (SL d'abord).
AMBIGUOUS_BAR_POLICY: str = "sl"   # {"sl", "tp"}

# Encodage des classes (classification 3 classes).
LABEL_MAP: Dict[str, int] = {"sl": 0, "tp": 1, "timeout": 2}

# ═══════════════════════════════════════════════════════════════════════════
# WALK-FORWARD / SPLIT TEMPOREL
# ═══════════════════════════════════════════════════════════════════════════
# Fraction de la fin de série réservée au test (split TEMPOREL, jamais aléatoire).
TEST_SIZE_FRACTION: float = 0.2
# Marge d'embargo (en bougies) entre train et test pour éviter le chevauchement des
# fenêtres de labeling (les labels regardent jusqu'à TIMEOUT_BARS dans le futur).
EMBARGO_BARS: int = TIMEOUT_BARS

# ═══════════════════════════════════════════════════════════════════════════
# FEATURES OPTIONNELLES
# ═══════════════════════════════════════════════════════════════════════════
ENABLE_WEEKEND_GAP: bool = True
ENABLE_SESSION_ONEHOT: bool = True

# ═══════════════════════════════════════════════════════════════════════════
# MULTI-TIMEFRAME (V2) — features de TF supérieurs projetées SANS LEAKAGE sur la base 1H
# ═══════════════════════════════════════════════════════════════════════════
ENABLE_MTF: bool = False
# (freq pandas, durée de la bougie) : la feature d'un TF supérieur n'est disponible qu'à la
# CLÔTURE de sa bougie → merge_asof "backward" avec availability = open + durée.
MTF_TIMEFRAMES: Tuple[Tuple[str, str], ...] = (("4h", "4h"), ("1D", "1D"))

# ═══════════════════════════════════════════════════════════════════════════
# COÛTS DE TRANSACTION (backtest réaliste)
# ═══════════════════════════════════════════════════════════════════════════
# Coût aller-retour par trade, exprimé en fraction de R (spread + commission + slippage).
# Soustrait du R réalisé de chaque trade. Ex : 0.04 = 4% d'un R perdu à chaque round-trip.
COST_PER_TRADE_R: float = 0.04


def validate_symbol(symbol: str) -> SymbolSpec:
    """Valide un symbole contre la whitelist. Lève ValueError si non autorisé."""
    key = symbol.upper().strip()
    if key not in WHITELIST:
        raise ValueError(
            f"Symbole '{symbol}' non autorisé (hors whitelist propfirm). "
            f"Autorisés : {sorted(WHITELIST)}"
        )
    return WHITELIST[key]
