"""Rattrape dans le journal les trades que le driver n'a pas écrits.

    py -3 -m edgelab.live.backfill --days 7           # aperçu, n'écrit rien
    py -3 -m edgelab.live.backfill --days 7 --write   # injecte les lignes manquantes

POURQUOI. Jusqu'au 2026-08-11 le driver n'écrivait une ligne `exit` que lorsqu'il fermait
lui-même. Quand le stop ou la cible du broker partait côté serveur, la position
disparaissait simplement entre deux passes : aucune ligne, aucun R, trade absent du
journal, de `summary` et du rapport Discord. Le biais n'était pas neutre — **un stop
touché vaut toujours −1 R, donc le journal ne perdait que des PERTES**.

`Broker.reconcile_closures()` corrige le flux à partir de maintenant, mais il ne peut
rien pour les fermetures déjà passées. Ce module relit l'historique MT5, apparie les
deals par `position_id` et injecte ce qui manque.

IDEMPOTENT : une position dont le ticket figure déjà dans le journal est ignorée, donc on
peut le relancer sans risque de doubler quoi que ce soit.
"""
from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

DEFAULT_CSV = Path(__file__).resolve().parent / "_out" / "trades.csv"
FIELDS = ["time", "event", "symbol", "dir", "lots", "price", "sl", "tp", "reason",
          "R", "cumR", "ticket"]


def _server_epoch_to_utc(ts: int):
    """MT5 estampille en heure SERVEUR (EET/EEST) mais renvoie un epoch : on réinterprète."""
    import pandas as pd
    naive = pd.Timestamp(ts, unit="s")
    return (naive.tz_localize("Europe/Athens", ambiguous="NaT", nonexistent="NaT")
            .tz_convert("UTC"))


def scan(days: int, magics) -> list:
    """-> [(position_id, dict de la ligne exit, dict de la ligne enter | None)]"""
    import MetaTrader5 as mt5
    import pandas as pd
    if not mt5.initialize():
        raise RuntimeError(f"MT5 initialize: {mt5.last_error()}")
    try:
        now = datetime.now(timezone.utc)
        # fenêtre large et en heure SERVEUR : `history_deals_get` n'interprète pas les
        # fuseaux, et une fenêtre calée sur UTC rate les deals des dernières heures.
        deals = mt5.history_deals_get(now - timedelta(days=days + 2),
                                      now + timedelta(days=2)) or []
        by_pos = {}
        for d in deals:
            if d.magic in magics:
                by_pos.setdefault(d.position_id, []).append(d)
        out = []
        for pid, ds in by_pos.items():
            ins = [x for x in ds if x.entry == 0]
            outs = [x for x in ds if x.entry == 1]
            if not ins or not outs:
                continue                       # position encore ouverte
            i = sorted(ins, key=lambda x: x.time)[0]
            o = sorted(outs, key=lambda x: x.time)[-1]
            direction = -1 if i.type == 1 else 1
            # 1R : le journal ne le porte pas, on le relit sur l'ordre d'origine
            sl = 0.0
            for oo in (mt5.history_orders_get(position=pid) or []):
                if oo.sl:
                    sl = float(oo.sl)
                    break
            dist = abs(float(i.price) - sl) if sl else 0.0
            R = (direction * (float(o.price) - float(i.price)) / dist) if dist else None
            tag = str(i.comment or "").split("_")[0].split(":")[0]
            reason = str(o.comment or "broker_exit").strip() or "broker_exit"
            enter = dict(time=_server_epoch_to_utc(i.time).isoformat(), event="enter",
                         symbol=i.symbol, dir=direction, lots=i.volume,
                         price=round(float(i.price), 5), sl=round(sl, 5) if sl else "",
                         tp="", reason=str(i.comment or ""), R="", cumR="", ticket=pid)
            exit_ = dict(time=_server_epoch_to_utc(o.time).isoformat(), event="exit",
                         symbol=o.symbol, dir=direction, lots=o.volume,
                         price=round(float(o.price), 5), sl="", tp="",
                         reason=f"{tag}:{reason}" if tag else reason,
                         R=(round(R, 3) if R is not None else ""), cumR="", ticket=pid)
            out.append((pid, exit_, enter))
        return sorted(out, key=lambda x: x[1]["time"])
    finally:
        mt5.shutdown()


def existing_tickets(path: Path) -> set:
    if not path.exists():
        return set()
    with open(path, newline="", encoding="utf-8") as fh:
        return {str(r.get("ticket", "")).strip()
                for r in csv.DictReader(fh) if r.get("ticket")}


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--write", action="store_true", help="sans ce drapeau, rien n'est écrit")
    ap.add_argument("--csv", default=str(DEFAULT_CSV))
    a = ap.parse_args()

    from edgelab.live.strategies import MAGIC
    magics = set(MAGIC.values())
    path = Path(a.csv)
    have = existing_tickets(path)
    rows = scan(a.days, magics)

    missing = [(pid, ex, en) for pid, ex, en in rows if str(pid) not in have]
    print(f"journal   : {path}")
    print(f"positions fermées trouvées sur {a.days} j : {len(rows)}")
    print(f"déjà dans le journal                      : {len(rows) - len(missing)}")
    print(f"MANQUANTES                                : {len(missing)}\n")
    if not missing:
        print("rien à injecter.")
        return 0
    for pid, ex, en in missing:
        print(f"  {ex['time'][:19]}  {ex['symbol']:7s} {'SHORT' if ex['dir'] < 0 else 'LONG '} "
              f"{ex['lots']:g} @ {ex['price']:.2f}  R={ex['R']}  '{ex['reason']}'  ticket {pid}")
    if not a.write:
        print("\n(aperçu — relancer avec --write pour injecter)")
        return 0

    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction="ignore")
        if new:
            w.writeheader()
        for pid, ex, en in missing:
            w.writerow(en)
            w.writerow(ex)
    print(f"\n{len(missing)} trade(s) injecté(s) ({2 * len(missing)} lignes).")
    print("⚠️ Les lignes sont AJOUTÉES à la fin, donc le journal n'est plus trié par date.")
    print("   `summary` et le rapport lisent par ligne, pas par ordre — sans effet sur eux.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
