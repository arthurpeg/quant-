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
    "US500": "TLF (two-leg fade)",   # only TLF trades US500, so this one is unambiguous
    "GER40": "RVWAP (GER40 H1 VWAP NY)",   # seule sleeve sur GER40 -> non ambigu
    "US30": "RSKEW (US30 H4 skew 50)",     # seule sleeve sur US30  -> non ambigu
}

# magic / reason tag -> display label (must match strategies.MAGIC)
BRICK_LABEL = {
    "brick1": "brick 1 - NAS ORB",
    "brick2": "brick 2 - gold ToM",
    "brick3": "brick 3 - crypto",
    "brick4": "brick 4 - NAS IBS",
    "hmasto": "HMASTO - NAS M15 HMA/EMA cross + 3 osc (fwd-test, 0.5R)",
    "tlf": "TLF - two-leg fade, NAS100 + US500 M5 short-only (fwd-test, 0.5R)",
    "kaer": "KAER - NAS M15 ER breakout (RETIRED 2026-08-10, replaced by HMASTO)",
    "kelt": "KELT - BTC H1 Keltner breakout (RETIRED 2026-08-09)",
    "rvwap": "RVWAP - GER40 H1 VWAP de session NY (fwd-test, 1R)",
    "rskew": "RSKEW - US30 H4 asymetrie 50 (fwd-test, 1R)",
}
# ⚠️ THIS MAP MUST TRACK `strategies.MAGIC`. It is a SECOND, hand-maintained copy, so a
# new sleeve shows up as "?" in the journal until it is added here — which is exactly what
# happened to HMASTO (magic 108) on the day it was wired. The assertion below turns that
# silent gap into an import-time failure.
MAGIC_TAG = {101: "brick1", 102: "brick2", 103: "brick3", 104: "brick3", 105: "brick4",
             106: "kaer", 107: "kelt", 108: "hmasto", 109: "tlf", 110: "tlf",
             111: "rvwap", 112: "rskew"}

# ⚠️ DEUX UNITES DE R COEXISTENT, ET LES CONFONDRE FAUSSE LE TOTAL.
#   * le JOURNAL enregistre le R DE LA SLEEVE : un stop plein vaut -1.00 quelle que soit
#     la taille deployee, exactement comme le backtest de la sleeve le calcule ;
#   * le LIVRE raisonne en R DE COMPTE, ou 1 R = `risk_per_trade` du capital. Une sleeve
#     deployee a 0.5R n'y contribue que la MOITIE : `books_report.book_series` multiplie
#     bien sa serie par son poids.
# Sommer le journal a plat revenait donc a compter un stop TLF (0,5 % du capital perdu)
# comme un stop de la brique 1 (1 %). Signale par l'utilisateur le 2026-08-11.
# Ce facteur DOIT rester egal aux poids de `books_report.BOOKS['AGRESSIF']['w']` et aux
# `*_size_R` de config_live.yaml.
SIZE_R = {"brick1": 1.0, "brick2": 1.0, "brick3": 0.5, "brick4": 1.0,
          "hmasto": 0.5, "tlf": 0.5, "kaer": 0.5, "kelt": 0.5,
          # RVWAP et RSKEW sont deployees a 1R (instruction du 2026-08-18), donc
          # leur R de sleeve EST leur R de compte. Si la taille change dans
          # config_live.yaml, elle doit changer ICI aussi.
          "rvwap": 1.0, "rskew": 1.0}


def account_R(reason: str, symbol: str, R: float) -> float:
    """R du journal (unite sleeve) -> R de COMPTE (unite du livre)."""
    if R is None:
        return 0.0
    head = str(reason or "").split("_")[0].split(":")[0]
    if head not in SIZE_R:
        for m, t in MAGIC_TAG.items():
            if BRICK.get(symbol, "").startswith(t):
                head = t
                break
    return float(R) * SIZE_R.get(head, 1.0)


