"""The single event loop that schedules the three bricks on one shared account.

Dry-run by default (see config_live.yaml): connects to MT5 for Pepperstone bars, logs
the orders it WOULD place, and paper-tallies realised R. One shared LiveRiskManager
gates every entry against the static-DD prop rules.

Usage (from repo root):
    python -m edgelab.live.runner              # continuous loop
    python -m edgelab.live.runner --once       # one evaluation pass then exit (cron/testing)
    python -m edgelab.live.runner --status      # print account/positions and exit
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pandas as pd
import yaml

EXIT_ACCOUNT_FAILED = 42   # supervisor uses this to STOP restarting (don't loop a blown account)
EXIT_UPDATE = 75           # a newer commit is on origin/main -> supervisor git-pulls + relaunches
REPO_ROOT = Path(__file__).resolve().parents[2]   # the git repo root (…/edgelab/live/runner.py)

from edgelab.config import load_config, risk_for
from edgelab.risk.propfirm import PropFirmRules
from edgelab.live.broker import Broker, MarketClosed
from edgelab.live.risk import LiveRiskManager
from edgelab.live.strategies import (NasOrbStrategy, GoldTomStrategy, CryptoMacdStrategy,
                                    ResearchSleeveStrategy,
                                     NasIbsStrategy, HmaStochStrategy,
                                     TwoLegFadeStrategy)
# KaerStrategy is deliberately NOT imported: KAER was replaced by HMASTO in the live
# forward-test slot on 2026-08-10 (same family, corr +0.335). The class stays in
# strategies.py for research and `verify`; importing it here would only make it easy to
# re-wire a sleeve that must not run alongside HMASTO.
# KeltnerStrategy is deliberately NOT imported: KELT was retired from the live book on
# 2026-08-09 (see build_stack below). The class itself still lives in strategies.py.

LOG = logging.getLogger("edgelab.live.runner")
CFG_LIVE = Path(__file__).resolve().parent / "config_live.yaml"


def _load_live_cfg() -> dict:
    with open(CFG_LIVE, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def build(cfg_live: dict):
    main_cfg = load_config()
    # brick 3 uses the widened crypto exits (config.yaml `crypto_risk:`), not the
    # framework defaults - the backtest reads the same block, so they cannot fork.
    risk_cfg = risk_for(main_cfg, "crypto")
    rules = PropFirmRules.from_config(cfg_live["propfirm"])
    broker = Broker(cfg_live)
    risk = LiveRiskManager(rules, float(cfg_live["risk_per_trade"]))
    strategies = [NasOrbStrategy(cfg_live), GoldTomStrategy(cfg_live)]
    for coin in cfg_live.get("crypto_symbols", ["BTCUSD", "ETHUSD"]):
        strategies.append(CryptoMacdStrategy(cfg_live, coin, risk_cfg))
    if cfg_live.get("enable_ibs", True):          # brick 4 (exp-009); set false to disable
        strategies.append(NasIbsStrategy(cfg_live))
    # FORWARD-TEST SLEEVE, not a brick: NAS100 M15 HMA/EMA cross + 3 oscillators, half
    # size. Defaults to OFF so a plain checkout keeps trading the frozen 4-brick book; the
    # demo runner enables it in config_live.yaml. See edgelab/intraday/hma_stoch.py.
    if cfg_live.get("enable_hmasto", False):
        strategies.append(HmaStochStrategy(cfg_live))
    # FORWARD-TEST SLEEVE, not a brick: TLF (Two-Leg Fade), M5, SHORT-ONLY, one instance
    # per symbol (NAS100 magic 109, US500 magic 110), half size. Deployed 2026-08-10 on
    # the user's explicit instruction. Defaults to OFF so a plain checkout keeps trading
    # the frozen book. The bar SELECTION is Brooks'; the DIRECTION is the opposite of his
    # (his direction measures -0.022 R, the selection +0.113 R at p=0.000) — which is why
    # it is called Two-Leg Fade and not "Brooks". See edgelab/intraday/two_leg_fade.py.
    if cfg_live.get("enable_tlf", False):
        for sym in cfg_live.get("tlf_symbols", ["NAS100", "US500"]):
            strategies.append(TwoLegFadeStrategy(cfg_live, sym))
    # FORWARD-TEST SLEEVES, not bricks: RVWAP (GER40 H1, magic 111) et RSKEW (US30 H4,
    # magic 112), issues de la chaine `research/`. Deployees le 2026-08-18 a 1R CHACUNE
    # sur instruction explicite de l'utilisateur. Par defaut OFF, comme les autres, pour
    # qu'un checkout nu continue de trader le book fige.
    # PARITE PROUVEE (`check_live_parity_research.py`, 0 ecart sur 400 trades chacune) :
    # le scan live et le backtest appellent LA MEME fonction `research_sleeves.decide`.
    # ⚠️ IN-SAMPLE, sans forward-test. Voir edgelab/intraday/research_sleeves.py.
    if cfg_live.get("enable_research_sleeves", False):
        for sleeve in ("RVWAP", "RSKEW"):
            strategies.append(ResearchSleeveStrategy(cfg_live, sleeve))
    # KAER (NAS100 M15 Kaufman ER breakout) was REPLACED by HMASTO in the forward-test
    # slot, 2026-08-10 — user decision. The two are the SAME family (corr +0.335 monthly,
    # same asset, same timeframe), so they are alternatives, never a pair: stacking them
    # takes the book's maxDD 17.1 -> 20.0 and its funded ruin 7.3 % -> 12.3 % at
    # 0.5 %/trade, while swapping cuts maxDD to 15.3 and ruin to 3.8 %. HMASTO also
    # dominates KAER standalone (R/yr +42.8 vs +30.9, RoMaD 1.72 vs 1.22) and its two
    # half-samples GROW where KAER's decay. `KaerStrategy` and `kaer.py` are kept for
    # research and `verify`; only the LIVE wiring is gone. See wiki/log.md 2026-08-10.
    if cfg_live.get("enable_kaer", False):
        LOG.warning("enable_kaer is set but KAER was REPLACED by HMASTO in the live "
                    "forward-test slot on 2026-08-10 (same family, corr +0.335; "
                    "stacking both degrades the book) — IGNORING the flag. "
                    "Set enable_hmasto instead. See wiki/log.md.")
    # KELT (BTCUSD H1 Keltner) is RETIRED from the live book, 2026-08-09 — user decision.
    # FTMO's BTCUSD swap is -30 %/yr BOTH sides (MT5 "percentage of current price" =
    # annual interest, 360-day bank year -> 8.33 bps/night). With that plus the
    # 0.0325 %/side commission the sleeve nets +5.00 R/yr at t=0.87 instead of +17.35 at
    # t=2.99, and DROPPING it improves both books (AGRESSIF maxDD 21.7->17.3, RoMaD
    # 2.03->2.41; FUNDED ruin 2.4 %->0.7 %). A tight stop bought notional that the swap
    # then charged for every night. `KeltnerStrategy` and `keltner_btc.py` are kept for
    # research and `verify`; only the LIVE wiring is gone. See wiki/log.md 2026-08-09.
    if cfg_live.get("enable_keltner", False):
        LOG.warning("enable_keltner is set but KELT was RETIRED from the live book on "
                    "2026-08-09 (FTMO swap -30%%/yr both sides) — IGNORING the flag. "
                    "See wiki/system.md.")
    return broker, risk, strategies


def _equity(broker: Broker, risk: LiveRiskManager) -> float:
    """Account equity in cash. Live: from MT5. Dry-run: initial * (1 + cumR * risk%)."""
    if broker.live:
        return broker.equity()
    return risk.initial_balance * (1.0 + broker.realized_R * risk.risk_per_trade)


def _arm_floors(broker: Broker, risk: LiveRiskManager, cfg_live: dict) -> None:
    """Pose la reference FIXE des planchers prop, une fois, au demarrage.

    Repli sur le solde du compte si l'ancre est illisible : sans cela, un compte de
    60 000 serait juge contre le nominal de config (100 000) et son plancher -10 %
    (90 000) le declarerait FAILED immediatement.
    """
    anchor, since = _challenge_anchor(broker, cfg_live)
    if anchor:
        LOG.warning("depart du challenge : %.2f (%s)", anchor, since)
    else:
        try:
            anchor = broker.balance() or risk.initial_balance
        except Exception:
            anchor = risk.initial_balance
        LOG.warning("ancre du challenge indisponible -> planchers bases sur le solde "
                    "courant %.2f (ils ne bougeront plus de la session)", anchor)
    risk.set_floor_basis(anchor)


def _sync_account_size(broker: Broker, risk: LiveRiskManager, cfg_live: dict) -> None:
    """Base le SIZING sur le solde reel du compte connecte (defaut).

    Empeche le decalage dangereux ou `initial_balance` de config (p.ex. 100000) vaut 10x
    le solde reel de la demo (p.ex. 10000) -> 1R ferait 10 % du compte au lieu de 1 %.
    `size_from_account:false` garde `propfirm.initial_balance` tel quel.

    ⚠️ CETTE FONCTION NE TOUCHE PLUS A L'ETAT DE RISQUE. Elle ecrivait aussi
    `peak_equity` et `day_start_equity`, et elle est appelee A CHAQUE RECONNEXION MT5 :
      * les planchers etant calcules sur `initial_balance`, le plancher de DD statique
        DESCENDAIT AVEC LE SOLDE — une reconnexion en plein drawdown le reposait plus bas
        et le compte pouvait depasser -10 % sans que le halt parte ;
      * `day_start_equity` etant remis au solde courant, la perte deja subie dans la
        journee etait effacee et le verrou journalier ne se declenchait plus.
    Les planchers vivent desormais sur `risk.floor_basis` (l'ancre du challenge, posee une
    seule fois par `set_floor_basis`) et `day_start_equity` n'est plus reecrit que par le
    changement de jour dans `on_equity`. Corrige le 2026-08-12.
    """
    if not cfg_live.get("size_from_account", True):
        return
    bal = broker.balance()
    if bal and bal > 0:
        risk.initial_balance = bal
        LOG.warning("sizing base = LIVE account balance %.2f | 1R = %.2f (%.2f%%) | "
                    "planchers prop bases sur %.2f (FIXE, pas sur ce solde)",
                    bal, risk.risk_per_trade * bal, risk.risk_per_trade * 100,
                    risk.floor_basis)


ANCHOR_FILE = Path(__file__).resolve().parent / "_out" / "account_start.json"
_ANCHOR: tuple | None = None      # memo: l'ancre est posee une fois, pas relue chaque jour


def _challenge_anchor(broker: Broker, cfg_live: dict) -> tuple[float | None, str | None]:
    """Le solde de DEPART du challenge — une ancre FIXE, et le jour ou elle a ete posee.

    `risk.initial_balance` ne peut pas jouer ce role : `size_from_account: true` y ecrit
    le solde lu AU DEMARRAGE, et le reecrit a chaque reconnexion MT5. La progression du
    challenge mesuree contre lui n'est donc pas la progression du challenge mais celle
    depuis le dernier redemarrage — d'ou le "+0.31 % de +15 %" affiche pendant que le
    journal etait a -0.14 R (signale par l'utilisateur le 2026-08-12).

    Ordre de priorite :
      1. `propfirm.challenge_start_balance` dans la config — la valeur nominale du
         challenge quand elle est connue. C'est la seule source VRAIMENT exacte.
      2. `_out/account_start.json`, ecrit UNE FOIS au premier passage et jamais reecrit.
         Le compte etait deja entame quand le fichier est cree ; la date publiee dans le
         rapport dit donc a partir de quand le pourcentage compte.
    Retourne (None, None) si le solde n'est pas lisible : le rapport retombe alors sur
    `initial` en le signalant, plutot que de publier un chiffre qui a l'air d'etre la
    progression du challenge sans l'etre.
    """
    global _ANCHOR
    import json
    if _ANCHOR is not None:
        return _ANCHOR
    cfgv = (cfg_live.get("propfirm") or {}).get("challenge_start_balance")
    if cfgv:
        _ANCHOR = (float(cfgv), "config")
        return _ANCHOR
    try:
        if ANCHOR_FILE.exists():
            d = json.loads(ANCHOR_FILE.read_text(encoding="utf-8"))
            _ANCHOR = (float(d["balance"]), str(d.get("since", "?")))
            return _ANCHOR
        bal = broker.balance()
        if not bal or bal <= 0:
            return None, None
        since = pd.Timestamp.now(tz="UTC").date().isoformat()
        ANCHOR_FILE.parent.mkdir(parents=True, exist_ok=True)
        ANCHOR_FILE.write_text(json.dumps({"balance": float(bal), "since": since}),
                               encoding="utf-8")
        LOG.warning("ancre de depart du challenge posee : %.2f au %s (%s) — le %% du "
                    "rapport quotidien ET les planchers prop comptent a partir de la",
                    bal, since, ANCHOR_FILE)
        _ANCHOR = (float(bal), since)
        return _ANCHOR
    except Exception as exc:
        LOG.warning("ancre de depart illisible (%s) — le rapport le signalera", exc)
        return None, None


_LAST_UPDATE_CHECK = 0.0
_UNSUPERVISED_WARNED = False


def _is_supervised() -> bool:
    """True when this process was launched by ``run_forever.ps1`` (which exports
    ``EDGELAB_SUPERVISED=1``).

    Il n'existe aucun autre moyen fiable de le savoir de l'interieur : le parent d'un
    `python -m` lance a la main est un `powershell.exe`, exactement comme celui du
    superviseur. La variable d'environnement est posee par le seul script qui sait
    RELANCER, donc sa presence est la definition meme de « supervise ».
    """
    return os.environ.get("EDGELAB_SUPERVISED") == "1"


def _check_update(cfg_live: dict) -> bool:
    """If ``auto_update`` is on, every ``update_check_min`` min compare local HEAD to
    origin/main; return True when a newer commit exists so the runner can exit and let
    the supervisor git-pull + relaunch. Degrades silently if git is missing/offline.

    ⚠️ NE REND JAMAIS True SANS SUPERVISEUR. La sortie 75 est un contrat a deux : le
    runner sort, le superviseur `git pull` + relance. Sans superviseur, la moitie du
    contrat manque et la sortie est DEFINITIVE — le mecanisme cense propager le code
    devient celui qui eteint le live, silencieusement et sans borne de duree. C'est
    exactement ce qui menacait le 2026-08-17 : superviseur mort depuis le 12/08 a 23:41,
    runner relance a la main, `auto_update: true`, et « le VPS suit origin/main » comme
    procedure de deploiement — le prochain push aurait arrete le book. On prefere donc
    TOUJOURS un runner en retard de code a un runner mort : on journalise, on alerte une
    fois, et on continue de trader.
    """
    if not cfg_live.get("auto_update", False):
        return False
    if not _is_supervised():
        global _UNSUPERVISED_WARNED
        if not _UNSUPERVISED_WARNED:
            _UNSUPERVISED_WARNED = True
            LOG.warning("auto-update DESACTIVE a chaud : aucun superviseur detecte "
                        "(EDGELAB_SUPERVISED absent). Sortir en %d serait definitif -> on "
                        "continue de trader sur le commit actuel. Relancer via "
                        "run_forever.ps1 pour retablir la mise a jour automatique.",
                        EXIT_UPDATE)
            _alert(cfg_live, ":warning: **runner NON SUPERVISE** — `auto_update` neutralise "
                             "pour ne pas mourir sur un push. Le book trade toujours, mais sur "
                             "le commit actuel, et rien ne le relancera s'il tombe. "
                             "Relancer via `run_forever.ps1`.")
        return False
    global _LAST_UPDATE_CHECK
    import subprocess
    import time as _t
    if _t.time() - _LAST_UPDATE_CHECK < float(cfg_live.get("update_check_min", 30)) * 60:
        return False
    _LAST_UPDATE_CHECK = _t.time()
    repo = str(REPO_ROOT)
    try:
        subprocess.run(["git", "-C", repo, "fetch", "--quiet", "origin", "main"], timeout=60, check=False)
        loc = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"],
                             capture_output=True, text=True, timeout=15).stdout.strip()
        rem = subprocess.run(["git", "-C", repo, "rev-parse", "origin/main"],
                             capture_output=True, text=True, timeout=15).stdout.strip()
        if loc and rem and loc != rem:
            LOG.warning("update available (%s -> %s) -> exiting %d for supervised pull+relaunch",
                        loc[:7], rem[:7], EXIT_UPDATE)
            return True
    except Exception as exc:
        LOG.warning("auto-update check skipped: %s", exc)
    return False


def _alert(cfg_live: dict, msg: str) -> None:
    """Push one ad-hoc Discord line (health alerts). Never raises: an alert that fails
    must not kill the loop it is watching."""
    url = cfg_live.get("discord_webhook_url")
    if not url:
        return
    try:
        from edgelab.live.summary import send_discord
        send_discord(url, msg, code=False)
    except Exception as exc:
        LOG.warning("alerte Discord non envoyee (%s) : %s", exc, msg)


def _us_session_minutes(now_utc: pd.Timestamp, tz: str = "America/New_York") -> tuple:
    """``(minute_of_day_ET, open_min, flat_min)`` or ``None`` outside a US cash session.

    Le calendrier de `us_session_calendar` est reutilise tel quel, donc les feries et les
    demi-seances (ou le flux CFD ferme plus tot) ne declenchent pas de fausse alerte.
    """
    from edgelab.live.us_session_calendar import flat_minute
    et = now_utc.tz_convert(tz)
    if et.weekday() >= 5:
        return None
    open_min = 9 * 60 + 30
    flat = flat_minute(et.date(), 15 * 60 + 55)
    minute = et.hour * 60 + et.minute
    if not (open_min <= minute <= flat):
        return None
    return minute, open_min, flat


_LAST_LIVENESS_ALERT = None
_STARTED_AT: pd.Timestamp | None = None
# Dernier instant ou chaque sleeve a ete VUE en position. C'est la piece qui manquait :
# `_acted_bar` ne bouge pas pendant une detention (et vaut meme None si le processus a
# demarre position ouverte), donc a la seconde ou la sleeve redevient plate, l'exclusion
# "en position" tombait et la fraicheur se mesurait sur TOUTE LA DUREE DU TRADE.
_SEEN_IN_POSITION: dict = {}


def _scan_window_open(strat, now_utc: pd.Timestamp) -> bool:
    """La sleeve a-t-elle le DROIT de scanner maintenant, selon SA fenetre de signal ?

    Copie exacte de la garde que les sleeves s'appliquent a elles-memes
    (`open_m <= minute <= cut_m + bar_minutes`, cf. TLF / HMASTO / KAER). Sans elle, la
    porte de seance US du controle (jusqu'a `flat_minute`, 15:55 ET) est PLUS LARGE que
    la fenetre d'entree de TLF (`entry_cutoff` 15:30, + 5 min) : entre 15:35 et 15:55 la
    sleeve sort sur sa propre garde sans toucher `_acted_bar`, le retard atteint 20-21 min
    contre un seuil de 20, et l'alerte partait TOUS LES JOURS vers 15:55:30 sans le
    moindre incident (mesure du 2026-08-19 : silence a 15:55:00, alerte a 15:55:30).
    Une sleeve sans fenetre declaree (RVWAP/RSKEW scannent toute barre) rend True.
    """
    p_ = getattr(strat, "p", None)
    tf = getattr(strat, "bar_minutes", None)
    if p_ is None or not tf:
        return True
    o, c = getattr(p_, "session_open", None), getattr(p_, "entry_cutoff", None)
    if not o or not c:
        return True
    et = now_utc.tz_convert(getattr(p_, "tz", "America/New_York"))
    minute = et.hour * 60 + et.minute
    return (int(o[:2]) * 60 + int(o[3:])) <= minute <= (int(c[:2]) * 60 + int(c[3:])) + int(tf)


def _maybe_liveness_alert(broker: Broker, cfg_live: dict, strategies,
                          now_utc: pd.Timestamp) -> None:
    """Alert when a bar-scanning sleeve STOPS SCANNING while the US session is open.

    LE TROU QUE CE CONTROLE BOUCHE (2026-08-17). Le rapport quotidien de
    `daily_report_et` prouve la vie **a 17:00 ET, une heure APRES la cloture** : les
    rapports du 15 et du 16/08 sont partis normalement alors que le runner avait manque
    toute la seance du 14/08, puis la premiere heure de celle du 17/08. La liveness AU
    REPOS et la liveness EN SEANCE sont deux proprietes distinctes, et une seule etait
    surveillee. Un runner qui meurt a l'ouverture et qu'on relance a 17:01 envoie un
    rapport parfaitement rassurant.

    Rien de neuf n'est mesure ici : `_acted_bar` existe deja et alimente deja le
    heartbeat. On le LIT, pendant la seance, et on crie s'il prend du retard. Une sleeve
    qui scanne sans rien trouver met quand meme `_acted_bar` a jour (le skip pour barre
    perimee le fait aussi), donc ce retard mesure bien la BOUCLE, pas le signal.

    DEUX FAUX POSITIFS ATTRAPES AU DEPLOIEMENT (2026-08-17, premiere mise en service) et
    que la logique doit exclure par construction :

    * **Une sleeve qui PORTE une position ne scanne pas, et c'est voulu.** Son `step()`
      part par la branche de gestion de position et ne touche jamais `_acted_bar` : le
      controle accusait donc HMASTO pendant toute la duree de son trade (« pas scanne
      depuis 212 min » sur un runner parfaitement sain qui venait d'ouvrir la position
      lui-meme). On saute donc les sleeves en position. Angle mort assume : si TOUTES les
      sleeves scannantes sont en position, le controle se taît — mais alors le runner
      vient de prouver qu'il fonctionne en les ouvrant, et leur risque est cote broker.
    * **Un processus qui vient de demarrer a legitimement `_acted_bar = None`.** La grace
      se compte donc depuis LE DEMARRAGE (`_STARTED_AT`), jamais depuis l'ouverture de la
      seance : sans ca, toute relance passe la 20e minute de seance declenchait l'alerte
      instantanement. Le trou laisse par une relance est deja le sujet de `_startup_alert`.
    """
    global _LAST_LIVENESS_ALERT
    sess = _us_session_minutes(now_utc)
    if sess is None:
        return
    _minute, _open_min, _flat = sess       # la porte de seance suffit ici
    floor_min = float(cfg_live.get("liveness_lag_alert_min", 20))
    margin = float(cfg_live.get("liveness_margin_min", 5))
    cooldown = float(cfg_live.get("liveness_alert_cooldown_min", 60))
    grace = float(cfg_live.get("liveness_grace_min", 20))   # laisse le warmup d'ouverture

    # LE SEUIL DOIT SUIVRE L'UT DE LA SLEEVE. `_acted_bar` pointe la derniere barre CLOSE,
    # donc son age cycle mecaniquement de 0 a `tf` sur un runner parfaitement sain : un
    # seuil fixe a 20 min hurlerait en continu sur une sleeve H1 (age normal jusqu'a 60)
    # et ne servirait a rien au-dela. On garde donc un plancher (pour les petites UT, ou
    # 5+5 serait trop nerveux) et on prend le max avec `tf + marge`.
    worst, worst_name, worst_thr = None, None, None
    for s_ in strategies:
        tf = getattr(s_, "bar_minutes", None)
        if not tf:
            continue                      # sleeve non scannante (rollover, 1 trade/jour)
        try:
            if broker.open_position(s_.magic) is not None:
                _SEEN_IN_POSITION[s_.magic] = now_utc
                continue                  # en position -> ne scanne pas, par conception
        except Exception:
            pass                          # un broker qui hoquette ne doit pas taire l'alerte
        if not _scan_window_open(s_, now_utc):
            continue                      # hors de SA fenetre de signal -> silence normal
        thr = max(floor_min, float(tf) + margin)
        bar = getattr(s_, "_acted_bar", None)
        # DEPUIS QUAND A-T-ON LE DROIT D'ATTENDRE UN SCAN ? Le plus TARDIF de : la
        # cloture de la derniere barre scannee, l'instant ou la sleeve a quitte sa
        # position, et le demarrage du processus. Ne lire que `_acted_bar` etait le
        # defaut : le 2026-08-18 le runner a redemarre a 16:09:19Z alors que TLF/NAS100
        # portait son short, donc `_acted_bar` valait None ; la position s'est fermee sur
        # l'aplat de seance a 19:55:19.548Z et l'alerte est partie 179 ms plus tard, dans
        # LE MEME CYCLE, en annoncant "pas scanne depuis 226 min" -- soit exactement
        # l'age du processus, c'est-a-dire la duree pendant laquelle il tenait le trade.
        refs = []
        if bar is not None:
            refs.append(pd.Timestamp(bar) + pd.Timedelta(minutes=tf))
        seen = _SEEN_IN_POSITION.get(s_.magic)
        if seen is not None:
            refs.append(seen)
        if _STARTED_AT is not None:
            refs.append(_STARTED_AT)
        if not refs:
            continue                      # rien de mesurable (ni barre, ni ancre)
        lag = (now_utc - max(refs)).total_seconds() / 60.0
        # une sleeve qui n'a JAMAIS scanne attend sa premiere cloture de barre : on lui
        # laisse la grace, comme avant, en plus du seuil d'UT.
        eff = thr if bar is not None else max(thr, grace)
        if lag <= eff:
            continue
        if worst is None or lag - eff > worst - worst_thr:
            worst, worst_name, worst_thr = lag, f"{type(s_).__name__}/{s_.magic}", eff

    if worst is None:
        return
    if _LAST_LIVENESS_ALERT is not None and \
            (now_utc - _LAST_LIVENESS_ALERT).total_seconds() / 60.0 < cooldown:
        return
    _LAST_LIVENESS_ALERT = now_utc
    LOG.warning("LIVENESS: %s n'a pas scanne depuis %.0f min alors que la seance US est "
                "ouverte (seuil %.0f)", worst_name, worst, worst_thr)
    _alert(cfg_live, f":rotating_light: **SCAN EN RETARD EN SEANCE** — `{worst_name}` sans "
                     f"barre scannee depuis **{worst:.0f} min** (seuil {worst_thr:.0f}). "
                     f"Le book peut etre en train de manquer des entrees. "
                     f"Verifier le runner, le terminal MT5 et le flux.")


def _startup_alert(cfg_live: dict, now_utc: pd.Timestamp) -> None:
    """Alert on a restart that lands INSIDE an open US session, with the gap length.

    Le 2026-08-17 le runner est mort et a redemarre deux fois (14/08 et 17/08) sans
    qu'aucune ligne d'arret ne soit ecrite nulle part — ni cote runner, ni cote
    superviseur. Un demarrage est le seul evenement que le processus est SUR de pouvoir
    signaler, et le heartbeat precedent donne la duree du trou. On les publie ensemble.
    """
    if _us_session_minutes(now_utc) is None:
        return
    prev = None
    try:
        hb = Path(__file__).resolve().parent / "_out" / "heartbeat.txt"
        if hb.exists():
            prev = pd.Timestamp(hb.read_text(encoding="utf-8").splitlines()[0])
    except Exception:
        prev = None
    gap_min = (now_utc - prev).total_seconds() / 60.0 if prev is not None else None
    gap = f"{gap_min:.0f} min" if gap_min is not None else "inconnu"
    sup = "sous superviseur" if _is_supervised() else "**SANS superviseur**"
    LOG.warning("demarrage EN SEANCE US (%s) — dernier heartbeat il y a %s", sup, gap)
    # UNE RELANCE SANS TROU N'EST PAS UN INCIDENT. Un arret/relance immediat (mise a jour
    # de code, redemarrage volontaire) laisse un ecart de quelques secondes et ne coute
    # rien de plus que la barre en cours : l'annoncer sur Discord apprend a ignorer
    # l'alerte, ce qui est exactement le defaut qu'on corrige. On journalise, on se taît.
    quiet = float(cfg_live.get("startup_alert_min_gap_min", 2))
    if gap_min is not None and gap_min < quiet:
        return
    _alert(cfg_live, f":arrows_counterclockwise: **runner redemarre EN PLEINE SEANCE** ({sup}) — "
                     f"dernier heartbeat il y a **{gap}**. Les entrees de cet intervalle sont "
                     f"perdues (les sleeves ne courent pas apres une barre passee).")


_LAST_ALERT_DAY: dict = {}


def _maybe_session_alerts(cfg_live: dict, now_utc: pd.Timestamp) -> None:
    """Fire configured pre-session Discord pings (e.g. ~1h before the US open). Each entry
    of ``pre_session_alerts`` is {et: "HH:MM", msg: "..."}; each fires once/day inside a
    short window after its time (no stale catch-up if the runner was down)."""
    alerts = cfg_live.get("pre_session_alerts") or []
    url = cfg_live.get("discord_webhook_url")
    if not alerts or not url:
        return
    et = now_utc.tz_convert("America/New_York")
    nowmin = et.hour * 60 + et.minute
    from edgelab.live.summary import send_discord
    for a in alerts:
        t = str(a.get("et", "")).strip()
        if len(t) < 4 or ":" not in t:
            continue
        amin = int(t[:2]) * 60 + int(t[3:])
        if _LAST_ALERT_DAY.get(t) == et.date() or not (amin <= nowmin < amin + 20):
            continue
        msg = str(a.get("msg", f"trading session in ~1h ({t} ET)"))
        try:
            send_discord(url, f"[{et:%H:%M} ET] {msg}", code=False)
            LOG.info("pre-session alert sent (%s)", t)
        except Exception as exc:
            LOG.warning("session alert failed: %s", exc)
        _LAST_ALERT_DAY[t] = et.date()


_LAST_REPORT_DAY = None


def _maybe_report(broker: Broker, risk: LiveRiskManager, strategies, cfg_live: dict,
                  now_utc: pd.Timestamp) -> None:
    """Once a day at ``daily_report_et``, push a heartbeat+summary to Discord. Its ABSENCE
    is the alert: no report = the runner is down. Sends even if MT5 hiccups (heartbeat)."""
    global _LAST_REPORT_DAY
    url = cfg_live.get("discord_webhook_url")
    if not url:
        return
    et = now_utc.tz_convert("America/New_York")
    hhmm = str(cfg_live.get("daily_report_et", "17:00"))
    rep_min = int(hhmm[:2]) * 60 + int(hhmm[3:])
    if et.date() == _LAST_REPORT_DAY or (et.hour * 60 + et.minute) < rep_min:
        return
    from edgelab.live.summary import (build_report_embed, build_report_text, send_discord,
                                      DEFAULT_CSV, MAGIC_TAG)
    try:
        bal = broker.balance()
    except Exception:
        bal = float("nan")
    try:      # equity = balance + flottant : sans elle le rapport compare du cash REALISE
        eq = broker.equity()     # a un journal qui, lui, ignore les positions ouvertes
    except Exception:
        eq = None
    anchor, anchor_since = _challenge_anchor(broker, cfg_live)
    # open positions from the BROKER (authoritative — the journal can miss one)
    positions = []
    for strat in strategies:
        try:
            p = broker.open_position(strat.magic)
        except Exception:
            p = None
        if p is not None:
            positions.append({"symbol": p.symbol, "direction": p.direction, "magic": p.magic,
                              "entry_price": float(p.entry_price),
                              "days": int((now_utc.normalize() - p.open_time.normalize()).days)})
    ctx = {"balance": bal, "initial": risk.initial_balance, "one_r": risk.risk_budget(),
           "equity": eq, "challenge_start": anchor, "challenge_start_since": anchor_since,
           "risk_pct": risk.risk_per_trade, "dd_pct": risk.rules.max_total_drawdown_pct,
           "target_pct": risk.rules.profit_target_pct, "now_et": et, "commit": _git_head(),
           "server": broker.server, "alive": True, "open_positions": positions,
           "n_bricks": len({MAGIC_TAG.get(s.magic, s.magic) for s in strategies})}
    try:
        send_discord(url, embed=build_report_embed(DEFAULT_CSV, ctx))
        LOG.info("daily Discord report sent")
    except Exception as exc:
        LOG.warning("Discord embed report failed (%s) -> falling back to plain text", exc)
        try:   # the heartbeat matters more than the formatting
            header = [f"edgelab.live daily report - {et:%Y-%m-%d %H:%M} ET",
                      f"account {risk.initial_balance:.0f} | 1R {risk.risk_budget():.2f} | "
                      f"balance {bal:.2f} | runner ALIVE"]
            send_discord(url, build_report_text(DEFAULT_CSV, header))
        except Exception as exc2:
            LOG.warning("Discord report failed: %s", exc2)
    _LAST_REPORT_DAY = et.date()   # set even on failure -> one attempt/day, no spam


_MARKET_CLOSED_SINCE: dict[str, pd.Timestamp] = {}   # strat name -> when it first hit a closed market
_LAST_FAILURE: dict = {}          # strat name -> (signature, first seen, last logged)
FAIL_REPEAT_MIN = 15.0            # re-log an UNCHANGED, still-repeating failure this often

_HB_FAIL: dict = {}               # streak d'echecs d'ecriture du heartbeat
HB_REPEAT_MIN = 30.0              # re-log un echec de heartbeat INCHANGE a ce rythme


def _log_failure(name: str, exc: Exception, now_utc: pd.Timestamp) -> None:
    """Full traceback the first time a brick fails, then one throttled line while the SAME
    failure keeps repeating.

    Exits are retried on every pass (a position we want out of is never abandoned), so a
    rejection that persists on an OPEN market — invalid stops, AutoTrading off, a
    mis-mapped symbol — would otherwise write a traceback every `poll_seconds`, i.e.
    thousands a day, and rotate the useful history out of runner.log. Same reasoning that
    made a missing quote a typed MarketClosed instead of an AttributeError (broker._tick_price).
    """
    sig = f"{type(exc).__name__}: {exc}"
    prev = _LAST_FAILURE.get(name)
    if prev is None or prev[0] != sig:          # new / different failure -> the full story
        LOG.exception("strategy %s failed: %s", name, exc)
        _LAST_FAILURE[name] = (sig, now_utc, now_utc)
    elif (now_utc - prev[2]) >= pd.Timedelta(minutes=FAIL_REPEAT_MIN):
        LOG.error("strategy %s STILL failing (for %s): %s", name, now_utc - prev[1], sig)
        _LAST_FAILURE[name] = (sig, prev[1], now_utc)


def _heartbeat(broker, risk, strategies, now_utc: pd.Timestamp) -> None:
    """Ecrit `_out/heartbeat.txt` a chaque passe. C'est la SEULE preuve de vie continue.

    `runner.log` n'en est pas une : `one_pass` ne journalise que sur EVENEMENT (ordre
    envoye, marche ferme, echec), donc un marche calme laisse le log muet pendant des
    heures alors que tout va bien. Un controle qui lisait la fraicheur du log a donc
    signale un runner mort qui tournait parfaitement (2026-08-11). Le fichier ci-dessous
    supprime l'ambiguite : s'il est frais, la boucle tourne.

    Volontairement pas un log : ecrire une ligne toutes les 20 s ferait tourner l'histoire
    utile hors de runner.log en quelques jours -- exactement ce que le commentaire sur
    MarketClosed cherche deja a eviter.
    """
    try:
        out = Path(__file__).resolve().parent / "_out"
        out.mkdir(parents=True, exist_ok=True)
        n_pos = sum(1 for s_ in strategies if broker.open_position(s_.magic) is not None)
        # DERNIERE BARRE SCANNEE, par sleeve. Sans ca, "aucune ligne de log" est ambigu :
        # une sleeve qui scanne chaque barre et ne trouve rien est SILENCIEUSE, exactement
        # comme une sleeve bloquee. Cette ligne separe les deux d'un coup d'oeil -- c'est
        # la question posee le 2026-08-11 ("es-tu sur que c'est normal que les 2 briques
        # skip ?") a laquelle rien dans le processus ne repondait.
        scanned = []
        for s_ in strategies:
            b_ = getattr(s_, "_acted_bar", None)
            if b_ is not None:
                scanned.append(f"{s_.magic}@{pd.Timestamp(b_).strftime('%H:%M')}")
        (out / "heartbeat.txt").write_text(
            f"{now_utc.isoformat()}\n"
            f"commit={_git_head()}\n"
            f"strategies={len(strategies)}\n"
            f"magics={sorted(s_.magic for s_ in strategies)}\n"
            f"open_positions={n_pos}\n"
            f"last_scanned_bar_utc={' '.join(scanned) if scanned else '(aucune)'}\n"
            f"realized_R={getattr(broker, 'realized_R', 0.0):.3f}\n",
            encoding="utf-8")
        if _HB_FAIL:                     # on n'ecrivait plus, on ecrit de nouveau
            LOG.warning("heartbeat: ecriture retablie apres %s d'echecs",
                        now_utc - _HB_FAIL["since"])
            _HB_FAIL.clear()
    except Exception as exc:             # un disque qui hoquette ne doit JAMAIS tuer la boucle
        # ...mais il ne doit PAS non plus etre SILENCIEUX. C'etait un LOG.debug, donc
        # invisible : le 2026-08-12 ce fichier datait de la veille alors que le runner
        # (sur le VPS) tradait normalement, et rien ne permettait de dire si la date
        # etait vieille parce que la BOUCLE etait morte ou parce que l'ECRITURE
        # echouait. Les deux se ressemblent exactement -- et c'est precisement la
        # question a laquelle ce fichier existe pour repondre.
        # ATTENTION : ce WARNING peut lui-meme ne jamais atterrir. Si `_out/` est
        # verrouille (OneDrive, permissions), runner.log est dans le MEME dossier et
        # sera muet aussi ; seule la console (StreamHandler) le verra a coup sur.
        sig = f"{type(exc).__name__}: {exc}"
        if _HB_FAIL.get("sig") != sig:               # echec neuf -> l'histoire complete
            LOG.warning("heartbeat: ECRITURE IMPOSSIBLE dans %s (%s) -- la preuve de vie est GELEE ; ne pas conclure que le runner est mort sur la seule date de ce fichier",
                        Path(__file__).resolve().parent / "_out", sig, exc_info=True)
            _HB_FAIL.update(sig=sig, since=now_utc, last=now_utc)
        elif (now_utc - _HB_FAIL["last"]) >= pd.Timedelta(minutes=HB_REPEAT_MIN):
            LOG.warning("heartbeat: TOUJOURS impossible a ecrire (depuis %s) : %s",
                        now_utc - _HB_FAIL["since"], sig)
            _HB_FAIL["last"] = now_utc


def one_pass(broker: Broker, risk: LiveRiskManager, strategies, now_utc: pd.Timestamp) -> None:
    risk.on_equity(_equity(broker, risk), now_utc)
    for strat in strategies:
        name = type(strat).__name__
        # LA CLE EST LE MAGIC, PAS LA CLASSE. Deux instances d'une meme sleeve (TLF x2,
        # research x2, crypto x2 autrefois) partageaient la cle : si l'une echouait et
        # que sa jumelle reussissait dans la MEME passe, le `pop` de la reussite effacait
        # la streak, et l'echec suivant etait relu comme NEUF -> traceback complet toutes
        # les 20 s, c'est-a-dire exactement le regime que `_log_failure` dit vouloir
        # eviter ("thousands a day, and rotate the useful history out of runner.log").
        key = f"{name}/{strat.magic}"
        try:
            sent_before = broker.orders_sent
            strat.step(broker, risk, now_utc)
            _LAST_FAILURE.pop(key, None)       # a clean pass ends any failure streak
            if key in _MARKET_CLOSED_SINCE:    # a prior pass was waiting -> it just went through
                waited = now_utc - _MARKET_CLOSED_SINCE.pop(key)
                # `step()` returns nothing, and half a dozen of its exits are legitimately
                # silent (no signal, day already handled, bar not printed yet). Only the
                # broker's own counter can say an order really went out — claiming one on a
                # bare return is what hid brick 4's stuck exit for three days (2026-08-07..09).
                if broker.orders_sent > sent_before:
                    LOG.info("%s: market reopened, order placed (waited %s)", name, waited)
                else:
                    LOG.info("%s: market reopened, NO order sent on this pass (waited %s)",
                             name, waited)
        except MarketClosed as exc:            # expected daily break -> log once, keep retrying quietly
            if key not in _MARKET_CLOSED_SINCE:
                _MARKET_CLOSED_SINCE[key] = now_utc
                LOG.info("%s: %s -> market closed, will retry until it opens (no error)", key, exc)
        except Exception as exc:               # never let one brick kill the loop
            _log_failure(key, exc, now_utc)


def status(broker: Broker, risk: LiveRiskManager, strategies, cfg_live: dict) -> None:
    broker.connect()
    _arm_floors(broker, risk, cfg_live)
    _sync_account_size(broker, risk, cfg_live)
    LOG.info("mode=%s  balance=%.2f  1R=%.2f  cumR(paper)=%+.2f",
             "LIVE" if broker.live else "DRY-RUN", broker.balance(),
             risk.risk_per_trade * risk.initial_balance, broker.realized_R)
    for strat in strategies:
        pos = broker.open_position(strat.magic)
        LOG.info("  %-20s magic=%d  position=%s", type(strat).__name__, strat.magic,
                 "flat" if pos is None else f"{pos.direction:+d} {pos.lots} @ {pos.entry_price:.5f}")


_SINGLETON_HANDLE = None   # keep the mutex handle alive for the process lifetime


def _acquire_singleton() -> bool:
    """Windows named-mutex singleton. True if we are the ONLY runner, False if another
    instance already holds it. Guarantees one runner per machine no matter how many
    launchers fire (bare `python` with two installs, a stray supervisor, etc.)."""
    global _SINGLETON_HANDLE
    try:
        import ctypes
        k = ctypes.windll.kernel32
        h = k.CreateMutexW(None, False, "Global\\edgelab_live_runner_singleton")
        if k.GetLastError() == 183:   # ERROR_ALREADY_EXISTS
            return False
        _SINGLETON_HANDLE = h
        return True
    except Exception:
        return True   # non-Windows / no ctypes -> no guard (this stack is Windows anyway)


def _git_head() -> str:
    """Short hash of the running commit (so the logs say exactly which version is live)."""
    import subprocess
    try:
        out = subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=10).stdout.strip()
        return out or "?"
    except Exception:
        return "?"


def _setup_logging() -> None:
    out = Path(__file__).resolve().parent / "_out"
    out.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s | %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    con = logging.StreamHandler(); con.setFormatter(fmt); root.addHandler(con)
    fh = RotatingFileHandler(out / "runner.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8")
    fh.setFormatter(fmt); root.addHandler(fh)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="single evaluation pass then exit")
    ap.add_argument("--status", action="store_true", help="print account/positions and exit")
    args = ap.parse_args()

    _setup_logging()
    cfg_live = _load_live_cfg()
    broker, risk, strategies = build(cfg_live)

    mode = "LIVE - REAL ORDERS" if broker.live else "DRY-RUN (paper, no orders sent)"
    LOG.warning("edgelab.live starting | commit %s | mode=%s | risk/trade=%.2f%% | static-DD prop",
                _git_head(), mode, risk.risk_per_trade * 100)

    if args.status:
        status(broker, risk, strategies, cfg_live)
        broker.disconnect()
        return 0

    # SINGLETON: never let two order-sending runners fight over the same account.
    if not _acquire_singleton():
        LOG.error("another edgelab.live.runner is already running -> exiting "
                  "(one runner per machine/account). This one will not trade.")
        return 0   # exit 0 so the supervisor stops instead of respawning a duplicate

    try:
        broker.connect()
        # ORDRE VOULU : les planchers prop d'abord (ils fixent `floor_basis`), le sizing
        # ensuite. L'inverse laisserait la premiere lecture d'equity etre jugee contre le
        # nominal de config -- p.ex. un plancher a 90 000 sur un compte de 60 000, donc un
        # compte declare FAILED des la premiere passe.
        _arm_floors(broker, risk, cfg_live)
        _sync_account_size(broker, risk, cfg_live)
        if args.once:
            one_pass(broker, risk, strategies, pd.Timestamp.now(tz="UTC"))
            return 0
        # AVANT la boucle : le heartbeat de l'instance PRECEDENTE est encore sur le disque,
        # et c'est la seule mesure du trou qu'on vient de laisser. `_heartbeat` l'ecrase des
        # le premier cycle, donc l'alerte se lit ici ou jamais.
        _startup_alert(cfg_live, pd.Timestamp.now(tz="UTC"))
        # L'ancre de grace de l'alerte de liveness : une sleeve qui n'a JAMAIS scanne se
        # juge par rapport a CE moment, pas a l'ouverture de la seance.
        global _STARTED_AT
        _STARTED_AT = pd.Timestamp.now(tz="UTC")
        poll = float(cfg_live.get("poll_seconds", 20))
        while True:
            # self-heal a dropped MT5 connection before trading
            if not broker.healthy():
                LOG.warning("MT5 connection lost -> reconnecting")
                try:
                    broker.reconnect()
                    _sync_account_size(broker, risk, cfg_live)
                except Exception:
                    LOG.exception("reconnect failed; retrying next cycle")
                    time.sleep(poll); continue
            now = pd.Timestamp.now(tz="UTC")
            one_pass(broker, risk, strategies, now)
            # Les sorties que le BROKER a executees (stop/target touches cote serveur)
            # n'apparaissent nulle part sans ceci : le driver ne journalise que ce qu'il
            # ferme lui-meme. Et comme un stop vaut toujours -1 R, l'oubli ne perdait
            # que des PERTES.
            broker.reconcile_closures([s_.magic for s_ in strategies], now)
            # ORDRE VOULU : l'alerte de liveness lit `_acted_bar` APRES `one_pass` (donc
            # apres le scan de ce cycle) mais AVANT le heartbeat n'ait plus d'importance —
            # ce qui compte est qu'elle ne juge jamais un etat d'avant le scan.
            _maybe_liveness_alert(broker, cfg_live, strategies, now)
            _heartbeat(broker, risk, strategies, now)
            _maybe_session_alerts(cfg_live, now)
            _maybe_report(broker, risk, strategies, cfg_live, now)
            if _check_update(cfg_live):
                return EXIT_UPDATE   # supervisor git-pulls the new code + relaunches
            if risk.failed:
                LOG.error("account FAILED -> stopping runner (exit %d, supervisor will NOT restart)",
                          EXIT_ACCOUNT_FAILED)
                return EXIT_ACCOUNT_FAILED
            time.sleep(poll)
    except KeyboardInterrupt:
        LOG.warning("interrupted -> shutting down")
        return 0
    finally:
        broker.disconnect()


if __name__ == "__main__":
    sys.exit(main())
