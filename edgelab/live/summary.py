"""Forward-test summary — a one-command readout of edgelab/live/_out/trades.csv.

Reads the trade journal the runner writes (one row per entry/exit, R on the exits) and
prints: realised R (total / per brick / per month), win rate + profit factor, and the
currently-open positions. Pure stdlib (no pandas) so it runs anywhere.

Run on the VPS from the repo root:
    py -3 -m edgelab.live.summary
    py -3 -m edgelab.live.summary --csv "C:\\path\\to\\trades.csv"
"""
from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from datetime import datetime
from pathlib import Path

DEFAULT_CSV = Path(__file__).resolve().parent / "_out" / "trades.csv"

# symbol -> which brick it belongs to. FALLBACK ONLY: NAS100 is traded by BOTH brick 1
# and brick 4, so this map cannot disambiguate it. The journal's `reason` field is the
# authority ("brick4_ibs_reversion" on entries, "brick4:ibs_high" on exits — see
# Broker._tag); this map is used only for legacy rows written before the tagging.
BRICK = {
    "NAS100": "brick1 (NAS ORB)",
    "XAUUSD": "brick2 (gold ToM)",
    "BTCUSD": "brick3 (crypto)",
    "ETHUSD": "brick3 (crypto)",
}

# magic / reason tag -> display label (must match strategies.MAGIC)
BRICK_LABEL = {
    "brick1": "brick 1 - NAS ORB",
    "brick2": "brick 2 - gold ToM",
    "brick3": "brick 3 - crypto",
    "brick4": "brick 4 - NAS IBS",
    "kaer": "KAER - NAS M15 ER breakout (fwd-test, 0.5R)",
}
MAGIC_TAG = {101: "brick1", 102: "brick2", 103: "brick3", 104: "brick3", 105: "brick4",
             106: "kaer"}


def _brick(symbol: str, reason: str = "") -> str:
    """Which brick a journal row belongs to — from its `reason` tag when present."""
    head = str(reason or "").split("_")[0].split(":")[0]
    if head in BRICK_LABEL:
        return BRICK_LABEL[head]
    return BRICK.get(symbol, f"other ({symbol})")


def _parse(csv_path: Path) -> list[dict]:
    """Parse the journal defensively. Fields 0-8 are consistent across all row types
    (time,event,symbol,dir,lots,price,sl,tp,reason); exits carry R at index 9."""
    rows: list[dict] = []
    with open(csv_path, newline="", encoding="utf-8") as fh:
        for r in csv.reader(fh):
            if len(r) < 9 or r[0] == "time":          # skip blanks + header
                continue
            event = r[1]
            if event not in ("enter", "exit"):
                continue
            rec = {"time": r[0], "event": event, "symbol": r[2], "dir": r[3],
                   "price": r[5], "reason": r[8]}
            if event == "exit" and len(r) >= 10:
                try:
                    rec["R"] = float(r[9])
                except ValueError:
                    rec["R"] = None
            rows.append(rec)
    return rows


