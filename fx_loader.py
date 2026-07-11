"""
fx_loader.py
============
Univers CROSS-SECTIONNEL FX + MÉTAUX (MT5, daily), orienté "actif vs USD".

Orientation : toutes les séries sont exprimées comme « devise/métal étranger coté en USD ».
Les paires USDXXX sont INVERSÉES (XXXUSD = 1/USDXXX) afin qu'un rendement positif signifie
toujours « l'actif se renforce contre le dollar ». Conséquence : classer ces actifs entre eux
revient à mesurer une force relative, et l'exposition USD s'annule dans un book long/short.

⚠️ PAS DE CARRY. MT5 n'expose que le swap COURANT (symbol_info.swap_long/short), pas son
   historique. L'utiliser comme feature sur des dates passées serait du look-ahead. Le carry
   est donc volontairement absent — le construire proprement exigerait un historique de taux.

Cache CSV par symbole → build reprenable.
"""
from __future__ import annotations
import os
from datetime import datetime, timezone

import numpy as np
import pandas as pd

CACHE = os.path.join(os.path.dirname(__file__), "data_cache_mt5")
PANEL = os.path.join(CACHE, "fx_panel.parquet")
os.makedirs(CACHE, exist_ok=True)
START = datetime(2015, 1, 1, tzinfo=timezone.utc)

# Univers liquide : majors, scandinaves, CE3, EM liquides, métaux précieux.
# (Exclus : USDARS/NGN/COP/GEL/RUB… — spreads énormes ou historiques troués.)
DIRECT = ["EURUSD", "GBPUSD", "AUDUSD", "NZDUSD"]                 # déjà XXX vs USD
INVERT = ["USDJPY", "USDCHF", "USDCAD", "USDSEK", "USDNOK", "USDDKK",
          "USDPLN", "USDCZK", "USDHUF", "USDMXN", "USDZAR", "USDSGD",
          "USDCNH", "USDILS", "USDTHB", "USDKRW"]                 # à inverser
METALS = ["XAUUSD", "XAGUSD", "XPTUSD", "XPDUSD"]                 # déjà vs USD

MIN_BARS = 1500          # ≥ ~6 ans d'historique daily
MAX_SPREAD_BPS = 15.0    # filtre de liquidité (coût aller-retour raisonnable)


def _fetch(symbol: str):
    path = os.path.join(CACHE, f"fx_{symbol}.csv")
    if os.path.exists(path):
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        df.index = pd.DatetimeIndex(df.index)
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        return df if len(df) >= MIN_BARS else None

    import MetaTrader5 as mt5
    if not mt5.symbol_select(symbol, True):
        return None
    r = mt5.copy_rates_range(symbol, mt5.TIMEFRAME_D1, START, datetime.now(timezone.utc))
    if r is None or len(r) < MIN_BARS:
        return None
    d = pd.DataFrame(r)
    d["time"] = pd.to_datetime(d["time"], unit="s", utc=True)
    d = d.set_index("time")[["close"]]
    d.to_csv(path)
    return d


def spreads_bps() -> dict:
    """Coût relatif (bps de prix) du spread courant, par actif orienté vs USD."""
    import MetaTrader5 as mt5
    if not mt5.initialize():
        raise RuntimeError(mt5.last_error())
    out = {}
    for sym in DIRECT + INVERT + METALS:
        si = mt5.symbol_info(sym)
        if si is None or si.ask <= 0:
            continue
        spread_price = si.spread * si.point
        # le spread RELATIF est invariant par inversion de la paire (au 1er ordre)
        out[_name(sym)] = spread_price / si.ask * 1e4
    mt5.shutdown()
    return out


def _name(sym: str) -> str:
    """Nom de l'actif orienté vs USD (USDJPY -> JPYUSD)."""
    return sym[3:] + "USD" if sym in INVERT else sym


def build_panel(force: bool = False) -> pd.DataFrame:
    """Panel wide : index=date, colonnes=actifs (close orienté vs USD)."""
    if os.path.exists(PANEL) and not force:
        return pd.read_parquet(PANEL)

    import MetaTrader5 as mt5
    if not mt5.initialize():
        raise RuntimeError(mt5.last_error())

    series = {}
    for sym in DIRECT + METALS:
        d = _fetch(sym)
        if d is not None:
            series[sym] = d["close"]
    for sym in INVERT:
        d = _fetch(sym)
        if d is not None:
            series[_name(sym)] = 1.0 / d["close"]          # inversion → XXX vs USD
    mt5.shutdown()

    panel = pd.DataFrame(series).sort_index()
    panel.index = panel.index.normalize()
    panel = panel[~panel.index.duplicated(keep="first")]
    panel.to_parquet(PANEL)
    return panel


if __name__ == "__main__":
    p = build_panel()
    print(f"Panel FX+métaux : {p.shape[1]} actifs · {len(p)} dates "
          f"[{p.index[0].date()} -> {p.index[-1].date()}]")
    print("Actifs :", ", ".join(p.columns))
    sp = spreads_bps()
    print("\nSpreads (bps de prix) :")
    for k, v in sorted(sp.items(), key=lambda kv: kv[1]):
        flag = "" if v <= MAX_SPREAD_BPS else "  <-- exclu (illiquide)"
        print(f"  {k:8s} {v:6.2f}{flag}")
