"""A-t-on ouvert CETTE position pour la bonne raison ? — audit d'une entree research.

    py -3 -m edgelab.live.audit_position            # les positions ouvertes 111 / 112
    py -3 -m edgelab.live.audit_position --magic 112
    py -3 -m edgelab.live.audit_position --days 3   # + les entrees fermees des 3 jours

POURQUOI CE FICHIER EXISTE. `verify` prouve que le moteur live calcule comme le backtest,
et `check_live_parity_research.py` le prouve sur 400 trades rejoues. Aucun des deux ne
repond a « CETTE position-la, ouverte pendant que le runner redemarrait, est-elle celle
que la regle demandait ? ». C'est une question sur un EVENEMENT, pas sur du code, et elle
se pose exactement quand on ne peut pas se fier au deroulement normal : au demarrage,
apres un crash, ou quand le terminal a servi une frame incomplete.

LE DEFAUT QUE CET AUDIT CHERCHE EN PREMIER. Le 2026-08-18 au demarrage sur le VPS, le
terminal a servi a RVWAP une frame **tronquee d'une heure** (symbole fraichement ajoute au
Market Watch, historique encore en telechargement), corrigee 21 s plus tard. Une frame
courte ne leve aucune erreur : elle donne un rang causal calcule sur MOINS d'occurrences,
donc un autre quantile, donc une entree que le backtest n'aurait pas prise. C'est pourquoi
l'audit ne se contente pas de dire « la regle etait vraie » : il REJOUE la decision sur des
fenetres volontairement raccourcies. Si l'entree disparait a fenetre pleine mais apparait a
fenetre courte, on tient le coupable.

CE QUE L'AUDIT COMPARE. Aucune de ces valeurs n'est relue du runner : toutes sont
re-derivees des barres du broker et de `research_sleeves.decide`, la fonction PARTAGEE avec
le backtest — un audit qui relirait la trace du runner ne ferait que le croire sur parole.

  1. la barre de DECISION = la derniere barre complete avant l'ouverture de la position ;
  2. `decide()` sur la fenetre de `*_bars` barres finissant sur cette barre : y a-t-il un
     signal, et dans quel SENS ;
  3. la distance de stop 1R = k_stop x ATR14, lue A LA BARRE DE SIGNAL ;
  4. le DELAI entre la cloture de la barre de decision et l'ouverture reelle : au-dela de
     `*_max_bar_age_min`, le fill n'est plus celui que le backtest mesure ;
  5. le nombre d'OCCURRENCES du signal dans la fenetre (le mode de panne silencieux) ;
  6. la sensibilite a la longueur de fenetre (1/2, 1/4) : l'entree tient-elle debout ?

Sortie : une ligne [ OK ] / [FAIL] par point, et un compte de FAIL a la fin.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

OK, BAD, WARN = "  OK  ", " FAIL ", " WARN "
_state = {"fail": 0, "warn": 0}


def say(level: str, msg: str) -> None:
    if level is BAD:
        _state["fail"] += 1
    elif level is WARN:
        _state["warn"] += 1
    print(f"[{level}] {msg}")


def _sleeve_of(magic: int, cfg: dict):
    """(nom, params dimensionnes par la config, symbole logique, fenetre, age max)."""
    import dataclasses as dc

    from edgelab.intraday.research_sleeves import SLEEVES
    from edgelab.live.strategies import MAGIC
    name = "RVWAP" if magic == MAGIC["ger40_rvwap"] else "RSKEW"
    key = name.lower()
    base = SLEEVES[name]
    p = dc.replace(base, size_R=float(cfg.get(key + "_size_R", 1.0)))
    return (name, p,
            cfg.get(key + "_symbol", base.symbol),
            int(cfg.get(key + "_bars", 5000 if name == "RVWAP" else 1500)),
            float(cfg.get(key + "_max_bar_age_min", 20 if name == "RVWAP" else 60)))


def audit(broker, cfg: dict, magic: int, symbol: str, direction: int, lots: float,
          entry_price: float, sl: float, open_time: pd.Timestamp, what: str) -> None:
    from edgelab.intraday.research_sleeves import decide, signal_series

    name, p, logical, n_win, max_age = _sleeve_of(magic, cfg)
    step = pd.Timedelta(minutes=p.bar_minutes)
    print("\n" + "-" * 92)
    print(f"{what} | {name} magic {magic} | {symbol} "
          f"{'LONG' if direction > 0 else 'SHORT'} {lots:g} lots @{entry_price:.2f} "
          f"SL={sl:.2f} | ouverte {open_time}")
    print("-" * 92)

    # --- 1. la barre de decision -------------------------------------------------
    # L'entree est au marche JUSTE APRES la cloture de la barre de signal : la barre de
    # decision est celle qui PRECEDE DANS L'INDEX celle ou tombe l'ouverture.
    # ⚠️ Deux pieges, tous deux attrapes par le temoin backtest le 2026-08-18 :
    #   * `.floor(step)` arrondit sur la grille de l'EPOCH, ou les barres H4 ne sont
    #     jamais (01/05/09... l'ete, 02/06/10... l'hiver en UTC vraie) ;
    #   * `entry_bar - step` suppose des barres CONTIGUES, et les flux ont des trous
    #     (GER40 n'a pas de barre 23:00, donc la barre avant 00:00 est celle de 21:00).
    # On lit donc l'index, et rien d'autre.
    bars_all = broker.get_bars(logical, p.timeframe, n_win + 500)
    j = int(bars_all.index.searchsorted(pd.Timestamp(open_time), side="right")) - 1
    if j < 1:
        say(BAD, f"ouverture {open_time} hors de la frame du broker "
                 f"({bars_all.index[0]} -> {bars_all.index[-1]}) — audit impossible")
        return
    i = j - 1
    dec_bar, entry_ts = bars_all.index[i], bars_all.index[j]
    # DEUX RETARDS DIFFERENTS, et les confondre fait crier a tort. Le TROU DE SEANCE
    # (GER40 ne cote pas de 20:00 a 23:00 UTC, et il y a les week-ends) separe la cloture
    # de la barre de signal de l'ouverture de la suivante : il est structurel, et c'est
    # justement lui qui fait SAUTER le signal en live (`age > *_max_bar_age_min`) alors
    # que le backtest, lui, entre a la barre suivante de l'INDEX quoi qu'il arrive. La
    # CHASSE, elle, est le retard du fill sur l'ouverture de la barre d'entree : c'est
    # elle qui dit si le runner a couru apres un prix qu'il aurait du laisser passer.
    gap = (entry_ts - (dec_bar + step)).total_seconds() / 60.0
    chase = (open_time - entry_ts).total_seconds() / 60.0
    say(OK if chase <= max_age else BAD,
        f"barre de decision {dec_bar} -> barre d'entree {entry_ts}, fill {chase:.1f} min "
        f"apres son ouverture (plafond {max_age:.0f})")
    if gap > 1.0:
        say(WARN, f"trou de seance de {gap:.0f} min entre la cloture de la barre de signal "
                  f"et la barre d'entree : EN LIVE le runner saute ce signal "
                  f"(age > {max_age:.0f} min) — une position ici sort de la regle live, "
                  f"meme si le backtest la prend")

    # --- 2. la fenetre EXACTE que le runner a vue --------------------------------
    win = bars_all.iloc[max(0, i + 1 - n_win): i + 1]
    say(OK if len(win) == n_win else WARN,
        f"fenetre rejouee : {len(win)} barres (config {n_win}) finissant sur {win.index[-1]}")

    # --- 3. occurrences : le mode de panne silencieux ----------------------------
    occ = int(np.isfinite(signal_series(win, p)).sum())
    say(OK if occ >= p.rank_win else BAD,
        f"occurrences du signal dans la fenetre : {occ} (requis {p.rank_win}, "
        f"plancher {p.rank_min}) -> marge x{occ / p.rank_win:.2f}")

    # --- 4. la regle disait-elle d'entrer, et dans quel sens ? -------------------
    got = decide(win, p)
    if got is None:
        say(BAD, "decide() ne demandait AUCUNE entree sur cette barre -> position NON "
                 "EXPLIQUEE par la regle")
    else:
        side, dist = got
        say(OK if side == direction else BAD,
            f"sens : regle {'LONG' if side > 0 else 'SHORT'} vs position "
            f"{'LONG' if direction > 0 else 'SHORT'}")
        ref = float(win["close"].iloc[-1])
        want_sl = ref - side * dist
        drift = abs(sl - want_sl) / dist if dist else float("inf")
        if np.isfinite(sl) and sl:
            say(OK if drift <= 0.10 else BAD,
                f"stop : 1R = {p.k_stop:g} x ATR14 = {dist:.2f} -> SL attendu "
                f"{want_sl:.2f} (ref = cloture {ref:.2f}), SL reel {sl:.2f}, "
                f"ecart {drift * 100:.1f} % de 1R")
        slip = abs(entry_price - ref) / dist if dist else float("inf")
        say(OK if slip <= 0.25 else WARN,
            f"prix d'entree {entry_price:.2f} vs cloture de la barre de signal "
            f"{ref:.2f} -> {slip * 100:.1f} % de 1R (ordre au marche : un ecart "
            f"modeste est normal)")

    # --- 5. l'entree survit-elle a une fenetre RACCOURCIE ? ---------------------
    print("        sensibilite a la longueur de fenetre (une entree qui n'existe QU'a "
          "fenetre courte est un artefact) :")
    for frac in (1.0, 0.5, 0.25):
        w = win.iloc[-max(1, int(len(win) * frac)):]
        o = int(np.isfinite(signal_series(w, p)).sum())
        g = decide(w, p)
        verdict = "aucune entree" if g is None else \
            f"{'LONG' if g[0] > 0 else 'SHORT'} 1R={g[1]:.2f}"
        print(f"          {int(frac * 100):>3} % = {len(w):>5} barres, "
              f"{o:>5} occ -> {verdict}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Audit d'une entree des sleeves research.")
    ap.add_argument("--magic", type=int, default=None, help="n'auditer que ce magic")
    ap.add_argument("--days", type=float, default=0.0,
                    help="auditer aussi les entrees FERMEES des N derniers jours")
    a = ap.parse_args()

    from edgelab.live.broker import Broker, server_epoch_to_utc
    from edgelab.live.runner import _load_live_cfg
    from edgelab.live.strategies import MAGIC

    cfg = _load_live_cfg()
    magics = [a.magic] if a.magic else [MAGIC["ger40_rvwap"], MAGIC["us30_rskew"]]
    broker = Broker(cfg)
    broker.connect()
    import MetaTrader5 as mt5

    seen = 0
    for m in magics:
        pos = broker.open_position(m)
        if pos is not None:
            seen += 1
            audit(broker, cfg, m, pos.symbol, pos.direction, pos.lots, pos.entry_price,
                  pos.sl, pos.open_time, "POSITION OUVERTE")
        else:
            print(f"\n(magic {m} : aucune position ouverte)")
        if a.days > 0:
            now = datetime.now(timezone.utc)
            deals = [d for d in (mt5.history_deals_get(now - timedelta(days=a.days), now) or [])
                     if d.magic == m and d.entry == mt5.DEAL_ENTRY_IN]
            for d in deals:
                seen += 1
                audit(broker, cfg, m, broker._logical_of(d.symbol),
                      1 if d.type == mt5.DEAL_TYPE_BUY else -1, d.volume, d.price,
                      float("nan"), server_epoch_to_utc(d.time), f"DEAL {d.ticket}")

    print("\n" + "=" * 92)
    if not seen:
        print("Rien a auditer.")
    else:
        print(f"{seen} entree(s) auditee(s) | {_state['fail']} FAIL | {_state['warn']} WARN")
        print("Un FAIL sur le SENS, le STOP ou la REGLE veut dire que la position n'est "
              "pas celle du backtest — la fermer est alors une decision a prendre.")
    mt5.shutdown()
    return 1 if _state["fail"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
