"""PARITE BACKTEST <-> LIVE des deux sleeves `research/` (RVWAP, RSKEW).

    python check_live_parity_research.py [--bars 5000] [--n 400]

CE QUE CE SCRIPT PROUVE, ET COMMENT.

Le backtest (`run_research_sleeve`) voit TOUT l'historique d'un coup. Le runner,
lui, ne voit jamais qu'une FENETRE : `broker.get_bars(symbol, tf, N)` rend les N
dernieres barres, et la barre en cours est jetee. Deux choses peuvent donc
diverger sans que rien ne casse bruyamment :

  * le RANG CAUSAL est calcule sur les 1 000 dernieres OCCURRENCES du signal ; si
    la fenetre tiree n'en contient pas 1 000, le rang vaut autre chose et les
    entrees changent -- silencieusement ;
  * la BARRIERE DE TEMPS compte des barres du cadre du broker, et une fenetre
    tronquee peut ne plus contenir la barre d'entree.

Le harnais rejoue donc l'histoire barre par barre en TRONQUANT la frame comme MT5
l'aurait servie, appelle le MEME `decide()` que le live, resout le trade avec la
MEME geometrie, et compare trade par trade au backtest complet. **Zero ecart
tolere** sur : date d'entree, date de sortie, sens, distance de stop (1R) et R.

CE QU'IL NE PROUVE PAS. Il prouve que la DECISION et la GEOMETRIE coincident.
Il ne prouve pas le slippage, le spread reel au fill, ni le comportement du
broker sur gap -- ceux-la se mesurent en dry-run puis en live, pas ici.
"""
from __future__ import annotations

import argparse
import sys

import numpy as np
import pandas as pd

from edgelab.intraday.research_sleeves import (SLEEVES, decide, load_bars,
                                               run_research_sleeve, signal_series)


