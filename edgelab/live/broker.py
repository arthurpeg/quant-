"""MT5 / Pepperstone broker layer — connection, bars, sizing inputs, order routing.

Two modes, chosen by ``live_trading`` in config_live.yaml:
  * DRY-RUN (default): sends NOTHING. Keeps an in-memory PAPER book so the runner can
    forward-test honestly — entries are logged, SL/TP/time-exits are resolved against
    freshly-pulled bars, and realised R is tallied. This is the safe forward-test.
  * LIVE: entries go via ``mt5.order_send`` with the SL/TP attached to the position
    (the broker then manages the brackets); the runner only has to enforce time-exits.

MetaTrader5 is imported lazily so this module (and the whole live package) imports and
unit-tests fine on a machine without the terminal. Bars are returned on a TRUE-UTC index
(broker EET reinterpreted via to_true_utc) so all session logic is correct.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from edgelab.intraday.orb import to_true_utc, POINT_SIZE

logger = logging.getLogger("edgelab.live.broker")


class MarketClosed(RuntimeError):
    """Raised when an order is rejected because the symbol's market is in its
    (expected) daily maintenance break — retcode 10018. It is a transient the
    caller should retry until the market reopens, NOT an error. The runner logs
    it once and keeps retrying, instead of spamming a traceback every pass."""


_TF = {"M1": "TIMEFRAME_M1", "M5": "TIMEFRAME_M5", "M15": "TIMEFRAME_M15",
       "H1": "TIMEFRAME_H1", "H4": "TIMEFRAME_H4", "D1": "TIMEFRAME_D1"}


def server_epoch_to_utc(epoch_s) -> pd.Timestamp:
    """A position's MT5 timestamp -> a genuine UTC instant.

    MT5 stamps ``position.time`` with the SERVER wall clock (EET/EEST) but hands it over
    as a plain epoch, so naively labelling it UTC puts it +3 h ahead in summer. Bars go
    through ``to_true_utc`` for exactly this reason; positions must too, or any duration
    computed as ``now_utc - pos.open_time`` is wrong by the server offset.

    This was not theoretical: with the mislabelled stamp brick 3 held **31** D1 bars
    instead of 30 and KELT **99+** H1 bars instead of 96 (KELT: +17.2 -> +15.0 R/yr,
    RoMaD 0.94 -> 0.60 measured on its own backtest). The failure is silent — every
    order still goes out, just one bar late.
    """
    return to_true_utc(pd.DatetimeIndex([pd.Timestamp(int(epoch_s), unit="s")]))[0]


@dataclass
class Position:
    magic: int
    symbol: str
    direction: int
    lots: float
    entry_price: float
    sl: float
    tp: float | None
    sl_dist: float                       # 1R in price
    open_time: pd.Timestamp
    comment: str = ""
    time_exit_at: pd.Timestamp | None = None   # hard time-exit (UTC), None = none
    bars_held_limit: int | None = None         # brick-3 style N-bar time-exit
    ticket: int | None = None                  # live MT5 ticket


@dataclass
class SymbolSpec:
    point: float
    tick_size: float
    tick_value: float                    # account-currency value of one tick per 1.0 lot
    volume_min: float
    volume_step: float
    digits: int
    volume_max: float = 1e9
    stops_level: float = 0.0             # broker min SL/TP distance from price, IN PRICE
    filling_mode: int = 0               # SYMBOL_FILLING_MODE bitmask


class Broker:
    def __init__(self, cfg_live: dict):
        self.cfg = cfg_live
        self.live = bool(cfg_live.get("live_trading", False))
        self.symbol_map: dict = cfg_live.get("symbol_map", {})
        self._connected = False
        self.is_demo = None
        self.server = None
        # paper book (dry-run)
        self.paper: dict[int, Position] = {}
        self.realized_R: float = 0.0
        self._paper_balance = float(cfg_live.get("paper_balance", 100000.0))
        # trade journal (both dry-run and live) — one CSV row per entry & exit
        self.trade_log_path = cfg_live.get("trade_log_csv")

    @staticmethod
    def _tag(pos: "Position", reason: str) -> str:
        """Prefix an exit reason with the brick that owns the position ("brick4:ibs_high").

        The journal's ENTRY rows already name the brick (the comment is "brick4_ibs_reversion"),
        but its EXIT rows only carried "stop"/"take"/"time_exit"/"ibs_high" — so a closed
        NAS100 trade could not be attributed to brick 1 or brick 4, which both trade that
        symbol under their own magic. Tagging the reason keeps attribution exact without
        touching the CSV schema (the field is free text; legacy rows just lack the prefix).
        """
        tag = str(pos.comment or "").split("_")[0]
        return f"{tag}:{reason}" if tag.startswith("brick") else reason

    def _log_trade(self, row: dict) -> None:
        if not self.trade_log_path:
            return
        import csv
        from pathlib import Path
        p = Path(self.trade_log_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        new = not p.exists()
        with open(p, "a", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(row.keys()))
            if new:
                w.writeheader()
            w.writerow(row)

    # ---- connection -------------------------------------------------------
    def connect(self) -> None:
        if self.live or self.cfg.get("pull_real_bars", True):
            import MetaTrader5 as mt5
            # Target a SPECIFIC terminal by path (essential when several terminals run
            # on the same VPS — e.g. a MetaQuotes algo + this Pepperstone one). Optional
            # login/server make an unattended reconnect deterministic.
            kw = {}
            if self.cfg.get("mt5_path"):
                kw["path"] = self.cfg["mt5_path"]
            if self.cfg.get("mt5_login"):
                kw["login"] = int(self.cfg["mt5_login"])
            if self.cfg.get("mt5_password"):
                kw["password"] = str(self.cfg["mt5_password"])
            if self.cfg.get("mt5_server"):
                kw["server"] = str(self.cfg["mt5_server"])
            if self.cfg.get("mt5_portable"):
                kw["portable"] = True
            if not mt5.initialize(**kw):
                raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
            self._connected = True
            info = mt5.account_info()
            server = str(getattr(info, "server", "?"))
            self.server = server
            # trade_mode: 0=DEMO, 1=CONTEST, 2=REAL
            mode = getattr(info, "trade_mode", None)
            self.is_demo = (mode == getattr(mt5, "ACCOUNT_TRADE_MODE_DEMO", 0))
            mode_name = {0: "DEMO", 1: "CONTEST", 2: "REAL"}.get(mode, str(mode))
            logger.info("MT5 connected | login=%s server=%s type=%s balance=%.2f",
                        getattr(info, "login", "?"), server, mode_name,
                        getattr(info, "balance", float("nan")))
            # SAFETY GATE 1: right BROKER/terminal. With two terminals on a VPS, refuse to
            # trade if we attached to the wrong one (e.g. the MetaQuotes algo's terminal).
            expect = self.cfg.get("expect_server")
            if expect and expect.lower() not in server.lower():
                self.disconnect()
                raise RuntimeError(
                    f"connected to server '{server}' but expected '{expect}'. Refusing — this "
                    "is probably the WRONG terminal/account. Set mt5_path to the Pepperstone "
                    "terminal (and/or mt5_login/mt5_server), or fix expect_server.")
            # SAFETY GATE 2: refuse LIVE orders on a REAL account unless explicitly allowed.
            if self.live and not self.is_demo and not self.cfg.get("allow_real_account", False):
                raise RuntimeError(
                    f"live_trading is ON but the connected account is {mode_name}, not DEMO. "
                    "Refusing to send orders. Set allow_real_account:true in config_live.yaml "
                    "ONLY if you truly intend to trade real money.")
            if self.live:
                logger.warning("*** LIVE ORDER SENDING ENABLED on a %s account (%s) ***", mode_name, server)

    def disconnect(self) -> None:
        if self._connected:
            import MetaTrader5 as mt5
            mt5.shutdown()
            self._connected = False

    def healthy(self) -> bool:
        """True only if the terminal is CONNECTED to the trade server and the account
        feed is live. A dropped link often leaves account_info() non-None but with
        equity 0 -> treat that as unhealthy so the loop reconnects instead of acting
        on a garbage equity (which used to trip a false 'prop failed')."""
        if not (self.live or self.cfg.get("pull_real_bars", True)):
            return True
        try:
            import MetaTrader5 as mt5
            ti = mt5.terminal_info()
            ai = mt5.account_info()
            if ti is None or ai is None:
                return False
            if not getattr(ti, "connected", True):
                return False
            if float(getattr(ai, "equity", 0.0)) <= 0.0:
                return False
            return True
        except Exception:
            return False

    def reconnect(self) -> None:
        """Tear down and re-establish the MT5 session (after a dropped connection)."""
        try:
            self.disconnect()
        except Exception:
            pass
        self._connected = False
        self.connect()

    def broker_symbol(self, logical: str) -> str:
        """Map a logical name (NAS100/XAUUSD/BTCUSD...) to the Pepperstone symbol."""
        return self.symbol_map.get(logical, logical)

    # ---- account ----------------------------------------------------------
    def balance(self) -> float:
        if self.live or self._connected:
            import MetaTrader5 as mt5
            info = mt5.account_info()
            if info is not None:
                return float(info.balance)
        return self._paper_balance  # dry-run nominal starting balance (realized_R tracked separately)

    def equity(self) -> float:
        if self.live or self._connected:
            import MetaTrader5 as mt5
            info = mt5.account_info()
            if info is not None:
                return float(info.equity)
        return self._paper_balance

    # ---- bars -------------------------------------------------------------
    def _raw_bars(self, logical: str, timeframe: str, count: int) -> pd.DataFrame:
        """Recent bars with the RAW broker-time index (EET wall-clock labelled UTC),
        exactly as the cached *_D1.parquet files are stored. Used where the backtest
        keys by the stored date (brick-1 D1 ATR) — do NOT tz-reinterpret those."""
        sym = self.broker_symbol(logical)
        import MetaTrader5 as mt5
        if not self._connected:
            self.connect()
        if not mt5.symbol_select(sym, True):
            raise RuntimeError(f"symbol_select failed for {sym}: {mt5.last_error()}")
        rates = mt5.copy_rates_from_pos(sym, getattr(mt5, _TF[timeframe]), 0, count)
        if rates is None or len(rates) == 0:
            raise ValueError(f"no bars for {sym} {timeframe}: {mt5.last_error()}")
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)   # EET-as-UTC, as stored
        return df

    def get_bars_raw(self, logical: str, timeframe: str, count: int = 90) -> pd.DataFrame:
        """Raw broker-time bars with a 'time' column (no tz reinterpretation)."""
        df = self._raw_bars(logical, timeframe, count)
        cols = [c for c in ["time", "open", "high", "low", "close", "spread", "tick_volume"] if c in df.columns]
        return df[cols]

    def get_bars(self, logical: str, timeframe: str, count: int = 500) -> pd.DataFrame:
        """Recent OHLC(+spread) bars for ``logical`` at ``timeframe`` on a TRUE-UTC index."""
        df = self._raw_bars(logical, timeframe, count)
        idx = pd.DatetimeIndex(df["time"])
        df = df.set_index(to_true_utc(idx))
        df = df[df.index.notna()]
        cols = [c for c in ["open", "high", "low", "close", "spread", "tick_volume"] if c in df.columns]
        return df[cols].astype(float).sort_index()

    # ---- symbol spec (for sizing) ----------------------------------------
    def symbol_spec(self, logical: str) -> SymbolSpec:
        sym = self.broker_symbol(logical)
        if self._connected or self.live:
            import MetaTrader5 as mt5
            si = mt5.symbol_info(sym)
            if si is not None:
                return SymbolSpec(point=si.point, tick_size=si.trade_tick_size or si.point,
                                  tick_value=si.trade_tick_value or 1.0,
                                  volume_min=si.volume_min, volume_step=si.volume_step,
                                  digits=si.digits, volume_max=si.volume_max or 1e9,
                                  stops_level=(si.trade_stops_level or 0) * si.point,
                                  filling_mode=getattr(si, "filling_mode", 0))
        # dry-run fallback: use POINT_SIZE; tick_value unknown -> assume 1.0/point (R-accounting still exact)
        pt = POINT_SIZE.get(logical, 0.1)
        return SymbolSpec(point=pt, tick_size=pt, tick_value=1.0, volume_min=0.01,
                          volume_step=0.01, digits=2)

    @staticmethod
    def _snap_lots(raw: float, spec: SymbolSpec) -> float:
        """Snap a raw lot count to the symbol's volume grid, rounding to the NEAREST step.

        Nearest (not floor): on a coarse grid — Pepperstone NAS100 steps by 0.1 lot — flooring
        gave a persistent ~half-step DOWNWARD bias (ideal 0.375 -> 0.3 = 0.80R), which
        systematically under-sized against the backtest's 1R. Rounding to nearest centres the
        quantisation error (0.375 -> 0.4 = 1.07R), so the bias averages out. Any resulting
        over-risk is bounded by ``lots_for_risk``'s ``max_risk_R`` cap. Never below
        ``volume_min`` / above ``volume_max``."""
        step = spec.volume_step or 0.01
        lots = math.floor(max(raw, 0.0) / step + 0.5) * step   # round half up to the grid
        if lots < spec.volume_min:
            return spec.volume_min
        return round(min(lots, spec.volume_max), 2)

    def _loss_per_lot(self, logical: str, direction: int, entry_price: float,
                      sl_price: float, spec: SymbolSpec) -> float:
        """Account-currency loss of a full entry->SL move for 1.0 lot (>0), or 0.0 if unknown.

        Uses MT5 ``order_calc_profit`` (handles the instrument->deposit currency conversion
        natively) so USD-denominated symbols size correctly on a EUR account. Falls back to
        the tick-value formula only when MT5 is unavailable (offline/dry-run)."""
        if self._connected or self.live:
            import MetaTrader5 as mt5
            sym = self.broker_symbol(logical)
            otype = mt5.ORDER_TYPE_BUY if direction > 0 else mt5.ORDER_TYPE_SELL
            try:
                loss = mt5.order_calc_profit(otype, sym, 1.0, float(entry_price), float(sl_price))
            except Exception:
                loss = None
            if loss is not None and loss < 0:
                return abs(loss)
            logger.warning("order_calc_profit unavailable for %s -> tick-value sizing (may be off on cross-ccy)", logical)
        sl_dist = abs(entry_price - sl_price)
        return (sl_dist / spec.tick_size) * spec.tick_value if spec.tick_size > 0 else 0.0

    def lots_for_risk(self, logical: str, direction: int, entry_price: float,
                      sl_price: float, risk_budget: float) -> float:
        """Lots such that the loss entry->SL equals ``risk_budget`` in the ACCOUNT currency,
        snapped to the NEAREST point of the symbol's lot grid (see ``_snap_lots``).

        On a coarse grid (Pepperstone NAS100 steps by 0.1 lot) the snap can land above 1R.
        Past ``max_risk_R`` (config, 1.25R default) the entry is SKIPPED (returns 0.0); a
        materially-hot but sub-cap size (>1.10R) is logged. This keeps the uniform-1R assumption
        of the MC/prop model honest. Callers treat lots<=0 as "skip this entry, mark the day done"."""
        spec = self.symbol_spec(logical)
        loss_per_lot = self._loss_per_lot(logical, direction, entry_price, sl_price, spec)
        if loss_per_lot <= 0:
            return spec.volume_min                      # sizing info unavailable -> legacy fallback
        lots = self._snap_lots(risk_budget / loss_per_lot, spec)
        realized = lots * loss_per_lot
        mult = realized / risk_budget
        cap = float(self.cfg.get("max_risk_R", 1.25))
        if mult > cap:                                  # coarsest lot still overshoots the cap
            logger.warning("%s sizing: smallest lot %.2f risks %.2f (%.2fR) > %.2fR cap -> SKIP "
                           "entry (cannot size this stop to 1R on the lot grid)",
                           logical, lots, realized, mult, cap)
            return 0.0
        if mult > 1.10:                                 # nearest lot lands materially above 1R
            logger.warning("%s sizing: nearest lot %.2f risks %.2f (%.2fR > 1R) on a coarse lot grid "
                           "-> taking it (within %.2fR cap)", logical, lots, realized, mult, cap)
        return lots

    # ---- orders -----------------------------------------------------------
    def place_market(self, logical: str, direction: int, lots: float, sl: float,
                     tp: float | None, magic: int, comment: str, sl_dist: float,
                     ref_price: float, now_utc: pd.Timestamp,
                     time_exit_at: pd.Timestamp | None = None,
                     bars_held_limit: int | None = None) -> Position:
        sym = self.broker_symbol(logical)
        pos = Position(magic=magic, symbol=logical, direction=direction, lots=lots,
                       entry_price=ref_price, sl=sl, tp=tp, sl_dist=sl_dist,
                       open_time=now_utc, comment=comment, time_exit_at=time_exit_at,
                       bars_held_limit=bars_held_limit)
        if not self.live:
            self.paper[magic] = pos
            logger.info("[DRY-RUN] ENTER %s %s %.2f lots @~%.5f  SL=%.5f TP=%s  (%s)",
                        logical, "LONG" if direction > 0 else "SHORT", lots, ref_price,
                        sl, f"{tp:.5f}" if tp else "none", comment)
            self._log_trade({"time": now_utc.isoformat(), "event": "enter", "symbol": logical,
                             "dir": direction, "lots": lots, "price": round(ref_price, 5),
                             "sl": round(sl, 5), "tp": round(tp, 5) if tp else "", "reason": comment})
            return pos
        # LIVE
        import MetaTrader5 as mt5
        spec = self.symbol_spec(logical)
        price = self._tick_price(sym, direction > 0, mt5)   # MarketClosed if no quote
        # respect the broker's minimum stop distance (else the order is rejected)
        sl, tp = self._enforce_stops(price, direction, sl, tp, spec)
        lots = self._clamp_lots(lots, spec)
        req = {
            "action": mt5.TRADE_ACTION_DEAL, "symbol": sym, "volume": float(lots),
            "type": mt5.ORDER_TYPE_BUY if direction > 0 else mt5.ORDER_TYPE_SELL,
            "price": price, "sl": round(sl, spec.digits),
            "tp": round(tp, spec.digits) if tp else 0.0,
            "deviation": int(self.cfg.get("deviation_points", 20)), "magic": magic,
            "comment": comment[:31], "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": self._filling(spec, mt5),
        }
        res = self._send_retry(req, mt5)
        if res is None or res.retcode != mt5.TRADE_RETCODE_DONE:
            rc = getattr(res, "retcode", None)
            if rc == mt5.TRADE_RETCODE_MARKET_CLOSED:   # 10018 — expected daily break
                raise MarketClosed(f"{logical} market closed")
            logger.error("LIVE order_send FAILED %s: retcode=%s %s", logical,
                         rc, getattr(res, "comment", mt5.last_error()))
            raise RuntimeError(f"order_send failed: {rc}")
        pos.ticket = res.order
        pos.entry_price = res.price
        logger.info("[LIVE] ENTER %s %s %.2f lots @%.5f ticket=%s SL=%.5f TP=%s",
                    logical, "LONG" if direction > 0 else "SHORT", lots, res.price,
                    res.order, sl, f"{tp:.5f}" if tp else "none")
        self._log_trade({"time": now_utc.isoformat(), "event": "enter", "symbol": logical,
                         "dir": direction, "lots": lots, "price": round(res.price, 5),
                         "sl": round(sl, 5), "tp": round(tp, 5) if tp else "",
                         "reason": comment, "ticket": res.order})
        return pos

    # ---- live order helpers ----------------------------------------------
    @staticmethod
    def _tick_price(sym: str, want_ask: bool, mt5) -> float:
        """Current ask/bid, or raise MarketClosed if the terminal serves no usable quote.

        A symbol in its break does not always reject the order with 10018: MT5 may
        return None here (or a tick with 0.0 bid/ask) and the order is never sent.
        Typing that as MarketClosed keeps it on the runner's quiet log-once-and-retry
        path — otherwise it surfaces as an AttributeError and logs a full traceback
        every poll (every 20 s, i.e. thousands over a weekend) until the market reopens,
        rotating the useful history out of runner.log.
        """
        tick = mt5.symbol_info_tick(sym)
        price = (tick.ask if want_ask else tick.bid) if tick is not None else 0.0
        if not price or not math.isfinite(price):
            raise MarketClosed(f"{sym} has no quote (market closed)")
        return float(price)

    @staticmethod
    def _filling(spec: "SymbolSpec", mt5) -> int:
        """Pick a filling mode the symbol actually supports (bitmask 1=FOK, 2=IOC)."""
        fm = spec.filling_mode
        if fm & 2:
            return mt5.ORDER_FILLING_IOC
        if fm & 1:
            return mt5.ORDER_FILLING_FOK
        return mt5.ORDER_FILLING_RETURN

    @staticmethod
    def _enforce_stops(price: float, direction: int, sl: float, tp: float | None,
                       spec: "SymbolSpec") -> tuple[float, float | None]:
        """Widen SL/TP so they clear the broker's minimum stop distance (with a small pad)."""
        min_d = spec.stops_level + spec.point  # tiny pad over the hard minimum
        if min_d <= 0:
            return sl, tp
        if direction > 0:
            sl = min(sl, price - min_d)
            if tp is not None:
                tp = max(tp, price + min_d)
        else:
            sl = max(sl, price + min_d)
            if tp is not None:
                tp = min(tp, price - min_d)
        return sl, tp

    @staticmethod
    def _clamp_lots(lots: float, spec: "SymbolSpec") -> float:
        return float(min(max(lots, spec.volume_min), spec.volume_max))

    def _send_retry(self, req: dict, mt5, tries: int = 3):
        """order_send with a couple of retries on requote/price-off (refresh the price)."""
        res = mt5.order_send(req)
        for _ in range(tries - 1):
            if res is not None and res.retcode in (mt5.TRADE_RETCODE_DONE,):
                return res
            if res is not None and res.retcode in (mt5.TRADE_RETCODE_REQUOTE,
                                                   mt5.TRADE_RETCODE_PRICE_OFF,
                                                   mt5.TRADE_RETCODE_PRICE_CHANGED):
                req["price"] = self._tick_price(req["symbol"],
                                                req["type"] == mt5.ORDER_TYPE_BUY, mt5)
                res = mt5.order_send(req)
            else:
                break
        return res

    def open_position(self, magic: int) -> Position | None:
        if not self.live:
            return self.paper.get(magic)
        import MetaTrader5 as mt5
        for pp in (mt5.positions_get() or []):
            if pp.magic == magic:
                d = 1 if pp.type == mt5.POSITION_TYPE_BUY else -1
                return Position(magic=magic, symbol=self._logical_of(pp.symbol), direction=d,
                                lots=pp.volume, entry_price=pp.price_open, sl=pp.sl,
                                tp=pp.tp or None, sl_dist=abs(pp.price_open - pp.sl),
                                open_time=server_epoch_to_utc(pp.time),
                                comment=pp.comment, ticket=pp.ticket)
        return None

    def _logical_of(self, broker_sym: str) -> str:
        for k, v in self.symbol_map.items():
            if v == broker_sym:
                return k
        return broker_sym

    def close(self, pos: Position, exit_price: float, reason: str,
              now_utc: pd.Timestamp, cost_R: float = 0.0) -> float:
        """Close ``pos`` at ``exit_price``. Returns the realised R (net of ``cost_R``)."""
        R = pos.direction * (exit_price - pos.entry_price) / pos.sl_dist - cost_R
        if not self.live:
            self.paper.pop(pos.magic, None)
            self.realized_R += R
            logger.info("[DRY-RUN] EXIT  %s @%.5f  %s  R=%+.2f  (cumR=%+.1f)",
                        pos.symbol, exit_price, reason, R, self.realized_R)
            self._log_trade({"time": now_utc.isoformat(), "event": "exit", "symbol": pos.symbol,
                             "dir": pos.direction, "lots": pos.lots, "price": round(exit_price, 5),
                             "sl": "", "tp": "", "reason": self._tag(pos, reason), "R": round(R, 3),
                             "cumR": round(self.realized_R, 3)})
            return R
        import MetaTrader5 as mt5
        sym = self.broker_symbol(pos.symbol)
        spec = self.symbol_spec(pos.symbol)
        price = self._tick_price(sym, pos.direction < 0, mt5)   # MarketClosed if no quote
        req = {
            "action": mt5.TRADE_ACTION_DEAL, "symbol": sym, "volume": float(pos.lots),
            "type": mt5.ORDER_TYPE_SELL if pos.direction > 0 else mt5.ORDER_TYPE_BUY,
            "position": pos.ticket, "price": price,
            "deviation": int(self.cfg.get("deviation_points", 20)), "magic": pos.magic,
            "comment": f"exit_{reason}"[:31], "type_filling": self._filling(spec, mt5),
        }
        res = self._send_retry(req, mt5)
        if res is None or res.retcode != mt5.TRADE_RETCODE_DONE:
            rc = getattr(res, "retcode", None)
            if rc == mt5.TRADE_RETCODE_MARKET_CLOSED:   # 10018 — expected daily break
                raise MarketClosed(f"{pos.symbol} market closed")
            logger.error("LIVE close FAILED %s: retcode=%s %s", pos.symbol,
                         rc, getattr(res, "comment", mt5.last_error()))
            raise RuntimeError("close order_send failed")
        R = pos.direction * (res.price - pos.entry_price) / pos.sl_dist - cost_R
        logger.info("[LIVE] EXIT %s @%.5f %s R=%+.2f", pos.symbol, res.price, reason, R)
        self._log_trade({"time": now_utc.isoformat(), "event": "exit", "symbol": pos.symbol,
                         "dir": pos.direction, "lots": pos.lots, "price": round(res.price, 5),
                         "sl": "", "tp": "", "reason": self._tag(pos, reason), "R": round(R, 3),
                         "cumR": ""})
        return R

    # ---- dry-run bracket resolution --------------------------------------
    def resolve_paper(self, pos: Position, bar: pd.Series, now_utc: pd.Timestamp,
                      bars_held: int | None = None) -> tuple[bool, float, str]:
        """Resolve a PAPER position against one bar (stop wins ties, pessimistic).

        Returns (closed, exit_price, reason). Time-exits are checked by the runner via
        ``time_exit_at`` / ``bars_held_limit`` and passed through here for uniform close.
        """
        hi, lo = float(bar["high"]), float(bar["low"])
        hit_stop = lo <= pos.sl if pos.direction > 0 else hi >= pos.sl
        hit_take = (pos.tp is not None) and (hi >= pos.tp if pos.direction > 0 else lo <= pos.tp)
        if hit_stop:
            return True, pos.sl, "stop"
        if hit_take:
            return True, pos.tp, "take"
        if pos.time_exit_at is not None and now_utc >= pos.time_exit_at:
            return True, float(bar["close"]), "time_exit"
        if pos.bars_held_limit is not None and bars_held is not None and bars_held >= pos.bars_held_limit:
            return True, float(bar["close"]), "time_exit"
        return False, float("nan"), ""
