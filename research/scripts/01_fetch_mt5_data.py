"""ETAPE 1 -- synchroniser l'historique reel depuis le terminal MT5 Pepperstone.

    python research/scripts/01_fetch_mt5_data.py [--force] [--tf M5,M15,H1,H4]

Ce script est la seule porte d'entree des donnees de la chaine. Il n'invente
rien : ce que le terminal ne sert pas n'existe pas pour la suite.

QUATRE PRECAUTIONS, toutes payees ailleurs dans ce depot.

1. LA DERNIERE BARRE EST JETEE. Elle est EN FORMATION. Un cache qui la fige
   garde une cloture fausse pour toujours (ledger : la barre du jour en
   formation avait laisse 2,6 % d'erreur permanente sur 1R). On ne garde donc
   que les barres dont la fin est passee.

2. LE TIRAGE EST DECOUPE PAR TRANCHES D'UN AN. `copy_rates_range` est borne
   par le reglage "Max bars in chart" du terminal ; demander dix ans de M5 en
   un appel rend un tableau tronque SANS erreur. Le decoupage rend la
   troncature impossible, et le recollement dedoublonne sur l'estampille.

3. L'ESTAMPILLE EST CONVERTIE EN UTC, PAS SUPPOSEE UTC (voir `common.to_utc`).

4. LE SPREAD EST LU DANS LA COLONNE `spread` DES BARRES, pas dans le tick
   courant. Le tick courant est le spread de MAINTENANT (souvent 22h, hors
   session, donc enorme) ; la colonne des barres est le spread qui a REELLEMENT
   ete affiche a chaque barre de l'historique.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C

LOG = C.get_logger("01_fetch")

_TF_CONST = {}


def _mt5():
    import MetaTrader5 as mt5
    if not mt5.initialize():
        raise RuntimeError(f"MT5 initialize() a echoue : {mt5.last_error()}")
    global _TF_CONST
    if not _TF_CONST:
        _TF_CONST = {"M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15,
                     "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4}
    return mt5


# ------------------------------------------------------------------ metadonnees
def fetch_meta(mt5) -> dict:
    """Point, digits, valeur du tick, swaps, mode de swap : lus une fois."""
    out = {}
    for logical, broker in C.SYMBOLS.items():
        if not mt5.symbol_select(broker, True):
            LOG.warning("symbol_select refuse pour %s (%s)", logical, broker)
            continue
        si = mt5.symbol_info(broker)
        if si is None:
            LOG.warning("symbol_info vide pour %s (%s)", logical, broker)
            continue
        out[logical] = dict(
            broker=broker, description=si.description, path=si.path,
            digits=si.digits, point=si.point,
            trade_contract_size=si.trade_contract_size,
            trade_calc_mode=int(si.trade_calc_mode),
            trade_tick_value=si.trade_tick_value, trade_tick_size=si.trade_tick_size,
            volume_min=si.volume_min, volume_step=si.volume_step,
            swap_long=si.swap_long, swap_short=si.swap_short,
            swap_mode=int(si.swap_mode), swap_rollover3days=int(si.swap_rollover3days),
            currency_base=si.currency_base, currency_profit=si.currency_profit,
            spread_current_pts=si.spread, trade_mode=int(si.trade_mode),
            asset_class=C.CLASS_OF[logical],
        )
    return out


# ------------------------------------------------------------------ barres
def fetch_bars(mt5, logical: str, tf: str) -> pd.DataFrame | None:
    broker = C.SYMBOLS[logical]
    tfc = _TF_CONST[tf]
    start = pd.Timestamp(C.TF_START[tf], tz="UTC").to_pydatetime()
    end = datetime.now(timezone.utc) + timedelta(days=1)

    chunks = []
    cur = start
    while cur < end:
        nxt = min(cur + timedelta(days=366), end)
        r = mt5.copy_rates_range(broker, tfc, cur, nxt)
        if r is not None and len(r):
            chunks.append(pd.DataFrame(r))
        cur = nxt
    if not chunks:
        LOG.warning("%-7s %-3s : aucune barre rendue par le terminal", logical, tf)
        return None

    df = pd.concat(chunks, ignore_index=True)
    df = df.drop_duplicates(subset="time").sort_values("time")
    # `time` MT5 = secondes epoch en heure SERVEUR -> naive puis localisee.
    naive = pd.to_datetime(df["time"], unit="s")
    df["time"] = C.to_utc(naive)
    df = df[df["time"].notna()]

    keep = ["time", "open", "high", "low", "close", "tick_volume", "spread"]
    if "real_volume" in df.columns:
        keep.append("real_volume")
    df = df[keep].reset_index(drop=True)

    # PRECAUTION 1 : la derniere barre est en formation, on la jette.
    df = df.iloc[:-1].reset_index(drop=True)

    # garde-fous elementaires : prix strictement positifs, high >= low
    ok = ((df[["open", "high", "low", "close"]] > 0).all(axis=1)
          & (df["high"] >= df["low"]))
    bad = int((~ok).sum())
    if bad:
        LOG.warning("%-7s %-3s : %d barres incoherentes ecartees", logical, tf, bad)
    return df[ok].reset_index(drop=True)


def trim_backfill(df: pd.DataFrame, sym: str, tf: str) -> tuple[pd.DataFrame, dict]:
    """Coupe la tete de serie REMPLIE PAR LE BROKER, mesuree par la densite.

    Le terminal sert BTCUSD "H1" depuis 2012 et USOIL "H1" depuis 2012 -- mais a
    ~300 barres par an, c'est-a-dire UNE barre par jour de bourse estampillee
    H1. Ce n'est pas de l'historique horaire, c'est du journalier re-etiquete.
    Le laisser entrer fabriquerait des ATR, des sessions et des IC sur des
    barres qui n'ont jamais existe.

    Le test est la DENSITE, pas le spread : sur un compte a spread brut, un
    spread median de 0 point est normal sur EURGBP et ne prouve rien. Un mois
    est declare rempli s'il porte moins de la moitie du nombre de barres median
    des 36 derniers mois, et on ne coupe que la GRAPPE DE TETE (un mois creux
    isole en 2022 ne doit pas emporter les six annees qui le precedent).
    """
    m = df.set_index("time").assign(_x=1).resample("MS")["_x"].sum()
    m = m[m > 0]
    if len(m) < 12:
        return df, dict(trimmed=0)
    ref = float(m.tail(36).median())
    bad = (m < 0.5 * ref).to_numpy()
    frac = np.cumsum(bad) / np.arange(1, len(bad) + 1)
    cand = [i for i in range(len(bad)) if bad[i] and frac[i] >= 0.5]
    if not cand:
        return df, dict(trimmed=0)
    i = max(cand)
    if i + 1 >= len(m):
        return df.iloc[0:0], dict(trimmed=len(df), reason="serie entierement remplie")
    first_ok = m.index[i + 1]
    n0 = len(df)
    out = df[df["time"] >= first_ok].reset_index(drop=True)
    info = dict(trimmed=n0 - len(out), start_after_trim=str(first_ok.date()),
                bars_per_month_ref=ref)
    if info["trimmed"]:
        LOG.info("%-7s %-3s : %d barres de remplissage broker coupees (debut reel %s)",
                 sym, tf, info["trimmed"], info["start_after_trim"])
    return out, info


# Peage : les trois constantes du depot, pas des valeurs devinees.
COMMISSION_RT_EUR = 5.22        # Razor, aller-retour, 1 lot (cf. swinglab/config.py)
SLIPPAGE_PIPS = 1.0             # PAR COTE
LIQ0, LIQ1 = 7 * 60, 20 * 60    # heures liquides, minutes SERVEUR


def cost_row(logical: str, meta: dict, df: pd.DataFrame) -> dict:
    """Peage aller-retour, par la methode deja validee du depot (`swinglab/costs.py`).

    UN SPREAD MEDIAN NAIF VAUT ZERO SUR LES MAJEURES, ET CE ZERO EST FAUX. Sur
    un compte Razor le flux imprime un spread de 0 point sur 27 % des barres
    EURUSD : la mediane brute tombe donc sur 0, et le rapport bord/peage part a
    l'infini. Un 0 imprime est une cotation manquante, pas un spread nul. Le
    plancher est donc la mediane des spreads NON NULS, et seulement pendant les
    heures liquides (07h-20h serveur) -- un creux asiatique ne doit pas faire
    passer un actif pour bon marche.

    Trois composantes, et elles sont rendues SEPAREMENT parce qu'elles ne se
    valent pas : sur EURUSD le spread pese 20 points, la commission 6 et le
    slippage 20. Dire "3,92 bp" sans dire d'ou ils viennent cacherait que plus
    de la moitie du peage est une hypothese de slippage, pas une mesure.

    La commission ne s'applique qu'aux lignes que le broker facture
    (`trade_calc_mode != 2`) : les CFD d'indices n'en portent pas ici. C'est lu
    sur le symbole, pas suppose.
    """
    m = meta[logical]
    pt = float(m["point"])
    pip = pt * 10.0 if int(m["digits"]) in (3, 5) else pt
    tv = float(m["trade_tick_value"])

    tod = pd.DatetimeIndex(df["time"]).tz_convert(C.SERVER_TZ)
    mins = np.asarray(tod.hour) * 60 + np.asarray(tod.minute)
    s = df["spread"].to_numpy(float)[(mins >= LIQ0) & (mins < LIQ1)]
    nz = s[s > 0]
    floor = max(1.0, float(np.median(nz)) if nz.size else float(m["spread_current_pts"]))

    comm_pts = (COMMISSION_RT_EUR / tv) if (int(m["trade_calc_mode"]) != 2 and tv > 0) else 0.0
    slip_pts = 2.0 * SLIPPAGE_PIPS * pip / pt
    rt_pts = floor + comm_pts + slip_pts
    px = float(np.nanmedian(df["close"].to_numpy(float)))
    to_bp = 1e4 * pt / px

    return dict(
        spread_floor_pts=round(floor, 2),
        zero_frac=round(float((s == 0).mean()), 4) if s.size else None,
        comm_pts=round(comm_pts, 2), slip_pts=round(slip_pts, 2),
        rt_pts=round(rt_pts, 2), median_price=px,
        spread_bps=round(floor * to_bp, 4),
        comm_bps=round(comm_pts * to_bp, 4),
        slip_bps=round(slip_pts * to_bp, 4),
        rt_bps=round(rt_pts * to_bp, 4),
        rt_bps_no_slippage=round((floor + comm_pts) * to_bp, 4),
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true",
                    help="retelecharge meme si le parquet existe")
    ap.add_argument("--tf", default=",".join(C.TIMEFRAMES))
    ap.add_argument("--symbols", default=",".join(C.UNIVERSE))
    ap.add_argument("--costs-only", action="store_true",
                    help="ne retelecharge rien : recalcule seulement le peage")
    ap.add_argument("--clean-only", action="store_true",
                    help="ne retelecharge rien : re-applique le nettoyage aux parquets")
    a = ap.parse_args()
    tfs = [t for t in a.tf.split(",") if t in C.TIMEFRAMES]
    syms = [s for s in a.symbols.split(",") if s in C.UNIVERSE]

    if a.costs_only:
        mt5 = _mt5()
        meta = fetch_meta(mt5)
        C.meta_path().write_text(json.dumps(meta, indent=2), encoding="utf-8")
        costs = {}
        for sym in syms:
            if sym not in meta:
                continue
            for tf in tfs:
                p = C.bars_path(sym, tf)
                if not p.exists():
                    continue
                costs.setdefault(sym, {})[tf] = cost_row(sym, meta, pd.read_parquet(p))
            if "H1" in costs.get(sym, {}):
                r = costs[sym]["H1"]
                LOG.info("%-7s : plancher %6.1f pts (%4.1f %% de zeros) + comm %5.1f "
                         "+ slip %5.1f = %6.1f pts = %5.2f bp AR (%.2f bp hors slippage)",
                         sym, r["spread_floor_pts"], 100 * (r["zero_frac"] or 0),
                         r["comm_pts"], r["slip_pts"], r["rt_pts"], r["rt_bps"],
                         r["rt_bps_no_slippage"])
        C.costs_path().write_text(json.dumps(costs, indent=2), encoding="utf-8")
        LOG.info("PEAGE recalcule pour %d symboles", len(costs))
        mt5.shutdown()
        return 0

    if a.clean_only:
        meta = json.loads(C.meta_path().read_text(encoding="utf-8"))
        costs = json.loads(C.costs_path().read_text(encoding="utf-8")) \
            if C.costs_path().exists() else {}
        n = 0
        for sym in syms:
            for tf in tfs:
                p = C.bars_path(sym, tf)
                if not p.exists():
                    continue
                df = pd.read_parquet(p)
                df, info = trim_backfill(df, sym, tf)
                if len(df) < 500:
                    LOG.warning("%-7s %-3s : rejete apres nettoyage (%d barres)",
                                sym, tf, len(df))
                    p.unlink()
                    continue
                df.to_parquet(p, index=False)
                if sym in meta:
                    costs.setdefault(sym, {})[tf] = cost_row(sym, meta, df) | info
                n += 1
        C.costs_path().write_text(json.dumps(costs, indent=2), encoding="utf-8")
        LOG.info("NETTOYAGE termine : %d couples conserves", n)
        return 0

    mt5 = _mt5()
    ti, ai = mt5.terminal_info(), mt5.account_info()
    LOG.info("terminal=%s | serveur=%s | connecte=%s",
             ti.company, ai.server if ai else "?", ti.connected)

    meta = fetch_meta(mt5)
    C.meta_path().write_text(json.dumps(meta, indent=2), encoding="utf-8")
    LOG.info("metadonnees ecrites pour %d/%d symboles", len(meta), len(C.SYMBOLS))

    costs = {}
    if C.costs_path().exists():
        costs = json.loads(C.costs_path().read_text(encoding="utf-8"))

    n_ok = 0
    for sym in syms:
        if sym not in meta:
            continue
        for tf in tfs:
            p = C.bars_path(sym, tf)
            if p.exists() and not a.force:
                df = pd.read_parquet(p)
                LOG.info("%-7s %-3s : cache %7d barres  %s -> %s", sym, tf, len(df),
                         df['time'].iloc[0].date(), df['time'].iloc[-1].date())
                n_ok += 1
                continue
            df = fetch_bars(mt5, sym, tf)
            if df is not None:
                df, info = trim_backfill(df, sym, tf)
            if df is None or len(df) < 500:
                LOG.warning("%-7s %-3s : IGNORE (%s barres)", sym, tf,
                            0 if df is None else len(df))
                continue
            df.to_parquet(p, index=False)
            costs.setdefault(sym, {})[tf] = cost_row(sym, meta, df) | info
            n_ok += 1
            LOG.info("%-7s %-3s : %7d barres  %s -> %s  spread median %.2f bps",
                     sym, tf, len(df), df["time"].iloc[0].date(),
                     df["time"].iloc[-1].date(),
                     costs[sym][tf]["spread_median_bps"])

    C.costs_path().write_text(json.dumps(costs, indent=2), encoding="utf-8")
    LOG.info("ETAPE 1 terminee : %d couples (symbole, UT) disponibles", n_ok)
    mt5.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