def _dt(s: str) -> datetime | None:
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def summarise(csv_path: Path) -> None:
    print("=" * 64)
    print("  edgelab.live - forward-test summary")
    print(f"  {csv_path}")
    print("=" * 64)
    if not csv_path.exists():
        print("  no trades.csv yet — the runner writes it on the first entry/exit.")
        return
    rows = _parse(csv_path)
    if not rows:
        print("  journal is empty (no entries yet).")
        return

    entries = [r for r in rows if r["event"] == "enter"]
    exits = [r for r in rows if r["event"] == "exit" and r.get("R") is not None]
    times = [_dt(r["time"]) for r in rows if _dt(r["time"])]
    d0, d1 = (min(times), max(times)) if times else (None, None)
    span_days = ((d1 - d0).days + 1) if d0 else 0

    # open positions = per symbol, entries not yet matched by an exit (1 pos/symbol)
    net = defaultdict(int)
    last_entry = {}
    for r in rows:
        if r["event"] == "enter":
            net[r["symbol"]] += 1; last_entry[r["symbol"]] = r
        else:
            net[r["symbol"]] -= 1
    open_syms = [s for s, n in net.items() if n > 0]

    print(f"  Period : {d0.date() if d0 else '?'} .. {d1.date() if d1 else '?'}  "
          f"({span_days} day{'s' if span_days != 1 else ''})")
    print(f"  Trades : {len(entries)} entered | {len(exits)} closed | {len(open_syms)} open")

    # ---- realised R ----
    print("\n  --- realised R (closed trades) ---")
    if not exits:
        print("    no closed trades yet - R is only realised on exit (SL/TP/time-exit).")
    else:
        Rs = [r["R"] for r in exits]
        tot = sum(Rs); wins = [x for x in Rs if x > 0]; losses = [x for x in Rs if x <= 0]
        pf = (sum(wins) / -sum(losses)) if losses and sum(losses) != 0 else float("inf")
        yrs = max(span_days / 365.25, 1e-9)
        print(f"    total {tot:+.2f} R   ({tot/yrs:+.1f} R/yr extrapolated - noisy early)")
        print(f"    n={len(Rs)}  win {100*len(wins)/len(Rs):.0f}%  PF {pf:.2f}  "
              f"avg {tot/len(Rs):+.2f} R  best {max(Rs):+.2f}  worst {min(Rs):+.2f}")
        print(f"    ~cash @ 1R=100: {tot*100:+.0f} (account currency)")

        # per brick
        print("\n  --- per brick (closed) ---")
        byb = defaultdict(list)
        for r in exits:
            byb[_brick(r["symbol"], r.get("reason", ""))].append(r["R"])
        for b in sorted(byb):
            v = byb[b]; w = sum(1 for x in v if x > 0)
            print(f"    {b:18} n={len(v):>3}  win {100*w/len(v):>3.0f}%  totR {sum(v):>+7.2f}")

        # per month
        print("\n  --- per month (closed) ---")
        bym = defaultdict(float); cntm = defaultdict(int)
        for r in exits:
            dt = _dt(r["time"])
            if dt:
                key = dt.strftime("%Y-%m"); bym[key] += r["R"]; cntm[key] += 1
        for m in sorted(bym):
            print(f"    {m}   {bym[m]:>+7.2f} R   ({cntm[m]} trades)")

    # ---- open positions ----
    print("\n  --- open positions now ---")
    if not open_syms:
        print("    flat (no open positions).")
    else:
        for s in sorted(open_syms):
            e = last_entry.get(s, {})
            side = "LONG" if str(e.get("dir", "")).lstrip("+") not in ("-1",) else "SHORT"
            print(f"    {s:8} {side:5} entered {(_dt(e.get('time','')) or '?')}  "
                  f"@ {e.get('price','?')}  ({_brick(s, e.get('reason', ''))})")
    print("=" * 64)


def build_report_text(csv_path: Path, header: list[str] | None = None) -> str:
    """Compact one-message report (for Discord): heartbeat header + realised R + open pos."""
    lines = list(header) if header else []
    rows = _parse(csv_path) if csv_path.exists() else []
    if not rows:
        lines.append("no trades logged yet.")
        return "\n".join(lines)
    exits = [r for r in rows if r["event"] == "exit" and r.get("R") is not None]
    net = defaultdict(int); last_entry = {}
    for r in rows:
        if r["event"] == "enter":
            net[r["symbol"]] += 1; last_entry[r["symbol"]] = r
        else:
            net[r["symbol"]] -= 1
    open_syms = [s for s, n in net.items() if n > 0]
    if exits:
        Rs = [r["R"] for r in exits]; tot = sum(Rs)
        w = [x for x in Rs if x > 0]; l = [x for x in Rs if x <= 0]
        pf = (sum(w) / -sum(l)) if l and sum(l) != 0 else float("inf")
        lines.append(f"closed {len(exits)} | realised {tot:+.2f} R | win {100*len(w)/len(Rs):.0f}% | PF {pf:.2f}")
        byb = defaultdict(float)
        for r in exits:
            byb[_brick(r["symbol"], r.get("reason", ""))] += r["R"]
        lines.append("  " + " | ".join(f"{b.split('(')[0].strip()} {v:+.1f}R" for b, v in sorted(byb.items())))
    else:
        lines.append("closed 0 | realised +0.00 R (nothing closed yet)")
    if open_syms:
        parts = []
        for s in sorted(open_syms):
            e = last_entry.get(s, {})
            side = "LONG" if str(e.get("dir", "")).lstrip("+") != "-1" else "SHORT"
            parts.append(f"{s} {side}")
        lines.append("open: " + " | ".join(parts))
    else:
        lines.append("open: flat")
    return "\n".join(lines)


