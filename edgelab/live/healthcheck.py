"""Contrôle de santé du livre live — une commande, tout ce qui peut clocher.

    py -3 -m edgelab.live.healthcheck              # tout sauf la fidélité des moteurs
    py -3 -m edgelab.live.healthcheck --verify     # + `verify` (lent, ~4 min)
    py -3 -m edgelab.live.healthcheck --no-mt5     # sans le terminal (code + config seuls)

Pourquoi ce fichier existe. `verify` répond à « le moteur live calcule-t-il la même chose
que le backtest ? ». Il ne répond PAS à « ce qui tourne est-il bien ce que je crois ? » —
et c'est là que ce projet s'est fait avoir plusieurs fois :

  * 2026-08-10 : deux EA étrangers (magic 111111, commentaire `[LONNY]`) traitaient sur le
    compte à côté du livre, réveillés par un simple `mt5.initialize()` qui relance le
    terminal avec son profil et AutoTrading actif ;
  * 2026-08-09 : le runner tournait sur du code antérieur au retrait de KELT, donc la pile
    réelle n'était pas celle que le wiki décrivait ;
  * 2026-08-11 : les magics 109/110 existaient dans `strategies` mais pas dans le journal.

Les contrôles ci-dessous sont donc tous du type « comparer deux sources qui doivent
s'accorder », jamais « lire une seule source et la croire ».
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent

OK, WARN, BAD = "  OK  ", " WARN ", " FAIL "
_state = {"fail": 0, "warn": 0}


def say(level: str, msg: str) -> None:
    if level is BAD:
        _state["fail"] += 1
    elif level is WARN:
        _state["warn"] += 1
    print(f"[{level}] {msg}")


def head(t: str) -> None:
    print("\n" + "=" * 92 + f"\n{t}\n" + "=" * 92)


# --------------------------------------------------------------------------- A. code
def check_code() -> dict:
    head("A. CODE")
    info = {}
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                             capture_output=True, text=True, timeout=20).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "edgelab"], cwd=ROOT,
                               capture_output=True, text=True, timeout=20).stdout.strip()
        behind = subprocess.run(["git", "rev-list", "--count", "HEAD..origin/main"],
                                cwd=ROOT, capture_output=True, text=True,
                                timeout=20).stdout.strip()
        info["commit"] = sha
        say(OK, f"commit {sha}")
        if dirty:
            say(WARN, f"edgelab/ a des modifications locales non commitées :\n        "
                      + "\n        ".join(dirty.splitlines()[:8]))
        else:
            say(OK, "edgelab/ propre (aucune modification locale)")
        if behind and behind != "0":
            say(BAD, f"le dépôt local est {behind} commit(s) DERRIÈRE origin/main "
                     f"-> `git fetch origin; git reset --hard origin/main`")
        else:
            say(OK, "à jour avec origin/main (ou origin non consulté)")
    except Exception as e:
        say(WARN, f"git indisponible : {e}")

    from edgelab.live.strategies import MAGIC
    from edgelab.live.summary import BRICK_LABEL, MAGIC_TAG
    miss = sorted(set(MAGIC.values()) - set(MAGIC_TAG))
    unlab = sorted(set(MAGIC_TAG.values()) - set(BRICK_LABEL))
    if miss or unlab:
        say(BAD, f"journal incomplet : magics sans tag {miss}, tags sans label {unlab}")
    else:
        say(OK, f"journal : les {len(MAGIC)} magics de strategies.MAGIC sont tous nommés")
    info["MAGIC"] = MAGIC
    return info


# ------------------------------------------------------------------------ B. config
def check_config() -> dict:
    head("B. CONFIGURATION")
    from edgelab.live.runner import _load_live_cfg
    from edgelab.live.strategies import MAGIC
    cfg = _load_live_cfg()

    live = bool(cfg.get("live_trading"))
    real = bool(cfg.get("allow_real_account"))
    say(OK if live else WARN, f"live_trading={live} (False = dry-run, aucun ordre envoyé)")
    say(BAD if real else OK, f"allow_real_account={real}"
                             + ("  <- GARDE-FOU DÉSACTIVÉ" if real else "  (garde dure)"))
    say(OK, f"risk_per_trade={100 * float(cfg['risk_per_trade']):.2f} %/trade  "
            f"| expect_server={cfg.get('expect_server')!r}")

    # quelles sleeves sont censées tourner, et sous quels magics
    # ⚠️ `on` doit dire ce que le RUNNER INSTANCIE, jamais ce que le livre contenait :
    # la brique 3 se retire par `crypto_symbols: []` (2026-08-18), et ce tableau la
    # declarait ACTIVE quoi qu il arrive -- donc il aurait affiche vert une brique que
    # le runner ne pilote plus, exactement le genre de desaccord que ce fichier existe
    # pour attraper.
    coins = [str(c).upper() for c in cfg.get("crypto_symbols", ["BTCUSD", "ETHUSD"])]
    want = {"brick1 NAS ORB": (MAGIC["nas_orb"], True, 1.0),
            "brick2 gold ToM": (MAGIC["gold_tom"], True, 1.0),
            "brick3 BTC": (MAGIC["btc_macd"], "BTCUSD" in coins,
                           float(cfg.get("crypto_size_R", 1.0))),
            "brick3 ETH": (MAGIC["eth_macd"], "ETHUSD" in coins,
                           float(cfg.get("crypto_size_R", 1.0))),
            "brick4 NAS IBS": (MAGIC["nas_ibs"], bool(cfg.get("enable_ibs", True)), 1.0),
            "HMASTO": (MAGIC["nas_hmasto"], bool(cfg.get("enable_hmasto", False)),
                       float(cfg.get("hmasto_size_R", 0.5)))}
    if cfg.get("enable_tlf", False):
        for sym in cfg.get("tlf_symbols", ["NAS100", "US500"]):
            m = MAGIC["nas_tlf"] if "NAS" in sym.upper() else MAGIC["spx_tlf"]
            want[f"TLF {sym}"] = (m, True, float(cfg.get("tlf_size_R", 0.5)))
    # RVWAP (111) / RSKEW (112). Sans elles ici, une position ouverte par une sleeve
    # bien vivante etait rapportee « MAGIC INCONNU ... <- ETRANGER AU LIVRE » par le
    # controle des positions -- l alerte qui doit signaler un EA etranger.
    if cfg.get("enable_research_sleeves", False):
        want[f"RVWAP {cfg.get('rvwap_symbol', 'GER40')}"] = (
            MAGIC["ger40_rvwap"], True, float(cfg.get("rvwap_size_R", 1.0)))
        want[f"RSKEW {cfg.get('rskew_symbol', 'US30')}"] = (
            MAGIC["us30_rskew"], True, float(cfg.get("rskew_size_R", 1.0)))
    print()
    for name, (m, on, size) in want.items():
        say(OK if on else WARN, f"{name:16s} magic {m:>3}  {'ACTIVE' if on else 'désactivée'}"
                                f"  taille {size:.2f}R")
    for dead, key in (("KAER", "enable_kaer"), ("KELT", "enable_keltner")):
        if cfg.get(key, False):
            say(WARN, f"{dead} : {key}=true mais le runner l'IGNORE (sleeve retirée) — "
                      f"mettre false pour éviter le warning au démarrage")

    # symbol_map complet pour tout ce qui est actif ?
    smap = cfg.get("symbol_map", {})
    need = {cfg.get("nas_symbol", "NAS100"), cfg.get("gold_symbol", "XAUUSD")}
    need |= set(cfg.get("crypto_symbols", []))
    if cfg.get("enable_hmasto"):
        need.add(cfg.get("hmasto_symbol", "NAS100"))
    if cfg.get("enable_tlf"):
        need |= set(cfg.get("tlf_symbols", []))
    if cfg.get("enable_research_sleeves"):
        need.add(cfg.get("rvwap_symbol", "GER40"))
        need.add(cfg.get("rskew_symbol", "US30"))
    missing = sorted(need - set(smap))
    say(BAD if missing else OK,
        f"symbol_map couvre les actifs actifs : {sorted(need)}"
        + (f"  <- MANQUE {missing}" if missing else ""))
    return {"cfg": cfg, "want": want}


# ------------------------------------------------------------------------ C. broker
def check_broker(want: dict, cfg: dict) -> None:
    head("C. TERMINAL, COMPTE, POSITIONS")
    try:
        import MetaTrader5 as mt5
    except Exception as e:
        say(WARN, f"MetaTrader5 indisponible ({e}) — contrôles broker sautés")
        return
    if not mt5.initialize():
        say(BAD, f"mt5.initialize() a échoué : {mt5.last_error()}")
        return
    try:
        a = mt5.account_info()
        exp = str(cfg.get("expect_server", ""))
        say(OK, f"compte {a.login} @ {a.server} ({a.company}) | {a.currency} "
                f"| balance {a.balance:.2f} | equity {a.equity:.2f} | levier 1:{a.leverage}")
        say(OK if exp.lower() in (a.server or "").lower() else BAD,
            f"serveur conforme à expect_server={exp!r}")
        say(OK if a.trade_mode == 0 else BAD,
            f"trade_mode={a.trade_mode} ({'DEMO' if a.trade_mode == 0 else 'CONCOURS/RÉEL'})")
        if not a.trade_allowed:
            say(BAD, "trade_allowed=False côté terminal (AutoTrading coupé ?)")

        known = {m: n for n, (m, on, _) in want.items() if on}
        allmag = {m for n, (m, on, _) in want.items()}

        # --- positions -----------------------------------------------------------
        pos = list(mt5.positions_get() or [])
        print()
        say(OK, f"{len(pos)} position(s) ouverte(s)")
        for p in pos:
            who = known.get(p.magic) or ("MAGIC INCONNU" if p.magic not in allmag
                                         else "sleeve désactivée")
            lvl = BAD if (p.magic not in allmag or p.sl == 0) else OK
            say(lvl, f"  {p.symbol:8s} magic {p.magic:<7} {who:22s} "
                     f"{'LONG ' if p.type == 0 else 'SHORT'} {p.volume:g} lots "
                     f"@{p.price_open:.2f} SL={p.sl:.2f}"
                     f"{'  <- SANS STOP !' if p.sl == 0 else ''}"
                     f"{'  <- ÉTRANGER AU LIVRE' if p.magic not in allmag else ''}")
        # --- ordres en attente ---------------------------------------------------
        ords = list(mt5.orders_get() or [])
        print()
        say(OK, f"{len(ords)} ordre(s) en attente")
        for o in ords:
            who = known.get(o.magic) or ("MAGIC INCONNU" if o.magic not in allmag
                                         else "sleeve désactivée")
            say(BAD if o.magic not in allmag else OK,
                f"  {o.symbol:8s} magic {o.magic:<7} {who:22s} type {o.type} "
                f"prix {o.price_open:.2f} SL={o.sl:.2f} vol {o.volume_current:g}"
                f"{'  <- ÉTRANGER AU LIVRE' if o.magic not in allmag else ''}")

        # --- deals récents, par magic -------------------------------------------
        since = datetime.now(timezone.utc) - timedelta(days=7)
        deals = list(mt5.history_deals_get(since, datetime.now(timezone.utc)) or [])
        by = {}
        for d in deals:
            if d.magic:
                by.setdefault(d.magic, []).append(d)
        print()
        say(OK, f"{len(deals)} deal(s) sur 7 jours, {len(by)} magic(s) distinct(s)")
        for m in sorted(by):
            who = known.get(m) or ("MAGIC INCONNU" if m not in allmag else "désactivée")
            pnl = sum(d.profit for d in by[m])
            say(BAD if m not in allmag else OK,
                f"  magic {m:<7} {who:22s} {len(by[m]):>3} deals  P&L {pnl:>+10.2f}"
                f"{'  <- ÉTRANGER AU LIVRE' if m not in allmag else ''}")
        silent = [n for n, (m, on, _) in want.items() if on and m not in by]
        if silent:
            say(WARN, "sleeves ACTIVES sans aucun deal sur 7 jours : " + ", ".join(silent)
                      + "  (normal si leur signal est rare — à recouper avec le journal)")
    finally:
        mt5.shutdown()


# ------------------------------------------------------------------------ E. runner
def check_runner(cfg: dict) -> None:
    """Le runner tourne-t-il VRAIMENT ? C'est la question que tout le reste presuppose.

    Le wiki enregistre deux fois « LE RUNNER N'EST TOUJOURS PAS LANCE » : un contrôle qui
    lit le compte, la config et le journal peut être entièrement vert alors que plus rien
    ne trade. Trois signaux indépendants, parce qu'aucun n'est suffisant seul :

      * le PROCESSUS (autorité, mais absent si le contrôle tourne sur une autre machine) ;
      * le BATTEMENT DE CŒUR `_out/heartbeat.txt`, ecrit a chaque passe (l'autorite locale) ;
      * les LOGS, purement informatifs : `one_pass` ne journalise que sur evenement, donc
        un marche calme laisse `runner.log` muet des heures sans que rien n'aille mal.
    """
    head("E. RUNNER")
    out = HERE / "_out"
    now = datetime.now().astimezone()

    # --- 1. le processus ---------------------------------------------------------
    procs = []
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name like 'python%'\" | "
             "Where-Object { $_.CommandLine -like '*edgelab.live.runner*' } | "
             "ForEach-Object { \"$($_.ProcessId)|$($_.CommandLine)\" }"],
            capture_output=True, text=True, timeout=30)
        procs = [x for x in (r.stdout or "").splitlines() if x.strip()]
    except Exception as e:
        say(WARN, f"impossible d'interroger les processus ({e})")
    if procs:
        for x in procs:
            pid = x.split("|", 1)[0]
            say(OK, f"processus runner VIVANT (pid {pid})")
    else:
        say(BAD, "AUCUN processus `edgelab.live.runner` sur cette machine "
                 "-> relancer `run_forever.ps1` (si le runner est sur un autre hote, "
                 "ignorer et lire les fraicheurs ci-dessous)")

    # --- 2. le battement de coeur : LA preuve de vie ------------------------------
    poll = float(cfg.get("poll_seconds", 20))
    budget = max(3.0 * poll / 60.0, 2.0)          # 3 passes, plancher 2 min
    hb = out / "heartbeat.txt"
    if not hb.exists():
        say(WARN, f"heartbeat.txt absent de {out} — runner sur un autre hote, ou "
                  f"version anterieure au 2026-08-11 (relancer le runner pour l'obtenir)")
    else:
        mins = (now - datetime.fromtimestamp(hb.stat().st_mtime).astimezone()
                ).total_seconds() / 60.0
        say(OK if mins <= budget else BAD,
            f"heartbeat ecrit il y a {mins:.1f} min (budget {budget:.1f} min = 3 passes)")
        for line in hb.read_text(encoding="utf-8", errors="replace").splitlines():
            print(f"            {line}")

    # --- 3. les logs : INFORMATIFS, jamais un echec -------------------------------
    # `runner.log` n'est PAS une preuve de vie : one_pass ne journalise que sur evenement
    # (ordre, marche ferme, echec), donc un marche calme le laisse muet des heures alors
    # que la boucle tourne. Traiter sa fraicheur comme un critere a produit un FAIL sur un
    # runner parfaitement vivant le 2026-08-11 — d'ou le heartbeat ci-dessus.
    for name in ("runner.log", "supervisor.log"):
        f = out / name
        if not f.exists():
            say(WARN, f"{name} absent de {out} (runner sur un autre hote ?)")
            continue
        mins = (now - datetime.fromtimestamp(f.stat().st_mtime).astimezone()
                ).total_seconds() / 60.0
        say(OK, f"{name} ecrit il y a {mins:.1f} min (informatif : ce log ne parle que "
                f"sur evenement, le silence est normal)")
        if name == "runner.log":
            try:
                for t in f.read_text(encoding="utf-8",
                                     errors="replace").splitlines()[-3:]:
                    print(f"            {t[:150]}")
            except Exception:
                pass


# ----------------------------------------------------------------------- D. journal
def check_journal() -> None:
    head("D. JOURNAL DE TRADES")
    from edgelab.live.summary import DEFAULT_CSV, _brick
    import csv
    if not Path(DEFAULT_CSV).exists():
        say(WARN, f"pas de journal à {DEFAULT_CSV} (normal si le runner tourne ailleurs)")
        return
    rows = list(csv.DictReader(open(DEFAULT_CSV, newline="", encoding="utf-8")))
    if not rows:
        say(WARN, "journal vide")
        return
    say(OK, f"{len(rows)} lignes | de {rows[0].get('time', '?')[:19]} "
            f"à {rows[-1].get('time', '?')[:19]}")
    per = {}
    for r in rows:
        if r.get("event") == "exit" and r.get("R"):
            per.setdefault(_brick(r.get("symbol", ""), r.get("reason", "")), []).append(
                float(r["R"]))
    for k, v in sorted(per.items()):
        say(OK, f"  {k:52s} {len(v):>4} trades  somme {sum(v):>+8.2f} R")
    unknown = [r for r in rows if r.get("event") == "exit"
               and _brick(r.get("symbol", ""), r.get("reason", "")) == "?"]
    say(BAD if unknown else OK,
        f"lignes de sortie non attribuables : {len(unknown)}")
    # Chronologie : le runner ecrit en append, donc un horodatage qui RECULE veut dire
    # qu'une ligne n'a pas ete produite par lui -- typiquement un test en dry-run rejoue
    # sur des barres historiques. C'est exactement ce qui a pollue ce journal le
    # 2026-08-11 (3 lignes `stop_order` datees de juin/juillet, retirees depuis).
    times = [r.get("time", "") for r in rows]
    back = [(a, b) for a, b in zip(times, times[1:]) if b and a and b < a]
    say(WARN if back else OK,
        f"chronologie : {len(back)} recul(s) d'horodatage"
        + (f"  <- lignes non ecrites par le runner ? ex. {back[0][0][:19]} -> "
           f"{back[0][1][:19]}" if back else ""))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true", help="+ verify (lent)")
    ap.add_argument("--no-mt5", action="store_true")
    a = ap.parse_args()

    # le VPS sort en cp1252 : sans ça un simple accent fait planter le contrôle lui-même
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    print(f"CONTROLE DE SANTE DU LIVRE LIVE - {datetime.now():%Y-%m-%d %H:%M:%S}")
    check_code()
    c = check_config()
    if not a.no_mt5:
        check_broker(c["want"], c["cfg"])
    check_runner(c["cfg"])
    check_journal()

    if a.verify:
        head("F. FIDELITE DES MOTEURS (verify)")
        r = subprocess.run([sys.executable, "-m", "edgelab.live.verify"], cwd=ROOT)
        say(OK if r.returncode == 0 else BAD, f"verify exit={r.returncode}")
    else:
        head("F. FIDELITE DES MOTEURS")
        say(WARN, "non execute - relancer avec --verify (~4 min) apres tout "
                  "changement de regle, de bracket ou de moteur")

    head("VERDICT")
    print(f"  {_state['fail']} FAIL, {_state['warn']} WARN")
    print("  " + ("TOUT EST EN PLACE" if _state["fail"] == 0 else
                  "À CORRIGER AVANT DE LAISSER TOURNER"))
    return 1 if _state["fail"] else 0


if __name__ == "__main__":
    sys.exit(main())
