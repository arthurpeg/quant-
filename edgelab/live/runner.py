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

from edgelab.config import load_config
from edgelab.risk.propfirm import PropFirmRules
from edgelab.live.broker import Broker
from edgelab.live.risk import LiveRiskManager
from edgelab.live.strategies import NasOrbStrategy, GoldTomStrategy, CryptoMacdStrategy

LOG = logging.getLogger("edgelab.live.runner")
CFG_LIVE = Path(__file__).resolve().parent / "config_live.yaml"


def _load_live_cfg() -> dict:
    with open(CFG_LIVE, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def build(cfg_live: dict):
    main_cfg = load_config()
    risk_cfg = main_cfg.raw["risk"]
    rules = PropFirmRules.from_config(cfg_live["propfirm"])
    broker = Broker(cfg_live)
    risk = LiveRiskManager(rules, float(cfg_live["risk_per_trade"]))
    strategies = [NasOrbStrategy(cfg_live), GoldTomStrategy(cfg_live)]
    for coin in cfg_live.get("crypto_symbols", ["BTCUSD", "ETHUSD"]):
        strategies.append(CryptoMacdStrategy(cfg_live, coin, risk_cfg))
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


def one_pass(broker: Broker, risk: LiveRiskManager, strategies, now_utc: pd.Timestamp) -> None:
    risk.on_equity(_equity(broker, risk), now_utc)
    for strat in strategies:
        try:
            strat.step(broker, risk, now_utc)
        except Exception as exc:               # never let one brick kill the loop
            LOG.exception("strategy %s failed: %s", type(strat).__name__, exc)


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

    mode = "LIVE — REAL ORDERS" if broker.live else "DRY-RUN (paper, no orders sent)"
    LOG.warning("edgelab.live starting | mode=%s | risk/trade=%.2f%% | static-DD prop",
                mode, risk.risk_per_trade * 100)

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
            one_pass(broker, risk, strategies, pd.Timestamp.now(tz="UTC"))
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
