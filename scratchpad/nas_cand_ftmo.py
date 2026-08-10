"""HMASTO CONTRE KAER, **NET DE TOUS LES FRAIS FTMO** — et probabilite du challenge.

Correction demandee par l'utilisateur (2026-08-10): *"le book a 40R est potentiellement
celui calcule une fois les frais overnight et overweek calcules sur les briques cryptos"*.
**C'est exactement ca**, et `scratchpad/ftmo_swaps.py` le confirme au dixieme:

    AGRESSIF   brut 47.38  ->  +commission 47.14  ->  +SWAP 40.90 R/an
               maxDD 17.36, RoMaD 2.36

Les 6.24 R/an manquants sont quasi tous CRYPTO (swap FTMO -30 %/an des DEUX cotes:
b3 BTC 6.41 -> 3.13, b3 ETH 5.50 -> 3.07); l'or perd 0.34 et l'IBS 0.51 en portant la nuit.

CE QUE CA CHANGE POUR L'ARBITRAGE — RIEN SUR LE SIGNE, TOUT SUR LE NIVEAU.
b1, KAER et HMASTO sont INTRADAY: 0.0 unite de swap par trade, et NAS100 est un indice
donc commission nulle. Les trois sleeves NAS100 traversent donc les frais FTMO intactes,
et l'echange KAER -> HMASTO ne cree aucun cout nouveau. Mais le LIVRE auquel on les
compare vaut 40.90 R/an et non 47.38, donc toutes les metriques de %/an, de RoMaD et de
ruine doivent etre refaites sur la serie NETTE — c'est ce que fait ce script.

Il repond aussi a la question posee: **P(valider le challenge) a 1 %/trade, HMASTO a
0.5 %**, et en combien de temps.

Le challenge FTMO tel que `monte_carlo_static.simulate` le modelise: cible +15 %,
drawdown statique -10 %, perte quotidienne max -5 %, bootstrap par blocs de 14 jours.

Usage:  python -u scratchpad/nas_cand_ftmo.py
"""
import sys, json, warnings
sys.path.insert(0, 'scratchpad'); sys.path.insert(0, '.')
warnings.filterwarnings('ignore')
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import numpy as np
import pandas as pd

import ftmo_swaps as FS
from edgelab.intraday.hma_stoch import run_hma_stoch, load_m15, HmaStochParams
from edgelab.reports.monte_carlo_static import simulate


def cand_frame():
    """La sleeve HMASTO au format des frames de `ftmo_swaps` (units=0: intraday)."""
    tr = run_hma_stoch("NAS100", HmaStochParams(), bars=load_m15("NAS100")).trades
    ex = pd.DatetimeIndex(pd.to_datetime(tr["exit_time"]))
    ex = ex.tz_convert("UTC") if ex.tz is not None else ex.tz_localize("UTC")
    f = pd.DataFrame({
        "exit_time": ex.tz_localize(None),
        "symbol": "NAS100",
        "R": tr["R"].to_numpy(float),
        # stop_pct sert au passage R -> % du notionnel pour facturer comm/swap;
        # ici les deux sont nuls (intraday + indice), mais on le renseigne quand meme.
        "stop_pct": (tr["sl_dist"] / tr["entry"]).to_numpy(float),
        "units": 0.0,
    })
    return f[f["exit_time"] >= FS.START].reset_index(drop=True)