def _assert_magics_covered() -> None:
    """Fail loudly at import if a sleeve exists that the journal cannot name."""
    from edgelab.live.strategies import MAGIC
    missing = sorted(set(MAGIC.values()) - set(MAGIC_TAG))
    if missing:
        raise RuntimeError(
            f"summary.MAGIC_TAG is missing magic(s) {missing} present in "
            f"strategies.MAGIC -- add them (and a BRICK_LABEL) or the live journal "
            f"will report those positions as '?'.")
    unlabelled = sorted(set(MAGIC_TAG.values()) - set(BRICK_LABEL))
    if unlabelled:
        raise RuntimeError(f"summary.BRICK_LABEL is missing {unlabelled}")
    unsized = sorted(set(MAGIC_TAG.values()) - set(SIZE_R))
    if unsized:
        raise RuntimeError(
            f"summary.SIZE_R is missing {unsized} -- sans sa taille deployee, le R de "
            f"cette sleeve serait somme comme s'il valait 1 R de compte.")


_assert_magics_covered()


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
                # `R` reste le R DE LA SLEEVE tel que le journal l'ecrit (un stop plein
                # vaut -1.00 quelle que soit la taille deployee, comme dans le backtest
                # de la sleeve). `aR` est le meme trade en R DE COMPTE, seule unite dans
                # laquelle des sleeves de tailles differentes peuvent etre ADDITIONNEES.
                rec["aR"] = account_R(rec["reason"], rec["symbol"], rec["R"])
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
        Rs = [r["aR"] for r in exits]
        tot = sum(Rs); wins = [x for x in Rs if x > 0]; losses = [x for x in Rs if x <= 0]
        pf = (sum(wins) / -sum(losses)) if losses and sum(losses) != 0 else float("inf")
        yrs = max(span_days / 365.25, 1e-9)
        print(f"    total {tot:+.2f} R   ({tot/yrs:+.1f} R/yr extrapolated - noisy early)")
        print(f"    n={len(Rs)}  win {100*len(wins)/len(Rs):.0f}%  PF {pf:.2f}  "
              f"avg {tot/len(Rs):+.2f} R  best {max(Rs):+.2f}  worst {min(Rs):+.2f}")
        print(f"    ~cash @ 1R=100: {tot*100:+.0f} (account currency)")
        print("    R DE COMPTE : les sleeves a 0.5R (b3, HMASTO, TLF) comptent moitie, "
              "sinon\n    leur stop -- 0,5 % du capital -- pesait autant qu'un stop "
              "plein a 1 %.")

        # per brick
        print("\n  --- per brick (closed) ---")
        byb = defaultdict(list); bys = defaultdict(list)
        for r in exits:
            k = _brick(r["symbol"], r.get("reason", ""))
            byb[k].append(r["aR"]); bys[k].append(r["R"])
        for b in sorted(byb):
            v = byb[b]; w = sum(1 for x in v if x > 0)
            print(f"    {b:18} n={len(v):>3}  win {100*w/len(v):>3.0f}%  "
                  f"compte {sum(v):>+7.2f} R   (sleeve {sum(bys[b]):>+7.2f} R)")

        # per month
        print("\n  --- per month (closed) ---")
        bym = defaultdict(float); cntm = defaultdict(int)
        for r in exits:
            dt = _dt(r["time"])
            if dt:
                key = dt.strftime("%Y-%m"); bym[key] += r["aR"]; cntm[key] += 1
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
        Rs = [r["aR"] for r in exits]; tot = sum(Rs)
        w = [x for x in Rs if x > 0]; l = [x for x in Rs if x <= 0]
        pf = (sum(w) / -sum(l)) if l and sum(l) != 0 else float("inf")
        lines.append(f"closed {len(exits)} | realised {tot:+.2f} R | win {100*len(w)/len(Rs):.0f}% | PF {pf:.2f}")
        byb = defaultdict(float)
        for r in exits:
            byb[_brick(r["symbol"], r.get("reason", ""))] += r["aR"]
        lines.append("  " + " | ".join(f"{b.split('(')[0].strip()} {v:+.1f}R" for b, v in sorted(byb.items())))
    else:
        lines.append("closed 0 | realised +0.00 R (nothing closed yet)")
    # Le detail du jour, aussi dans ce repli texte : c'est le message qui part quand
    # l'embed echoue, et l'information la plus lue du rapport ne doit pas dependre du
    # format le plus fragile.
    from datetime import timezone
    today = _et_date(datetime.now(timezone.utc))
    t_ex = [r for r in exits if (_dt(r["time"]) and _et_date(_dt(r["time"])) == today)]
    if t_ex:
        lines.append("today: " + " | ".join(
            f"{_et_hm(r['time'])} {r['symbol']} {_side(r['dir'])} "
            f"{_sleeve_short(r.get('reason', ''), r['symbol'])} {r['aR']:+.2f}R" for r in t_ex))
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


