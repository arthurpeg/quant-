"""
backtest_breakout_us30.py — PROXY H1 de l'EA IntradayVolatilityBreakout (exp-005).
PAS l'EA : US30 (pas NAS100), H1 (pas M1). Teste le CONCEPT, pas l'implementation.
Logique repliquee : breakout de l'open de session US +/- k*ATR(D1), RR fixe, filtre de
regime ATR(3d)<ATR(20d), flat en fin de seance, cout reel en points.

Resultat (2019-2026, cout 6 pts A/R) : en "both directions" c'est PLAT (E[R] +0.010,
PF 1.02, Sharpe ~0). Le positif vient uniquement du cote LONG = derive haussiere du
marche, pas un edge. Le filtre bas-vol aide marginalement (vol = filtre, pas alpha).
Voir wiki/experiments/exp-005-mt5-intraday-vol-breakout.md.
"""
import json, os
import numpy as np
import pandas as pd

CACHE = os.path.join(os.path.dirname(__file__), "data_cache_mt5")
K_BREAK = 0.25      # ATR mult niveau de breakout (EA: ATR_Multiplier)
K_STOP  = 0.25      # ATR mult stop (EA: Stop_ATR_Multiplier)
RR      = 2.0       # TP = RR * stop
ATR_P   = 14
ENTRY_HOURS = [16, 17, 18]   # ~09:00-11:00 NY (EA window 16:30-18:05 serveur)
EXIT_HOUR   = 22             # flat ~15:00 NY (EA exit 22:55 serveur)
COST_POINTS = 6.0            # cout aller-retour en points (spread+slippage), hypothese prudente

def wilder_atr(df, n):
    h, l, c = df["high"], df["low"], df["close"]
    pc = c.shift(1)
    tr = pd.concat([(h-l), (h-pc).abs(), (l-pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/n, adjust=False).mean()

def load():
    h1 = pd.read_csv(f"{CACHE}/US30_H1.csv", index_col=0, parse_dates=True)
    d1 = pd.read_csv(f"{CACHE}/US30_D1.csv", index_col=0, parse_dates=True)
    for df in (h1, d1):
        if df.index.tz is None: df.index = df.index.tz_localize("UTC")
    d1 = d1.assign(atr14=wilder_atr(d1, ATR_P), atr3=wilder_atr(d1, 3), atr20=wilder_atr(d1, 20))
    return h1, d1

def run(direction="both", use_regime=True, regime_low=True):
    h1, d1 = load()
    # ATR de la veille (shift 1 => pas de look-ahead), indexe par date
    atr = d1[["atr14", "atr3", "atr20"]].shift(1)
    atr.index = atr.index.normalize()
    amap = {d.date(): r for d, r in atr.iterrows()}

    trades = []
    for day, g in h1.groupby(h1.index.normalize()):
        a = amap.get(day.date())
        if a is None or not np.isfinite(a["atr14"]) or a["atr14"] <= 0:
            continue
        if use_regime:
            low = a["atr3"] < a["atr20"]
            if regime_low and not low: continue
            if (not regime_low) and low: continue

        g = g.sort_index()
        hours = {ts.hour: row for ts, row in g.iterrows()}
        if 16 not in hours: continue
        open_ref = hours[16]["open"]
        atr14 = a["atr14"]
        upper = open_ref + K_BREAK * atr14
        lower = open_ref - K_BREAK * atr14
        stop_d = K_STOP * atr14
        tp_d   = K_STOP * RR * atr14

        # entree : 1er bar dont la CLOTURE casse un niveau (dans la fenetre)
        entry = None
        for hh in ENTRY_HOURS:
            if hh not in hours: continue
            close = hours[hh]["close"]
            if close >= upper and direction in ("both", "long"):
                entry = ("long", hh, close); break
            if close <= lower and direction in ("both", "short"):
                entry = ("short", hh, close); break
        if entry is None: continue
        side, ehour, epx = entry

        # sortie : bars suivants jusqu'a EXIT_HOUR ; TP/SL intrabar (SL prioritaire si ambigu)
        exit_R = None
        for hh in range(ehour + 1, EXIT_HOUR + 1):
            if hh not in hours: continue
            bar = hours[hh]
            hi, lo = bar["high"], bar["low"]
            if side == "long":
                hit_sl = lo <= epx - stop_d
                hit_tp = hi >= epx + tp_d
            else:
                hit_sl = hi >= epx + stop_d
                hit_tp = lo <= epx - tp_d
            if hit_sl: exit_R = -1.0; break          # conservateur
            if hit_tp: exit_R = +RR; break
        if exit_R is None:  # flat fin de seance
            rest = [h for h in range(ehour + 1, EXIT_HOUR + 1) if h in hours]
            last_h = max(rest) if rest else ehour
            cpx = hours[last_h]["close"]
            exit_R = ((cpx - epx) if side == "long" else (epx - cpx)) / stop_d

        cost_R = COST_POINTS / stop_d
        trades.append({"date": day.date(), "side": side, "R_gross": exit_R, "R_net": exit_R - cost_R})

    return pd.DataFrame(trades)

def stats(t, label):
    if len(t) == 0:
        print(f"{label:28s} : aucun trade"); return
    n = len(t); wr = (t["R_net"] > 0).mean()
    tot = t["R_net"].sum(); avg = t["R_net"].mean()
    gw = t.loc[t.R_net > 0, "R_net"].sum(); gl = -t.loc[t.R_net < 0, "R_net"].sum()
    pf = gw / gl if gl > 0 else np.inf
    per_year = n / ((pd.Timestamp(t['date'].max()) - pd.Timestamp(t['date'].min())).days/365.25 + 1e-9)
    sh_ann = avg / t["R_net"].std() * np.sqrt(per_year) if t["R_net"].std() > 0 else np.nan
    print(f"{label:28s} : n={n:4d}  win={wr:5.1%}  E[R]={avg:+.3f}  totR={tot:+7.1f}  PF={pf:4.2f}  Sh_ann={sh_ann:+.2f}")

if __name__ == "__main__":
    import sys
    try: sys.stdout.reconfigure(encoding="utf-8")
    except Exception: pass
    print("="*92)
    print(" PROXY H1 US30 de l'EA breakout (exp-005) — cout A/R =", COST_POINTS, "pts | RR =", RR)
    print(" ATTENTION : US30 != NAS100, H1 != M1 -> test du CONCEPT, pas de l'EA")
    print("="*92)
    print("\n--- Regime BAS de volatilite (ATR3<ATR20), comme l'EA par defaut ---")
    for d in ("both", "long", "short"):
        stats(run(d, use_regime=True, regime_low=True), f"regime-low / {d}")
    print("\n--- SANS filtre de regime (tous les jours) ---")
    for d in ("both", "long", "short"):
        stats(run(d, use_regime=False), f"no-regime / {d}")
    print("\n--- Regime HAUT de volatilite (ATR3>ATR20) ---")
    for d in ("both", "long", "short"):
        stats(run(d, use_regime=True, regime_low=False), f"regime-high / {d}")
    print("="*92)