def replay_windowed(name: str, window: int, start_i: int) -> pd.DataFrame:
    """Rejoue depuis la barre `start_i` EN NE VOYANT QU'UNE FENETRE a chaque pas.

    `start_i` DOIT etre la barre de signal d'un trade du backtest complet, sinon
    les deux rejeux ne partent pas du meme etat d'occupation : le backtest peut
    etre DEJA EN POSITION a cette barre et sauter le signal que le rejeu, parti a
    froid, prendrait. La premiere version de ce harnais demarrait a un index
    arbitraire et signalait un faux ecart pour cette seule raison.
    """
    p = SLEEVES[name]
    b = load_bars(p)
    o = b["open"].to_numpy(float)
    h = b["high"].to_numpy(float)
    lo = b["low"].to_numpy(float)
    n = len(b)

    rows = []
    i = int(start_i)
    while i < n - 1:
        # LA FRAME QUE LE RUNNER AURAIT VUE : les `window` dernieres barres
        # CLOSES, barre en formation deja exclue (elle l'est par construction ici,
        # puisqu'on decide a la cloture de i).
        frame = b.iloc[max(0, i - window + 1):i + 1]
        got = decide(frame, p)
        if got is None:
            i += 1
            continue
        side, dist = got

        e = i + 1
        px_in = o[e]
        stop = px_in - side * dist
        exit_i = px_out = why = None
        for j in range(p.max_bars):
            k = e + j
            if k >= n:
                break
            if side * (o[k] - stop) <= 0:
                exit_i, px_out, why = k, o[k], "gap_stop"
                break
            worst = lo[k] if side > 0 else h[k]
            if side * (worst - stop) <= 0:
                exit_i, px_out, why = k, stop, "stop"
                break
        if exit_i is None:
            k = min(e + p.max_bars, n - 1)
            exit_i, px_out, why = k, o[k], "time_exit"

        rows.append(dict(entry_time=b.index[e], exit_time=b.index[exit_i],
                         direction=int(side), sl_dist=float(dist), reason=why,
                         R=float(side * (px_out - px_in) / dist)))
        i = max(exit_i - 1, i + 1)
    return pd.DataFrame(rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", type=int, default=0,
                    help="fenetre simulee ; 0 = celle de la config live")
    ap.add_argument("--n", type=int, default=400, help="derniers trades compares")
    a = ap.parse_args()

    default_window = {"RVWAP": 5000, "RSKEW": 1500}
    fails = 0
    print("=" * 96)
    print("PARITE BACKTEST <-> LIVE — sleeves research/ (RVWAP, RSKEW)")
    print("=" * 96)

    for name in ("RVWAP", "RSKEW"):
        p = SLEEVES[name]
        window = a.bars or default_window[name]
        full = run_research_sleeve(name).trades
        # SYNCHRONISATION : on demarre le rejeu sur la barre de SIGNAL d'un trade
        # du backtest, donc a un instant ou les deux sont a plat.
        b_all = load_bars(p)
        want = max(0, len(full) - a.n)
        sig_ts = full["signal_time"].iloc[want] if "signal_time" in full else None
        start_i = int(b_all.index.get_indexer([sig_ts])[0]) if sig_ts is not None else window
        if start_i < window:
            start_i = int(b_all.index.get_indexer(
                [full[full["signal_time"] >= b_all.index[window]]["signal_time"].iloc[0]])[0])
        win = replay_windowed(name, window, start_i)
        if full.empty or win.empty:
            print(f"  {name}: AUCUN TRADE -- parite non evaluable")
            fails += 1
            continue

        # on compare sur l'intersection temporelle des deux rejeux
        t0 = win["entry_time"].min()
        f = full[full["entry_time"] >= t0].reset_index(drop=True)
        w = win[win["entry_time"] >= t0].reset_index(drop=True)

        print(f"\n  --- {name} ({p.symbol} {p.timeframe}, fenetre simulee {window} barres)")
        print(f"      backtest complet : {len(full)} trades | rejeu fenetre : {len(win)}")
        print(f"      fenetre comparee : {t0.date()} -> {w['exit_time'].max().date()} "
              f"({len(f)} contre {len(w)} trades)")

        if len(f) != len(w):
            print(f"      ECHEC : nombre de trades different ({len(f)} vs {len(w)})")
            fails += 1
            # montrer les 3 premieres divergences de date
            m = min(len(f), len(w))
            for k in range(m):
                if f["entry_time"][k] != w["entry_time"][k]:
                    print(f"        1er ecart au trade {k}: backtest {f['entry_time'][k]} "
                          f"vs live {w['entry_time'][k]}")
                    break
            continue

        d_entry = int((f["entry_time"] != w["entry_time"]).sum())
        d_exit = int((f["exit_time"] != w["exit_time"]).sum())
        d_dir = int((f["direction"] != w["direction"]).sum())
        d_sl = float(np.max(np.abs(f["sl_dist"] - w["sl_dist"])))
        d_R = float(np.max(np.abs(f["R"] - w["R"])))
        ok = (d_entry == 0 and d_exit == 0 and d_dir == 0
              and d_sl < 1e-9 and d_R < 1e-9)
        print(f"      dates d'entree differentes : {d_entry}")
        print(f"      dates de sortie differentes: {d_exit}")
        print(f"      sens differents            : {d_dir}")
        print(f"      ecart max sur 1R           : {d_sl:.3e}")
        print(f"      ecart max sur R            : {d_R:.3e}")
        print(f"      -> {'PARITE PROUVEE' if ok else 'ECHEC'}")
        fails += 0 if ok else 1

        # garde-fou supplementaire : la fenetre contient-elle assez d'OCCURRENCES ?
        b = load_bars(p)
        tail = b.iloc[-window:]
        occ = int(np.isfinite(signal_series(tail, p)).sum())
        margin = occ / p.rank_win
        print(f"      occurrences du signal dans la fenetre : {occ} pour "
              f"{p.rank_win} requises ({margin:.2f}x)"
              + ("" if margin >= 1.0 else "   <-- FENETRE TROP COURTE"))
        if margin < 1.0:
            fails += 1

    print("\n" + "=" * 96)
    print("PARITE : " + ("2/2 PROUVEE" if fails == 0 else f"ECHEC ({fails} probleme(s))"))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