def _et_date(dt: datetime, tz: str = "America/New_York"):
    from zoneinfo import ZoneInfo
    return dt.astimezone(ZoneInfo(tz)).date()


def _et_hm(s: str, tz: str = "America/New_York") -> str:
    """L'horodatage ISO du journal (UTC) en HH:MM ET, l'heure dans laquelle le rapport
    raisonne (sa date du jour, ses fenetres de session)."""
    d = _dt(s)
    if not d:
        return "??:??"
    from zoneinfo import ZoneInfo
    return f"{d.astimezone(ZoneInfo(tz)):%H:%M}"


def _side(d) -> str:
    return "SHORT" if str(d).lstrip("+") == "-1" else "LONG"


def _sleeve_short(reason: str, symbol: str) -> str:
    """Nom COURT de la sleeve, pour la table etroite des trades du jour.

    `_brick` rend le libelle complet ("TLF - two-leg fade, NAS100 + US500 M5 short-only
    (fwd-test, 0.5R)", 62 caracteres) : il deborde une colonne. On garde la meme source
    de verite (le tag du champ `reason`), on n'en montre que la tete.
    """
    head = str(reason or "").split("_")[0].split(":")[0]
    if head in BRICK_LABEL:
        return head if head.startswith("brick") else head.upper()
    return _brick(symbol, reason).split(" - ")[0].split(" (")[0]


def _still_open(row: dict, open_keys: set, open_syms: set) -> bool:
    """Cette ENTREE du jour correspond-elle a une position encore ouverte ?

    ⚠️ L'appariement se fait sur (symbole, SLEEVE), pas sur le symbole seul : NAS100 est
    traite par quatre sleeves a la fois (brique 1, brique 4, HMASTO, TLF). Si la brique 1
    a ferme son NAS100 aujourd'hui pendant qu'HMASTO tient encore le sien, l'appariement
    par symbole afficherait le trade FERME de la brique 1 comme "open".
    Les lignes anciennes, ecrites avant le tag de `reason`, n'ont pas de sleeve lisible :
    pour elles seulement, on retombe sur le symbole.
    """
    head = str(row.get("reason", "")).split("_")[0].split(":")[0]
    if head in BRICK_LABEL:
        return (row["symbol"], head) in open_keys
    return row["symbol"] in open_syms


