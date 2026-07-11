"""
equity_loader.py
================
Univers ACTIONS US (CFD MT5) en daily, pour la preuve de concept cross-sectionnelle.

⚠️ BIAIS DE SURVIVANCE : la liste de symboles du broker ne contient que les sociétés
   ENCORE cotées aujourd'hui. Les faillites/radiations (Lehman, Bed Bath...) sont absentes.
   Cela gonfle mécaniquement les performances. On le documente et on l'assume : la POC vise
   à démontrer l'effet de BREADTH, pas à produire une stratégie déployable telle quelle.

⚠️ Les prix CFD sont ajustés des splits mais pas nécessairement des dividendes → rendements
   total-return légèrement sous-estimés. Sans conséquence pour un signal cross-sectionnel.
"""
from __future__ import annotations
import os
from datetime import datetime, timezone

import numpy as np
import pandas as pd

CACHE = os.path.join(os.path.dirname(__file__), "data_cache_mt5")
PANEL_PATH = os.path.join(CACHE, "equity_panel.parquet")
os.makedirs(CACHE, exist_ok=True)
START = datetime(2015, 1, 1, tzinfo=timezone.utc)

# Large caps US liquides (S&P 100 élargi). Intersectées avec les symboles réellement dispos.
TICKERS = """
AAPL MSFT NVDA AMZN GOOGL META TSLA BRK.B AVGO JPM LLY V UNH XOM MA JNJ PG COST HD ABBV
MRK WMT NFLX BAC KO PEP ADBE CRM TMO AMD LIN ACN MCD CSCO ABT ORCL PM DHR WFC IBM
TXN GE VZ NOW INTU CAT DIS AMGN QCOM PFE CMCSA UNP AXP SPGI COP RTX LOW HON NEU BKNG
GS ELV SYK BLK T PLD LMT VRTX MDT SCHW ADI TJX MDLZ CVS PGR BSX C REGN AMT
ETN MMC ZTS CB SO ADP MO CI DUK BDX SLB EOG TGT ITW APD KLAC NOC AON PNC
MU CME SHW MSI GD FDX EMR MCK PSA CL ORLY HUM MAR ROP CTAS TRV APH NSC AJG
AZO ADSK PCAR MNST ECL AIG MET WELL DXCM SPG PAYX AFL O KMB ALL SRE HLT DOW STZ
IDXX A FAST ROST YUM CTSH VRSK EA CPRT ODFL EXC BIIB GIS KR SYY XEL DD WMB LHX
"""


def _fetch_one(symbol: str):
    """Barres D1 d'une action, avec cache CSV PAR SYMBOLE → le build est reprenable."""
    path = os.path.join(CACHE, f"eq_{symbol}.csv")
    if os.path.exists(path):
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        df.index = pd.DatetimeIndex(df.index)
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        return df if len(df) >= 1200 else None

    import MetaTrader5 as mt5
    if not mt5.symbol_select(symbol, True):
        return None
    rates = mt5.copy_rates_range(symbol, mt5.TIMEFRAME_D1, START, datetime.now(timezone.utc))
    if rates is None or len(rates) < 1200:            # exige ≥ ~5 ans d'historique
        return None
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df = df.set_index("time")[["close", "tick_volume"]].rename(columns={"tick_volume": "volume"})
    df.to_csv(path)
    return df


def build_panel(force: bool = False) -> pd.DataFrame:
    """
    Panel long : index (date, ticker), colonnes close/volume.
    Cache parquet pour éviter de re-solliciter MT5.
    """
    if os.path.exists(PANEL_PATH) and not force:
        return pd.read_parquet(PANEL_PATH)

    import MetaTrader5 as mt5
    if not mt5.initialize():
        raise RuntimeError(f"MT5 init: {mt5.last_error()}")
    available = {s.name for s in mt5.symbols_get()}
    wanted = [t for t in TICKERS.split() if t in available]

    frames = []
    print(f"[equity] {len(wanted)} tickers à charger", flush=True)
    for i, t in enumerate(wanted, 1):
        d = _fetch_one(t)
        if d is not None:
            d["ticker"] = t
            frames.append(d.reset_index())
        if i % 20 == 0:
            print(f"[equity] {i}/{len(wanted)} — retenus {len(frames)}", flush=True)
    mt5.shutdown()
    print(f"[equity] terminé : {len(frames)} tickers retenus", flush=True)

    if not frames:
        raise RuntimeError("Aucune action récupérée")
    panel = pd.concat(frames).rename(columns={"time": "date"})
    panel = panel.set_index(["date", "ticker"]).sort_index()
    panel.to_parquet(PANEL_PATH)
    return panel


if __name__ == "__main__":
    p = build_panel()
    n_tick = p.index.get_level_values("ticker").nunique()
    print(f"Panel : {len(p):,} lignes · {n_tick} tickers")
    print(f"Période : {p.index.get_level_values('date').min().date()} -> "
          f"{p.index.get_level_values('date').max().date()}")
    counts = p.groupby(level="date").size()
    print(f"Actions par jour : median={counts.median():.0f}  min={counts.min()}  max={counts.max()}")
