"""
backtest_breakout_nas100.py — port Python FIDELE de l'EA IntradayVolatilityBreakout
(exp-005), pour NAS100, reproduisant la semantique MT5 "Open prices only" sur M10.

But : seconde implementation independante pour verifier les chiffres MT5 et balayer
les configurations (robustesse) sans relancer le testeur a la main.

Donnees : tirees du terminal MT5 (PepperstoneUK-Demo) via MetaTrader5 python, cachees
en data_cache_mt5/NAS100_M10.parquet (barres M10, temps SERVEUR broker) et
NAS100_D1.parquet. Les OHLC sont des prix BID ; 'spread' est en points (point=0.1).

Semantique repliquee (cf. mql5/IntradayVolatilityBreakout.mq5) :
  - ATR(D1) Wilder, periodes 14 / 3 / 20, lues au shift 1 (jour precedent) -> pas de leak.
  - Niveaux calcules a l'open de la barre M10 de 16:30 (serveur) : open +/- K_BREAK*ATR14.
  - Confirmation candle-close : a l'ouverture de la barre t, on lit la CLOTURE de t-1
    (iClose(TF,1)) ; cassure -> entree a l'open de t (ask pour long, bid pour short).
  - Fenetre d'entree [16:30, 18:05), 1 trade/jour, long teste avant short.
  - Filtre de regime : ATR3 < ATR20 * factor (bas-vol) ou > (haut-vol).
  - SL = K_STOP*ATR14, TP = K_STOP*RR*ATR14 ; resolus intrabar sur les barres M10
    suivantes avec l'ordre de parcours MT5 (barre haussiere O->L->H->C, baissiere
    O->H->L->C). Sinon flat a l'open de la 1re barre >= 22:55 (Exit_Time).
  - Spread integre : long entre a l'ask (bid+spread), short rachete a l'ask.

Sortie en R-multiples -> PF, win%, E[R] independants du sizing (comparables au PF MT5).
"""
import os, argparse
import numpy as np
import pandas as pd

CACHE = os.path.join(os.path.dirname(__file__), "data_cache_mt5")
POINT = 0.1  # NAS100 : digits=1, point=0.1

# --- defauts = valeurs par defaut de l'EA ---
# spread_pts : cout d'execution EFFECTIF a l'entree (spread + slippage) en points MT5.
#   CALIBRE = 100 pts (= 10 unites prix) pour reproduire le run MT5 "ticks reels" 2024->2025-05
#   (PF 1.31, win 47.9%). Le champ 'spread' des barres (~13 pts) sous-estime le vrai spread a
#   l'ouverture US ; mettre 0 pour un backtest "sans cout", ~60 pts pour imiter MT5 open-prices.
DEF = dict(k_break=0.25, k_stop=0.25, rr=2.0, atr_p=14, regime_short=3, regime_long=20,
           regime_factor=1.0, regime_mode="low", direction="both",
           entry="16:30", max_entry="18:05", exit="22:55", tf_min=10, spread_pts=100.0,
           point=0.1,        # taille du point MT5 (NAS100/US30=0.1, or=0.01, argent/oil/gaz=0.001)
           reverse=False)    # False = breakout (momentum) ; True = fade la cassure (mean-reversion)

