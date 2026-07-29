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

# symbol -> which brick it belongs to
BRICK = {
    "NAS100": "brick1 (NAS ORB)",
    "XAUUSD": "brick2 (gold ToM)",
    "BTCUSD": "brick3 (crypto)",
    "ETHUSD": "brick3 (crypto)",
}


def _brick(symbol: str) -> str:
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
            byb[_brick(r["symbol"])].append(r["R"])
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
                  f"@ {e.get('price','?')}  ({_brick(s)})")
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
            byb[_brick(r["symbol"])] += r["R"]
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


def send_discord(webhook_url: str, text: str, code: bool = True) -> int:
    """POST ``text`` to a Discord webhook. ``code`` wraps it in a monospace block (good for
    the report table); set False for a plain short message (alerts, emojis). Returns status."""
    import json
    import urllib.request
    body = ("```\n" + text[:1900] + "\n```") if code else text[:1990]
    data = json.dumps({"content": body, "username": "edgelab.live"}).encode("utf-8")
    # Discord's edge rejects the default 'Python-urllib' UA with 403 -> send a real one.
    req = urllib.request.Request(webhook_url, data=data, headers={
        "Content-Type": "application/json",
        "User-Agent": "edgelab.live (https://github.com/arthurpeg/quant-, 1.0)",
    })
    with urllib.request.urlopen(req, timeout=15) as resp:
        return getattr(resp, "status", 204)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=str(DEFAULT_CSV), help="path to trades.csv")
    ap.add_argument("--discord", help="send the report to this Discord webhook URL (a test send)")
    args = ap.parse_args()
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
            code = send_discord(args.discord, build_report_text(Path(args.csv), hdr))
            print(f"sent to Discord (HTTP {code}) - check your channel")
        except Exception as exc:
            print(f"Discord send FAILED: {exc}")
            print("Check the webhook URL is the full one copied from Discord (Server Settings "
                  "> Integrations > Webhooks > Copy Webhook URL), not truncated.")
        return
    summarise(Path(args.csv))


if __name__ == "__main__":
    main()