def main():
    fr = FS.build()
    fr["CAND NAS"] = cand_frame()
    FS.SLEEVE_DIR["CAND NAS"] = 0                      # les deux sens -> pas de biais swap

    print("=" * 104)
    print("SLEEVES NAS100 INTRADAY — elles traversent les frais FTMO intactes")
    print("=" * 104)
    for n in ("b1 NAS ORB", "KAER NAS", "CAND NAS"):
        f = fr[n]
        Rn, c, s = FS.net_R(n, f)
        yrs = (f["exit_time"].max() - f["exit_time"].min()).days / 365.25
        print(f"  {n:<12} n={len(f):<5} unites/trade {f['units'].mean():.1f}  "
              f"brut {f['R'].sum()/yrs:+7.2f}  comm {-c.sum()/yrs:+6.2f}  "
              f"swap {-s.sum()/yrs:+6.2f}  NET {Rn.sum()/yrs:+7.2f} R/an  "
              f"({Rn.sum()/f['R'].sum()*100:.0f} % conserve)")

    BOOKS = {
        "AGRESSIF (live, KAER@0.5R)":
            {"b1 NAS ORB": 1.0, "b2 XAU ToM": 1.0, "b3 BTCUSD MACD": 1.0,
             "b3 ETHUSD MACD": 1.0, "b4 NAS IBS": 1.0, "KAER NAS": 0.5},
        "KAER -> CAND@0.5R":
            {"b1 NAS ORB": 1.0, "b2 XAU ToM": 1.0, "b3 BTCUSD MACD": 1.0,
             "b3 ETHUSD MACD": 1.0, "b4 NAS IBS": 1.0, "CAND NAS": 0.5},
        "les DEUX @0.5R (contre-epreuve)":
            {"b1 NAS ORB": 1.0, "b2 XAU ToM": 1.0, "b3 BTCUSD MACD": 1.0,
             "b3 ETHUSD MACD": 1.0, "b4 NAS IBS": 1.0, "KAER NAS": 0.5,
             "CAND NAS": 0.5},
        "CAND@1R au lieu de 0.5R":
            {"b1 NAS ORB": 1.0, "b2 XAU ToM": 1.0, "b3 BTCUSD MACD": 1.0,
             "b3 ETHUSD MACD": 1.0, "b4 NAS IBS": 1.0, "CAND NAS": 1.0},
        "sans sleeve intraday supplementaire":
            {"b1 NAS ORB": 1.0, "b2 XAU ToM": 1.0, "b3 BTCUSD MACD": 1.0,
             "b3 ETHUSD MACD": 1.0, "b4 NAS IBS": 1.0},
    }

    print("\n" + "=" * 104)
    print("LES LIVRES, NET DE COMMISSION **ET** DE SWAP FTMO")
    print("=" * 104)
    print(f"{'livre':<36}{'brut':>8}{'+comm':>8}{'NET':>8}{'maxDD':>8}"
          f"{'RoMaD':>7}{'Sharpe':>8}{'mois+':>7}")
    series = {}
    for nm, w in BOOKS.items():
        brut = FS.dmetrics(FS.book_daily(fr, w, "brut"))
        comm = FS.dmetrics(FS.book_daily(fr, w, "comm"))
        s = FS.book_daily(fr, w, "all")
        net = FS.dmetrics(s)
        series[nm] = s
        print(f"{nm:<36}{brut['Ryr']:>8.2f}{comm['Ryr']:>8.2f}{net['Ryr']:>8.2f}"
              f"{net['maxDD']:>8.2f}{net['RoMaD']:>7.2f}{net['Sharpe']:>8.2f}"
              f"{net['pos_months']*100:>6.0f}%")

    print("\n" + "=" * 104)
    print("MONTE-CARLO SUR LA SERIE NETTE — challenge FTMO (+15 % / -10 % statique / -5 % jour)")
    print("=" * 104)
    for nm in ("AGRESSIF (live, KAER@0.5R)", "KAER -> CAND@0.5R"):
        mc = simulate(series[nm].to_numpy())
        print(f"\n  {nm}   P(annee positive) = {(mc['annual'] > 0).mean():.1%}")
        for c, f in zip(mc["chal"], mc["fund"]):
            mo = f"{c['med_months']:.1f}" if c["med_months"] else "n/a"
            print(f"    {c['risk']:.2%}/trade -> passage {c['p_pass']:.1%} "
                  f"(median {mo} mois), echec DD {c['p_fail_dd']:.1%}, "
                  f"echec jour {c['p_fail_daily']:.1%} | funded ruine {f['p_ruin']:.1%}")

    # ---- la question posee: 1 %/trade, HMASTO a 0.5 % -> distribution du DELAI --------
    print("\n" + "=" * 104)
    print("LA REPONSE — book KAER->CAND@0.5R a 1 %/trade: combien de temps pour valider ?")
    print("=" * 104)
    R = series["KAER -> CAND@0.5R"].to_numpy()
    rng = np.random.default_rng(7)
    B, N, r = 14, 40000, 0.01
    T, DD, DAY = 0.15 / r, 0.10 / r, 0.05 / r

    def path(L):
        o = []
        while len(o) < L:
            st = rng.integers(0, len(R) - B)
            o.extend(R[st:st + B])
        return np.array(o[:L])

    days, npass, nfd, nfl = [], 0, 0, 0
    for _ in range(N):
        e, res = 0.0, None
        for t, x in enumerate(path(730)):
            if x <= -DAY:
                res = "fl"; break
            e += x
            if e <= -DD:
                res = "fd"; break
            if e >= T:
                res = "ps"; days.append(t + 1); break
        npass += res == "ps"; nfd += res == "fd"; nfl += res == "fl"
    d = np.array(days, float)
    print(f"  P(VALIDER)          = {npass/N:.1%}   sur {N:,} simulations de 2 ans")
    print(f"  P(echec drawdown)   = {nfd/N:.1%}    P(echec perte du jour) = {nfl/N:.1%}")
    print(f"  P(ni l'un ni l'autre en 2 ans) = {1-(npass+nfd+nfl)/N:.1%}")
    print(f"\n  DELAI DE VALIDATION (jours calendaires, sur les {len(d):,} passages):")
    for q in (10, 25, 50, 75, 90):
        v = np.percentile(d, q)
        print(f"    {q:>2}e pct : {v:6.0f} jours = {v/30.44:5.1f} mois")
    print(f"    moyenne : {d.mean():6.0f} jours = {d.mean()/30.44:5.1f} mois")
    for h in (30, 60, 90, 180, 365):
        print(f"    P(valide en moins de {h:>3} jours) = {(d <= h).mean()*npass/N:5.1%}")


if __name__ == "__main__":
    main()