def wilder_atr(df, n):
    h, l, c = df["high"], df["low"], df["close"]
    pc = c.shift(1)
    tr = pd.concat([(h - l), (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / n, adjust=False).mean()

def hm(s):  # "16:30" -> minutes
    h, m = s.split(":"); return int(h) * 60 + int(m)

def load(symbol="NAS100"):
    m10 = pd.read_parquet(f"{CACHE}/{symbol}_M10.parquet").sort_values("time").reset_index(drop=True)
    d1 = pd.read_parquet(f"{CACHE}/{symbol}_D1.parquet").sort_values("time").reset_index(drop=True)
    d1 = d1.assign(atr14=wilder_atr(d1, DEF["atr_p"]),
                   atr3=wilder_atr(d1, DEF["regime_short"]),
                   atr20=wilder_atr(d1, DEF["regime_long"]))
    # ATR de la veille (shift 1), indexe par date
    a = d1[["atr14", "atr3", "atr20"]].shift(1)
    a.index = d1["time"].dt.normalize()
    amap = {d.date(): (r.atr14, r.atr3, r.atr20) for d, r in a.iterrows()}
    m10["min"] = m10["time"].dt.hour * 60 + m10["time"].dt.minute
    m10["date"] = m10["time"].dt.date
    return m10, amap

def resolve_bar(side, o, h, l, c, sl, tp, spread_px):
    """Rend ('sl'|'tp', prix_bid_execution) ou None. Ordre intrabar facon MT5."""
    seq = ["L", "H"] if c >= o else ["H", "L"]  # haussiere: bas d'abord
    for ext in seq:
        if side == "long":                       # bid touche sl/tp
            if ext == "L" and l <= sl: return "sl", sl
            if ext == "H" and h >= tp: return "tp", tp
        else:                                     # short : l'ask (bid+spread) touche
            if ext == "H" and (h + spread_px) >= sl: return "sl", sl - spread_px
            if ext == "L" and (l + spread_px) <= tp: return "tp", tp - spread_px
    return None

def run(cfg=None, date_from=None, date_to=None, m10=None, amap=None):
    p = dict(DEF); p.update(cfg or {})
    if m10 is None: m10, amap = load()
    if date_from: m10 = m10[m10["time"] >= pd.Timestamp(date_from)]
    if date_to:   m10 = m10[m10["time"] <  pd.Timestamp(date_to)]

    e_min, mx_min, x_min = hm(p["entry"]), hm(p["max_entry"]), hm(p["exit"])
    tf = p["tf_min"]; kb, ks, rr = p["k_break"], p["k_stop"], p["rr"]
    sprd = p["spread_pts"] * p["point"]          # cout d'execution effectif (fixe, calibre)
    rev = p["reverse"]
    trades = []
    for day, g in m10.groupby("date", sort=True):
        a = amap.get(day)
        if a is None or not np.isfinite(a[0]) or a[0] <= 0: continue
        atr14, atr3, atr20 = a
        low_vol = atr3 < atr20 * p["regime_factor"]
        if p["regime_mode"] == "low" and not low_vol: continue
        if p["regime_mode"] == "high" and low_vol: continue

        g = g.sort_values("min")
        rows = list(g.itertuples(index=False))
        by_min = {r.min: r for r in rows}
        if e_min not in by_min: continue          # pas de barre a 16:30
        open_ref = by_min[e_min].open
        upper = open_ref + kb * atr14
        lower = open_ref - kb * atr14
        stop_d = ks * atr14
        tp_d = ks * rr * atr14

        # --- entree : 1re barre t de la fenetre dont la cloture de t-1 casse un niveau ---
        entry = None
        for i, r in enumerate(rows):
            if r.min <= e_min: continue            # t doit etre > 16:30 (t-1 = barre de 16:30+)
            if r.min >= mx_min: break              # hors fenetre
            prev = rows[i - 1]
            lvl = "up" if prev.close >= upper else ("down" if prev.close <= lower else None)
            if lvl is None: continue
            # momentum : up->long, down->short ; reverse (fade) : up->short, down->long
            side = ("long" if lvl == "up" else "short")
            if rev: side = "short" if side == "long" else "long"
            if p["direction"] == "long" and side != "long": continue
            if p["direction"] == "short" and side != "short": continue
            epx = r.open + sprd if side == "long" else r.open   # long paye l'ask
            entry = (side, i, epx); break
        if entry is None: continue
        side, ei, epx = entry
        if side == "long":
            sl, tp = epx - stop_d, epx + tp_d
        else:
            sl, tp = epx + stop_d, epx - tp_d

        # --- sortie : SL/TP intrabar (barre d'entree incluse), sinon flat a la 1re barre >= exit ---
        R = None
        res0 = resolve_bar(side, epx, rows[ei].high, rows[ei].low, rows[ei].close, sl, tp, sprd)
        if res0:
            R = (-1.0 if res0[0] == "sl" else rr)
        for r in (rows[ei + 1:] if R is None else []):
            if r.min >= x_min:                     # exit time -> flat a l'open
                R = ((r.open - epx) if side == "long" else (epx - (r.open + sprd))) / stop_d
                break
            res = resolve_bar(side, r.open, r.high, r.low, r.close, sl, tp, sprd)
            if res:
                R = (-1.0 if res[0] == "sl" else rr)
                break
        if R is None:                              # pas de barre exit -> derniere barre du jour
            last = rows[-1]
            R = ((last.close - epx) if side == "long" else (epx - (last.close + sprd))) / stop_d
        trades.append(dict(date=day, side=side, R=R))
    return pd.DataFrame(trades)

def stats(t, label=""):
    if len(t) == 0:
        return dict(label=label, n=0)
    n = len(t); wr = (t.R > 0).mean()
    gw = t.loc[t.R > 0, "R"].sum(); gl = -t.loc[t.R < 0, "R"].sum()
    pf = gw / gl if gl > 0 else np.inf
    per_year = n / (((pd.Timestamp(max(t.date)) - pd.Timestamp(min(t.date))).days / 365.25) + 1e-9)
    sh = t.R.mean() / t.R.std() * np.sqrt(per_year) if t.R.std() > 0 else np.nan
    return dict(label=label, n=n, win=wr, ER=t.R.mean(), totR=t.R.sum(), PF=pf, Sh_ann=sh,
                longs=(t.side == "long").sum(), shorts=(t.side == "short").sum())

def pr(s):
    if s["n"] == 0: print(f"{s['label']:34s}: aucun trade"); return
    print(f"{s['label']:34s}: n={s['n']:4d}  win={s['win']:5.1%}  E[R]={s['ER']:+.3f}  "
          f"totR={s['totR']:+7.1f}  PF={s['PF']:4.2f}  Sh_ann={s['Sh_ann']:+.2f}  "
          f"(L{s['longs']}/S{s['shorts']})")

if __name__ == "__main__":
    import sys
    try: sys.stdout.reconfigure(encoding="utf-8")
    except Exception: pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="d0", default=None)
    ap.add_argument("--to", dest="d1", default=None)
    a = ap.parse_args()
    m10, amap = load()
    print(f"Data M10: {m10.time.min()} -> {m10.time.max()}  ({len(m10)} barres)")
    print("="*100)
    # validation vs MT5
    for lbl, d0, d1 in [("2024-01->2026-04 (MT5 open-prices PF~1.40)", "2024-01-01", "2026-05-01"),
                        ("2024-01->2025-05 (MT5 ticks reels PF~1.31)", "2024-01-01", "2025-06-01"),
                        ("full data (2023-09->2026)", None, None)]:
        pr(stats(run(date_from=d0, date_to=d1, m10=m10, amap=amap), lbl))
