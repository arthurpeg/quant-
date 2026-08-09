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
                                     NasIbsStrategy, KaerStrategy)
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
    # FORWARD-TEST SLEEVE, not a brick: NAS100 M15 Kaufman ER breakout, half size.
    # Defaults to OFF so a plain checkout keeps trading the frozen 4-brick book; the demo
    # runner enables it in config_live.yaml. See edgelab/intraday/kaer.py.
    if cfg_live.get("enable_kaer", False):
        strategies.append(KaerStrategy(cfg_live))
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


def _sync_account_size(broker: Broker, risk: LiveRiskManager, cfg_live: dict) -> None:
    """Base sizing + prop floors on the ACTUAL connected account balance (default).

    Prevents the dangerous mismatch where config initial_balance (e.g. 100000) is 10x the
    real demo balance (e.g. 10000) -> 1R would be 10% of the account instead of 1%.
    Set size_from_account:false in config_live.yaml to use propfirm.initial_balance verbatim.
    """
    if not cfg_live.get("size_from_account", True):
        return
    bal = broker.balance()
    if bal and bal > 0:
        risk.initial_balance = bal
        risk.peak_equity = bal
        risk.day_start_equity = bal
        LOG.warning("sizing base = LIVE account balance %.2f | 1R = %.2f (%.2f%%) | "
                    "daily floor -%.0f%% total-DD floor -%.0f%% (static)",
                    bal, risk.risk_per_trade * bal, risk.risk_per_trade * 100,
                    risk.rules.max_daily_loss_pct * 100, risk.rules.max_total_drawdown_pct * 100)


_LAST_UPDATE_CHECK = 0.0


def _check_update(cfg_live: dict) -> bool:
    """If ``auto_update`` is on, every ``update_check_min`` min compare local HEAD to
    origin/main; return True when a newer commit exists so the runner can exit and let
    the supervisor git-pull + relaunch. Degrades silently if git is missing/offline."""
    if not cfg_live.get("auto_update", False):
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


def one_pass(broker: Broker, risk: LiveRiskManager, strategies, now_utc: pd.Timestamp) -> None:
    risk.on_equity(_equity(broker, risk), now_utc)
    for strat in strategies:
        name = type(strat).__name__
        try:
            strat.step(broker, risk, now_utc)
            if name in _MARKET_CLOSED_SINCE:   # a prior pass was waiting -> it just went through
                waited = now_utc - _MARKET_CLOSED_SINCE.pop(name)
                LOG.info("%s: market reopened, order placed (waited %s)", name, waited)
        except MarketClosed as exc:            # expected daily break -> log once, keep retrying quietly
            if name not in _MARKET_CLOSED_SINCE:
                _MARKET_CLOSED_SINCE[name] = now_utc
                LOG.info("%s: %s -> market closed, will retry until it opens (no error)", name, exc)
        except Exception as exc:               # never let one brick kill the loop
            LOG.exception("strategy %s failed: %s", name, exc)


def status(broker: Broker, risk: LiveRiskManager, strategies, cfg_live: dict) -> None:
    broker.connect()
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
        _sync_account_size(broker, risk, cfg_live)
        if args.once:
            one_pass(broker, risk, strategies, pd.Timestamp.now(tz="UTC"))
            return 0
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