GREEN, RED, GREY = 0x3BA55D, 0xED4245, 0x4F545C


def _bar(frac: float, width: int = 14) -> str:
    n = max(0, min(width, int(round(max(0.0, min(1.0, frac)) * width))))
    return "█" * n + "░" * (width - n)


def _et_date(dt: datetime, tz: str = "America/New_York"):
    from zoneinfo import ZoneInfo
    return dt.astimezone(ZoneInfo(tz)).date()


def build_report_embed(csv_path: Path, ctx: dict) -> dict:
    """The daily heartbeat as a Discord EMBED (colour + fields) instead of a code block.

    ``ctx`` carries what only the runner knows: balance/1R/prop floors, the git commit,
    and — importantly — ``open_positions`` read from the BROKER rather than from the CSV.
    The journal can miss a position (one opened while the log path was unset stays absent
    forever), so the broker is the authority on what is open right now.
    """
    rows = _parse(csv_path) if csv_path.exists() else []
    exits = [r for r in rows if r["event"] == "exit" and r.get("R") is not None]
    entries = [r for r in rows if r["event"] == "enter"]
    now_et = ctx.get("now_et")
    today = _et_date(now_et) if now_et else None

    def _on_today(rs):
        out = []
        for r in rs:
            d = _dt(r["time"])
            if d and today and _et_date(d) == today:
                out.append(r)
        return out

    t_exits, t_entries = _on_today(exits), _on_today(entries)
    t_R = sum(r["R"] for r in t_exits)
    tot = sum(r["R"] for r in exits)
    wins = [r["R"] for r in exits if r["R"] > 0]
    losses = [r["R"] for r in exits if r["R"] <= 0]

    bal, init = ctx.get("balance"), ctx.get("initial")
    pnl_pct = ((bal / init - 1.0) * 100.0) if (bal and init) else 0.0
    colour = GREEN if (t_R > 0 or (not t_exits and pnl_pct > 0)) else RED if (t_R < 0 or pnl_pct < 0) else GREY

    fields = []
    fields.append({"name": "\U0001F4B0 Account", "inline": True,
                   "value": f"**{bal:,.2f}**\n1R {ctx.get('one_r', 0):,.2f} · "
                            f"{ctx.get('risk_pct', 0) * 100:.2f}%" if bal else "**n/a**"})
    fields.append({"name": "\U0001F4C5 Today", "inline": True,
                   "value": f"**{t_R:+.2f} R**\n{len(t_exits)} closed · {len(t_entries)} opened"})
    win_txt = f"win {100 * len(wins) / len(exits):.0f}%" if exits else "win —"
    fields.append({"name": "\U0001F4C8 Since start", "inline": True,
                   "value": f"**{tot:+.2f} R**\n{len(exits)} closed · {win_txt}"})

    # prop challenge progress: where the balance sits between the -10% floor and +15% target
    tgt, dd = ctx.get("target_pct"), ctx.get("dd_pct")
    if bal and init and tgt and dd:
        floor_cash, target_cash = init * (1 - dd), init * (1 + tgt)
        fields.append({"name": "\U0001F3AF Challenge", "inline": False,
                       "value": f"`{_bar(max(pnl_pct, 0) / (tgt * 100))}`  **{pnl_pct:+.2f}%** "
                                f"of +{tgt * 100:.0f}%\nfloor −{dd * 100:.0f}% at "
                                f"`{floor_cash:,.0f}` · target `{target_cash:,.0f}`"})

    # open positions — from the broker, not the journal
    pos = ctx.get("open_positions")
    if pos is None:                    # no broker view (CLI preview) -> derive from the journal
        net, last = defaultdict(int), {}
        for r in rows:
            net[r["symbol"]] += 1 if r["event"] == "enter" else -1
            if r["event"] == "enter":
                last[r["symbol"]] = r
        pos = [{"symbol": s, "direction": -1 if str(last[s]["dir"]).lstrip("+") == "-1" else 1,
                "entry_price": float(last[s]["price"]), "days": None,
                "magic": next((m for m, t in MAGIC_TAG.items()
                               if t == str(last[s]["reason"]).split("_")[0]), None)}
               for s, n in net.items() if n > 0]
    if pos:
        lines = []
        for p in sorted(pos, key=lambda x: x["symbol"]):
            side = "LONG" if p["direction"] > 0 else "SHORT"
            dot = "\U0001F7E2" if p["direction"] > 0 else "\U0001F534"
            held = f" · {p['days']}d" if p.get("days") is not None else ""
            lines.append(f"{dot} **{p['symbol']}** {side} · "
                         f"{BRICK_LABEL.get(MAGIC_TAG.get(p.get('magic'), ''), '?')} · "
                         f"@{p['entry_price']:,.2f}{held}")
        fields.append({"name": f"\U0001F4CC Open positions ({len(pos)})", "inline": False,
                       "value": "\n".join(lines)[:1024]})
    else:
        fields.append({"name": "\U0001F4CC Open positions", "inline": False, "value": "flat"})

    if exits:
        byb = defaultdict(list)
        for r in exits:
            byb[_brick(r["symbol"], r.get("reason", ""))].append(r["R"])
        tbl = ["{:<20}{:>4}{:>7}{:>8}".format("brick", "n", "win", "R")]
        for b in sorted(byb):
            v = byb[b]
            tbl.append("{:<20}{:>4}{:>6.0f}%{:>+8.2f}".format(
                b, len(v), 100 * sum(1 for x in v if x > 0) / len(v), sum(v)))
        pf = (sum(wins) / -sum(losses)) if losses and sum(losses) != 0 else float("inf")
        tbl.append("")
        tbl.append("PF {:.2f}   avg {:+.2f} R   best {:+.2f}   worst {:+.2f}".format(
            pf, tot / len(exits), max(r["R"] for r in exits), min(r["R"] for r in exits)))
        fields.append({"name": "\U0001F9F1 By brick (closed)", "inline": False,
                       "value": "```\n" + "\n".join(tbl)[:1000] + "\n```"})

    foot = f"{now_et:%a %d %b %Y · %H:%M} ET" if now_et else "edgelab.live"
    if ctx.get("commit"):
        foot += f" · commit {ctx['commit']}"
    if ctx.get("server"):
        foot += f" · {ctx['server']}"
    return {
        "title": "\U0001F4CA edgelab.live — daily report",
        "description": ("\U0001F7E2 runner **ALIVE**" if ctx.get("alive", True) else "\U0001F534 runner **DOWN**")
                       + f" · {ctx.get('n_bricks', 4)} bricks armed",
        "color": colour,
        "fields": fields,
        "footer": {"text": foot[:2048]},
    }