def _today_trades_field(t_exits: list, t_entries: list, open_keys: set,
                        one_r: float | None) -> dict:
    """Le DETAIL des trades du jour : un par ligne, avec sa sleeve et ce qu'il a rendu.

    Le rapport ne publiait que l'agregat ("+0.00 R - 2 closed - 1 opened") : impossible
    de savoir QUELS trades avaient tourne, ni a quelle brique/sleeve ils appartenaient,
    alors que c'est precisement ce qu'on veut lire le soir. Demande de l'utilisateur,
    2026-08-12.

    Les SORTIES portent leur R (realise a la sortie, en R DE COMPTE comme tout le reste
    du rapport) ; les ENTREES du jour encore ouvertes sont listees avec "open" a la place
    du R, parce qu'un trade ouvert n'a rien rendu tant qu'il n'est pas ferme -- afficher
    son flottant comme un rendement melangerait deux choses.
    """
    fmt = "{:<6}{:<9}{:<6}{:<8}{:>7}{:>9}"
    rows = [fmt.format("ET", "symbol", "side", "sleeve", "R", "~cash")]
    for r in sorted(t_exits, key=lambda x: x["time"]):
        cash = f"{r['aR'] * one_r:+,.0f}" if one_r else "-"
        rows.append(fmt.format(_et_hm(r["time"]), r["symbol"][:8], _side(r["dir"]),
                               _sleeve_short(r.get("reason", ""), r["symbol"])[:7],
                               f"{r['aR']:+.2f}", cash))
    open_syms = {s for s, _ in open_keys}
    for r in sorted((e for e in t_entries if _still_open(e, open_keys, open_syms)),
                    key=lambda x: x["time"]):
        rows.append(fmt.format(_et_hm(r["time"]), r["symbol"][:8], _side(r["dir"]),
                               _sleeve_short(r.get("reason", ""), r["symbol"])[:7],
                               "open", "-"))
    if len(rows) == 1:
        return {"name": "\U0001F9FE Trades du jour", "inline": False,
                "value": "aucun trade aujourd'hui (ni entree ni sortie)."}
    n_shown, extra = 14, len(rows) - 1 - 14
    if extra > 0:                      # 1024 car. max par champ Discord
        rows = rows[:n_shown + 1] + [f"... +{extra} autre(s)"]
    rows.append("R de COMPTE - ~cash = R x 1R. 'open' = entree du jour non encore fermee.")
    return {"name": f"\U0001F9FE Trades du jour ({len(t_exits)} ferme(s), "
                    f"{len(t_entries)} ouvert(s))",
            "inline": False, "value": "```\n" + "\n".join(rows)[:1000] + "\n```"}


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
    # ⚠️ TOUT CE QUI EST AGREGE ICI EST EN R DE COMPTE (`aR`), jamais en R de sleeve.
    # Un stop TLF fait perdre 0,5 % du capital et doit peser -0.50 R, pas -1.00 : la
    # sleeve est deployee a 0.5R. Additionner le journal a plat comptait un stop TLF
    # comme un stop de la brique 1, qui coute le double.
    t_R = sum(r["aR"] for r in t_exits)
    tot = sum(r["aR"] for r in exits)
    wins = [r["aR"] for r in exits if r["aR"] > 0]
    losses = [r["aR"] for r in exits if r["aR"] <= 0]

    bal, init, eq = ctx.get("balance"), ctx.get("initial"), ctx.get("equity")
    # ⚠️ REFERENCE DU POURCENTAGE. `initial` N'EST PAS le depart du challenge : avec
    # `size_from_account: true` (le defaut), le runner y ecrit LE SOLDE LU AU DEMARRAGE
    # (`runner._sync_account_size`), et le reecrit a chaque reconnexion MT5. Mesurer la
    # progression du challenge contre lui revient a la mesurer depuis le dernier
    # redemarrage du runner — c'est ce qui affichait "+0.31 % de +15 %" alors que le
    # journal etait a -0.14 R. La reference est `challenge_start`, l'ancre FIXE du compte
    # ecrite une seule fois (voir `runner._challenge_anchor`). Signale par l'utilisateur
    # le 2026-08-12.
    ref = ctx.get("challenge_start") or init
    pnl_pct = ((bal / ref - 1.0) * 100.0) if (bal and ref) else 0.0
    colour = GREEN if (t_R > 0 or (not t_exits and pnl_pct > 0)) else RED if (t_R < 0 or pnl_pct < 0) else GREY

    # Positions ouvertes — depuis le BROKER, pas le journal. Resolues ICI, avant les
    # champs : la table des trades du jour doit savoir quelles entrees du jour sont
    # ENCORE ouvertes (elles n'ont pas de R tant qu'elles ne sont pas fermees).
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
    # (symbole, sleeve) et non le symbole seul : quatre sleeves se partagent NAS100.
    open_keys = {(p["symbol"], MAGIC_TAG.get(p.get("magic"), "?")) for p in pos}

    fields = []
    float_txt = f"\nflottant {eq - bal:+,.0f}" if (bal and eq) else ""
    fields.append({"name": "\U0001F4B0 Account", "inline": True,
                   "value": f"**{bal:,.2f}**\n1R {ctx.get('one_r', 0):,.2f} · "
                            f"{ctx.get('risk_pct', 0) * 100:.2f}%{float_txt}" if bal else "**n/a**"})
    fields.append({"name": "\U0001F4C5 Today", "inline": True,
                   "value": f"**{t_R:+.2f} R**\n{len(t_exits)} closed · {len(t_entries)} opened"})
    win_txt = f"win {100 * len(wins) / len(exits):.0f}%" if exits else "win —"
    fields.append({"name": "\U0001F4C8 Since start", "inline": True,
                   "value": f"**{tot:+.2f} R**\n{len(exits)} closed · {win_txt}"})

    fields.append(_today_trades_field(t_exits, t_entries, open_keys, ctx.get("one_r")))

    # prop challenge progress: where the balance sits between the -10% floor and +15% target
    tgt, dd = ctx.get("target_pct"), ctx.get("dd_pct")
    if bal and ref and tgt and dd:
        floor_cash, target_cash = ref * (1 - dd), ref * (1 + tgt)
        # Le journal converti en % DE COMPTE (1 R = `risk_per_trade` du capital) est le
        # seul chiffre comparable au cash. On publie les deux ET leur ecart : cet ecart
        # n'est pas du bruit, c'est exactement ce que le journal ne voit pas (swap,
        # commissions, trades non journalises, flottant des positions ouvertes).
        jr_pct = tot * float(ctx.get("risk_pct") or 0.0) * 100.0
        gap = pnl_pct - jr_pct
        val = [f"**{pnl_pct:+.2f}%** de l'objectif **+{tgt * 100:.0f}%** · "
               f"floor −{dd * 100:.0f}% a `{floor_cash:,.0f}` · cible `{target_cash:,.0f}`"]
        since = ctx.get("challenge_start_since")
        src = ("" if not since else " (fixee en config)" if since == "config"
               else f" (ancre du {since})")
        val.append(f"reference `{ref:,.0f}`" + (src if since else
                   " ⚠️ solde au dernier demarrage du runner, PAS le depart du challenge"))
        val.append(f"cash {pnl_pct:+.2f}% · journal {tot:+.2f} R = {jr_pct:+.2f}%"
                   + (f" · ecart {gap:+.2f}% (swap/commissions, trades hors journal, flottant)"
                      if abs(gap) >= 0.02 else ""))
        fields.append({"name": "\U0001F3AF Challenge", "inline": False,
                       "value": "\n".join(val)})

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
            byb[_brick(r["symbol"], r.get("reason", ""))].append(r)
        # colonne `sz` : la taille deployee de la sleeve, pour que le lecteur voie
        # POURQUOI une ligne a 0.5 contribue moitie moins que son R de sleeve.
        tbl = ["{:<20}{:>4}{:>5}{:>6}{:>8}".format("brick", "n", "sz", "win", "R")]
        for b in sorted(byb):
            v = byb[b]
            sz = SIZE_R.get(str(v[0].get("reason", "")).split("_")[0].split(":")[0], 1.0)
            # tronque : les libelles portent leur description complete (celui de TLF fait
            # 62 caracteres) et debordaient la colonne, cassant l'alignement du bloc.
            tbl.append("{:<20}{:>4}{:>5.1f}{:>5.0f}%{:>+8.2f}".format(
                b.split(" - ")[0][:20], len(v), sz,
                100 * sum(1 for x in v if x["aR"] > 0) / len(v),
                sum(x["aR"] for x in v)))
        pf = (sum(wins) / -sum(losses)) if losses and sum(losses) != 0 else float("inf")
        tbl.append("")
        tbl.append("PF {:.2f}   avg {:+.2f} R   best {:+.2f}   worst {:+.2f}".format(
            pf, tot / len(exits), max(r["aR"] for r in exits), min(r["aR"] for r in exits)))
        tbl.append("R de COMPTE (1 R = risk_per_trade) : une sleeve a sz 0.5 compte moitie.")
        fields.append({"name": "\U0001F9F1 By brick (closed, account-R)", "inline": False,
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
    # meme ancre que le runner : la config si elle la fixe, sinon le fichier qu'il a
    # ecrit sur la machine qui trade (absent ici -> le rapport dira que la reference
    # n'est pas le depart du challenge, au lieu de le laisser croire).
    anchor, since = prop.get("challenge_start_balance"), "config"
    if not anchor:
        try:
            import json
            d = json.loads((Path(__file__).resolve().parent / "_out" /
                            "account_start.json").read_text(encoding="utf-8"))
            anchor, since = float(d["balance"]), str(d.get("since", "?"))
        except Exception:
            anchor, since = None, None
    # Sans MT5 il n'y a pas de solde reel : on prend l'ancre comme solde fictif, sinon
    # l'apercu compare le nominal de config a l'ancre et affiche une progression inventee.
    if anchor:
        init = float(anchor)
    return {"balance": init, "initial": init, "one_r": init * rp, "risk_pct": rp,
            "challenge_start": float(anchor) if anchor else None,
            "challenge_start_since": since,
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
