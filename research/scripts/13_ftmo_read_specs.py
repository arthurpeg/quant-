"""ETAPE 13 -- LECTURE SEULE des specs FTMO manquantes.

    python research/scripts/13_ftmo_read_specs.py

Ce script ne passe AUCUN ordre et ne modifie RIEN. Il n'appelle que
`symbol_info`, `symbol_info_tick`, `copy_rates_range`, `account_info`,
`orders_get`, `positions_get` -- toutes des lectures.

TROIS GARDE-FOUS, dont deux imposes par le journal du depot.

1. IL VERIFIE QUE LE TERMINAL EST BIEN FTMO avant de lire quoi que ce soit, et
   s'arrete sinon. Les taux Pepperstone et FTMO different et les confondre a
   deja coute une analyse ici.
2. IL RELEVE LES ORDRES ET POSITIONS AVANT ET APRES. Le journal du 2026-08-10
   enregistre qu'un `mt5.initialize()` peut RELANCER le terminal et reveiller
   des EA endormis (magic 111111 / [LONNY]) sur le compte ou le book est
   deploye. Le terminal etant deja ouvert ici, le risque est faible -- on
   verifie quand meme, parce que c'est la regle.
3. LE SPREAD EST MESURE PAR LA MEME METHODE QUE CHEZ PEPPERSTONE : mediane des
   spreads NON NULS des barres H1 en heures liquides (07h-20h serveur). Un 0
   imprime est une cotation manquante, pas un spread nul ; et sans la meme
   methode des deux cotes, la comparaison ne veut rien dire.

CE QU'IL VA CHERCHER, ET POURQUOI :
  * `GER40.cash`  -> le SPREAD, seule donnee manquante pour trancher la
                     candidature GER40 (etape 9 : <= 18 pts il ameliore le book,
                     >= 27 pts il est a ecarter).
  * `UK100.cash`  -> le SWAP, jamais releve : 6 cellules de la shortlist ont ete
  * `GBPJPY`         ecartees faute de ce taux (etape 12).
  * les autres    -> re-verification des taux du 2026-08-10.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C

LOG = C.get_logger("13_ftmo")

BANK_YEAR = 360.0
LIQ0, LIQ1 = 7 * 60, 20 * 60

# nom logique -> candidats de nom FTMO, dans l'ordre d'essai
WANT = {
    "GER40":  ["GER40.cash", "GER40", "DE40.cash", "DE40"],
    "UK100":  ["UK100.cash", "UK100", "UK100.cfd"],
    "GBPJPY": ["GBPJPY"],
    "US30":   ["US30.cash", "US30"],
    "US100":  ["US100.cash", "US100", "NAS100"],
    "US500":  ["US500.cash", "US500"],
    "XAUUSD": ["XAUUSD"],
}
SWAP_MODE = {0: "DISABLED", 1: "POINTS", 2: "CURRENCY_SYMBOL",
             3: "CURRENCY_MARGIN", 4: "CURRENCY_DEPOSIT",
             5: "INTEREST_CURRENT (% annuel du prix)", 6: "INTEREST_OPEN",
             7: "REOPEN_CURRENT", 8: "REOPEN_BID"}
DAY = {0: "dimanche", 1: "lundi", 2: "mardi", 3: "mercredi", 4: "jeudi",
       5: "vendredi", 6: "samedi"}


def main() -> int:
    import MetaTrader5 as mt5
    if not mt5.initialize():
        LOG.error("MT5 initialize a echoue : %s", mt5.last_error())
        return 1

    a = mt5.account_info()
    LOG.info("=" * 96)
    LOG.info("TERMINAL : compte %s | serveur %s | societe %s | devise %s",
             a.login, a.server, a.company, a.currency)
    is_ftmo = "ftmo" in (a.company or "").lower() or "ftmo" in (a.server or "").lower()
    if not is_ftmo:
        LOG.error("CE N'EST PAS UN TERMINAL FTMO (%s / %s) -- lecture annulee, "
                  "les taux ne seraient pas ceux du book.", a.company, a.server)
        mt5.shutdown()
        return 1
    LOG.info("FTMO confirme. Lecture seule ; aucun ordre ne sera passe.")

    o0 = mt5.orders_get() or ()
    p0 = mt5.positions_get() or ()
    LOG.info("ETAT AVANT : %d ordre(s) en attente, %d position(s) ouverte(s)",
             len(o0), len(p0))
    for x in p0:
        LOG.info("   position %s %s vol %.2f magic %d", x.symbol,
                 "BUY" if x.type == 0 else "SELL", x.volume, x.magic)
    for x in o0:
        LOG.info("   ordre    %s magic %d ticket %d", x.symbol, x.magic, x.ticket)

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=400)
    out = {}

    LOG.info("-" * 96)
    LOG.info("%-8s %-12s %8s %7s %8s %9s %9s %6s %5s %9s", "logique", "symbole",
             "point", "digits", "spr_med", "swapL", "swapS", "mode", "3j", "prix")
    for logical, names in WANT.items():
        si = None
        for nm in names:
            mt5.symbol_select(nm, True)
            si = mt5.symbol_info(nm)
            if si is not None:
                break
        if si is None:
            LOG.warning("%-8s : introuvable (essaye : %s)", logical, ", ".join(names))
            continue

        r = mt5.copy_rates_range(si.name, mt5.TIMEFRAME_H1, start, end)
        floor = np.nan
        px = float(si.bid or si.ask or np.nan)
        zero_frac = np.nan
        if r is not None and len(r):
            df = pd.DataFrame(r)
            t = pd.to_datetime(df["time"], unit="s")
            tod = t.dt.hour * 60 + t.dt.minute
            sp = df["spread"].to_numpy(float)[(tod >= LIQ0) & (tod < LIQ1)]
            nz = sp[sp > 0]
            floor = float(np.median(nz)) if nz.size else float(si.spread)
            zero_frac = float((sp == 0).mean()) if sp.size else np.nan
            px = float(np.median(df["close"].to_numpy(float)))

        pt = float(si.point)
        # swap -> % annuel du prix, selon le mode declare
        if int(si.swap_mode) == 1:            # POINTS
            # points/nuit -> % ANNUEL du prix. La taille du contrat se simplifie
            # (le swap est par lot, le notionnel aussi). Le `* 100` final est le
            # passage en POURCENT -- l'oublier donne un taux 100 fois trop petit,
            # ce qui a d'abord fait lire "+0,07 %/an" la ou GER40 en paie 6,6.
            sl_pct = -si.swap_long * pt / px * BANK_YEAR * 100.0
            ss_pct = -si.swap_short * pt / px * BANK_YEAR * 100.0
        elif int(si.swap_mode) == 5:          # deja en % annuel
            sl_pct, ss_pct = -float(si.swap_long), -float(si.swap_short)
        else:
            sl_pct = ss_pct = float("nan")

        out[logical] = dict(
            broker_symbol=si.name, point=pt, digits=int(si.digits),
            spread_floor_pts=floor, spread_zero_frac=zero_frac,
            spread_current_pts=int(si.spread), median_price=px,
            spread_bps=floor * pt / px * 1e4 if np.isfinite(floor) else None,
            swap_long_raw=float(si.swap_long), swap_short_raw=float(si.swap_short),
            swap_mode=int(si.swap_mode), swap_long_pct=sl_pct, swap_short_pct=ss_pct,
            triple_day=int(si.swap_rollover3days),
            trade_calc_mode=int(si.trade_calc_mode),
            trade_tick_value=float(si.trade_tick_value),
            contract=float(si.trade_contract_size))
        LOG.info("%-8s %-12s %8.5f %7d %8.1f %9.2f %9.2f %6d %5s %9.2f",
                 logical, si.name, pt, si.digits, floor, si.swap_long,
                 si.swap_short, si.swap_mode, DAY.get(si.swap_rollover3days, "?")[:3],
                 px)

    LOG.info("-" * 96)
    LOG.info("SWAP CONVERTI EN %% ANNUEL DU PRIX (positif = on paie)")
    for k, v in out.items():
        LOG.info("   %-8s (%-11s) mode %-32s long %+7.2f %%/an  court %+7.2f %%/an",
                 k, v["broker_symbol"], SWAP_MODE.get(v["swap_mode"], "?"),
                 v["swap_long_pct"], v["swap_short_pct"])

    LOG.info("-" * 96)
    LOG.info("SPREAD MESURE (mediane des NON NULS, heures liquides, 400 j de H1)")
    pep = json.loads(C.costs_path().read_text(encoding="utf-8"))
    for k, v in out.items():
        pv = pep.get(k, {}).get("H1")
        ref = f"{pv['spread_floor_pts']:.1f} pts / {pv['spread_bps']:.3f} bps" \
            if pv else "n.d."
        LOG.info("   %-8s FTMO %6.1f pts = %6.3f bps (%.0f %% de zeros) | "
                 "Pepperstone %s", k, v["spread_floor_pts"],
                 v["spread_bps"] or float("nan"), 100 * (v["spread_zero_frac"] or 0),
                 ref)

    o1 = mt5.orders_get() or ()
    p1 = mt5.positions_get() or ()
    LOG.info("-" * 96)
    LOG.info("ETAT APRES : %d ordre(s), %d position(s) -- %s", len(o1), len(p1),
             "INCHANGE" if (len(o1) == len(o0) and len(p1) == len(p0))
             else "⚠️ CHANGEMENT DETECTE, verifier immediatement")

    (C.DATA / "ftmo_specs.json").write_text(json.dumps(out, indent=1),
                                            encoding="utf-8")
    LOG.info("specs -> research/data/ftmo_specs.json")
    mt5.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