def send_discord(webhook_url: str, text: str | None = None, code: bool = True,
                 embed: dict | None = None) -> int:
    """POST to a Discord webhook. Pass ``embed`` for the rich daily report, or ``text``
    for a plain message (``code`` wraps it in a monospace block). Returns the HTTP status."""
    import json
    import urllib.request
    payload: dict = {"username": "edgelab.live"}
    if embed is not None:
        payload["embeds"] = [embed]
        if text:
            payload["content"] = text[:1990]
    else:
        payload["content"] = ("```\n" + (text or "")[:1900] + "\n```") if code else (text or "")[:1990]
    data = json.dumps(payload).encode("utf-8")
    # Discord's edge rejects the default 'Python-urllib' UA with 403 -> send a real one.
    req = urllib.request.Request(webhook_url, data=data, headers={
        "Content-Type": "application/json",
        "User-Agent": "edgelab.live (https://github.com/arthurpeg/quant-, 1.0)",
    })
    with urllib.request.urlopen(req, timeout=15) as resp:
        return getattr(resp, "status", 204)


def _cli_ctx() -> dict:
    """Best-effort report context for a CLI preview (no MT5): balances come from
    config_live.yaml, open positions are derived from the journal."""
    from datetime import timezone
    from zoneinfo import ZoneInfo
    cfg = {}
    try:
        import yaml
        cfg = yaml.safe_load(open(Path(__file__).resolve().parent / "config_live.yaml",
                                  encoding="utf-8")) or {}
    except Exception:
        pass
    prop = cfg.get("propfirm") or {}
    init = float(prop.get("initial_balance", 100000.0))
    rp = float(cfg.get("risk_per_trade", 0.01))
    return {"balance": init, "initial": init, "one_r": init * rp, "risk_pct": rp,
            "dd_pct": prop.get("max_total_drawdown_pct"), "target_pct": prop.get("profit_target_pct"),
            "now_et": datetime.now(timezone.utc).astimezone(ZoneInfo("America/New_York")),
            "alive": True, "n_bricks": 4}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=str(DEFAULT_CSV), help="path to trades.csv")
    ap.add_argument("--preview", action="store_true",
                    help="print the Discord embed JSON without sending it")
    ap.add_argument("--discord", help="send the report to this Discord webhook URL (a test send)")
    ap.add_argument("--alert-now", action="store_true",
                    help="fire the configured pre_session_alerts to Discord now (test)")
    args = ap.parse_args()
    if args.preview:
        import json
        import sys
        try:      # the Windows console defaults to cp1252 and cannot print the emoji
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
        print(json.dumps(build_report_embed(Path(args.csv), _cli_ctx()),
                         indent=2, ensure_ascii=False))
        return
    if args.alert_now:
        import yaml
        cfg = yaml.safe_load(open(Path(__file__).resolve().parent / "config_live.yaml", encoding="utf-8"))
        url = cfg.get("discord_webhook_url")
        alerts = cfg.get("pre_session_alerts") or []
        if not url:
            print("no discord_webhook_url in config"); return
        if not alerts:
            print("no pre_session_alerts found in config (block missing or wrong indentation)"); return
        for a in alerts:
            try:
                code = send_discord(url, f"[TEST alert] {a.get('msg', '')}", code=False)
                print(f"sent alert et={a.get('et','?')} (HTTP {code})")
            except Exception as exc:
                print(f"FAILED: {exc}")
        return
    if args.discord == "config":
        import yaml
        cfg_path = Path(__file__).resolve().parent / "config_live.yaml"
        args.discord = (yaml.safe_load(open(cfg_path, encoding="utf-8")).get("discord_webhook_url") or "")
    if args.discord:
        from datetime import datetime, timezone
        hdr = [f"edgelab.live TEST report - {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC"]
        if "TON_URL" in args.discord or "XXXX" in args.discord or "/webhooks/" not in args.discord:
            print("that is not a real webhook URL (still a placeholder). Paste the full URL "
                  "copied from Discord: https://discord.com/api/webhooks/<ID>/<TOKEN>")
            return
        try:
            code = send_discord(args.discord, embed=build_report_embed(Path(args.csv), _cli_ctx()))
            print(f"sent to Discord (HTTP {code}) - check your channel")
        except Exception as exc:
            print(f"Discord send FAILED: {exc}")
            print("Check the webhook URL is the full one copied from Discord (Server Settings "
                  "> Integrations > Webhooks > Copy Webhook URL), not truncated.")
        return
    summarise(Path(args.csv))


if __name__ == "__main__":
    main()
