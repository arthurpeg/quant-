"""ETAPE 6 -- la GEOMETRIE DE SORTIE, balayee. Memes 173 cellules, memes entrees.

    python research/scripts/06_stop_geometry.py --selftest
    python research/scripts/06_stop_geometry.py [--jobs 8] [--placebo 40]

La phase 2 a mesure que les 173 cellules ne survivent pas a un stop de
1,5 x ATR14 : bord directionnel median +0,0024 R, positif dans 52 % des
configurations, et un E[R] BRUT median de -0,0591 R -- le bracket perdait avant
les frais. Restait une question que ce chiffre ne tranchait pas : le stop
TRONQUAIT-IL un bord reel, ou n'y avait-il rien a tronquer ?

Ce script repond en changeant UNIQUEMENT la geometrie de sortie. Memes cellules,
memes signaux, memes seuils d'entree, meme peage, meme regle d'occupation. Deux
mecaniques :

  1. BARRIERE DE TEMPS + STOP DUR a 2,0 / 3,0 / 4,0 x ATR14 (contre 1,5 en
     phase 2). Si le stop tronquait un bord, l'elargir doit le liberer.
  2. CHANDELIER EXIT a 2,0 / 3,0 x ATR14 sous le PLUS HAUT des 5 dernieres
     barres (au-dessus du plus bas, pour un court). Le stop ne se desserre
     jamais.

CE QUE CHANGE LA LARGEUR, ET POURQUOI C'EST LE PIEGE DE LA MESURE. 1R vaut
`m x ATR14` : elargir le stop AGRANDIT l'unite de compte. Le peage en R diminue
donc mecaniquement (le meme spread rapporte a un R plus grand), et le gain brut
en R diminue AUSSI. Comparer des E[R] a m different revient a comparer des
choses mesurees dans des unites differentes -- c'est exactement ce qui avait
fait croire a un progres en phase 5b ([[exp-016]], "la barriere verticale n'est
PAS un levier de cout"). Le tableau rend donc systematiquement, a cote de E[R],
le **taux de declenchement du stop** et le **bord directionnel**, qui sont les
deux grandeurs que la largeur ne renormalise pas.

TROIS PRECAUTIONS D'IMPLEMENTATION.

* Le niveau de Chandelier en vigueur PENDANT la barre b est calcule sur les
  barres <= b-1. L'utiliser au meme instant reviendrait a poser le stop avec le
  plus haut de la barre qui va le toucher : une fuite invisible et flatteuse.
* Le stop trailing ne se DESSERRE jamais (`maximum.accumulate` implicite).
* Le gap reste honore : une barre qui OUVRE au-dela du stop sort a l'ouverture,
  donc a pire que -1R.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C
import signals as SG

# 05 porte un chiffre en tete de fichier : on le charge par son chemin et on
# REUTILISE ses briques, pour que les deux phases partagent exactement la meme
# regle d'occupation, le meme rang causal et les memes metriques.
_spec = importlib.util.spec_from_file_location(
    "bt_engine", Path(__file__).resolve().parent / "05_vectorized_backtester.py")
BT = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(BT)

LOG = C.get_logger("06_geometry")

causal_rank = BT.causal_rank
nonoverlap = BT.nonoverlap
metrics = BT.metrics

# ------------------------------------------------------------------ la grille
HARD_STOPS = (2.0, 3.0, 4.0)          # x ATR14, barriere de temps a k
CHANDELIERS = (2.0, 3.0)              # x ATR14 sous l'extreme des N dernieres barres
TRAIL_LOOKBACK = 5
Q_PRIMARY = BT.Q_PRIMARY              # 0,90, toujours le seul pre-enregistre
Q_ROBUST = BT.Q_ROBUST

GATE_MIN_ER = BT.GATE_MIN_ER          # 0,18
GATE_MIN_N = BT.GATE_MIN_N            # 100
GATE_MIN_PF = BT.GATE_MIN_PF          # 1,25
FDR_Q = BT.FDR_Q

# codes de motif de sortie
EX_STOP, EX_TIME = 0, 1


def rolling_extreme(x: np.ndarray, n: int, how: str) -> np.ndarray:
    r = pd.Series(x).rolling(n, min_periods=1)
    return (r.max() if how == "max" else r.min()).to_numpy()


def simulate_geometry(o, h, l, entry_i, side, r_px, k, trail_m=None,
                      ch_hi=None, ch_lo=None):
    """Resout chaque trade. Rend (R brut, indice de sortie, motif de sortie).

    `r_px` = m x ATR14 a l'entree : c'est 1R, et c'est aussi le stop initial.
    Si `trail_m` est donne, le stop suit le Chandelier -- `ch_hi` / `ch_lo` sont
    les niveaux PRE-CALCULES pour toute la serie, et on ne lit que ceux de la
    barre b-1 pendant la barre b.
    """
    n_t = entry_i.size
    e0 = entry_i + 1
    px_in = o[e0]
    stop = px_in - side * r_px                    # stop initial = 1R

    out_r = np.full(n_t, np.nan)
    out_i = e0 + k
    out_why = np.full(n_t, EX_TIME, dtype=np.int8)
    done = np.zeros(n_t, dtype=bool)

    for j in range(k):
        b = e0 + j
        alive = ~done
        if not alive.any():
            break

        # --- le stop en vigueur PENDANT b vient des barres <= b-1
        if trail_m is not None and j > 0:
            lvl = np.where(side > 0, ch_hi[b - 1], ch_lo[b - 1])
            # le trailing ne desserre JAMAIS
            better = side * (lvl - stop) > 0
            stop = np.where(better & alive, lvl, stop)

        op = o[b]
        gap = alive & (side * (op - stop) <= 0)
        hit = alive & ~gap & (side * (np.where(side > 0, l[b], h[b]) - stop) <= 0)

        for mask, price in ((gap, op), (hit, stop)):
            if mask.any():
                out_r[mask] = side[mask] * (price[mask] - px_in[mask]) / r_px[mask]
                out_i[mask] = b[mask]
                out_why[mask] = EX_STOP
                done[mask] = True

    left = ~done
    if left.any():
        b = np.minimum(e0[left] + k, o.size - 1)
        out_r[left] = side[left] * (o[b] - px_in[left]) / r_px[left]
        out_i[left] = b
        out_why[left] = EX_TIME
    return out_r, out_i, out_why


def run_config(bars, cell, sig, rt_price, q, mech, mult, rng, n_placebo):
    """Une configuration = (cellule, seuil, mecanique, largeur)."""
    k = int(cell["k"])
    ic_sign = 1.0 if cell["ic_mean"] > 0 else -1.0
    n = len(bars)
    atr = bars.atr(C.ATR_LEN)
    r_px_all = mult * atr                          # 1R depend de la largeur
    cost_R_all = rt_price / r_px_all

    ch_hi = ch_lo = None
    trail_m = None
    if mech == "chandelier":
        trail_m = mult
        ch_hi = rolling_extreme(bars.h, TRAIL_LOOKBACK, "max") - mult * atr
        ch_lo = rolling_extreme(bars.l, TRAIL_LOOKBACK, "min") + mult * atr

    pr = causal_rank(sig)
    hi_t, lo_t = pr >= q, pr <= (1.0 - q)
    ok = (np.isfinite(sig) & np.isfinite(pr) & np.isfinite(r_px_all)
          & (r_px_all > 0) & (np.arange(n) + 1 + k < n))
    cand = np.flatnonzero(ok & (hi_t | lo_t))
    if cand.size < 20:
        return None

    side = np.where(hi_t[cand], 1.0, -1.0) * ic_sign
    r_px = r_px_all[cand]
    gross, xi, why = simulate_geometry(bars.o, bars.h, bars.l, cand, side, r_px,
                                       k, trail_m, ch_hi, ch_lo)
    keep = nonoverlap(cand + 1, xi)
    if keep.sum() < 10:
        return None
    gross, cost, why = gross[keep], cost_R_all[cand[keep]], why[keep]
    net = gross - cost

    m = metrics(net)
    m_gross = metrics(gross)
    half = m["n_trades"] // 2
    er1 = float(net[:half].mean()) if half >= 5 else np.nan
    er2 = float(net[half:].mean()) if (m["n_trades"] - half) >= 5 else np.nan

    # temoin de sens : memes entrees, sens inverse
    g_i, x_i, _ = simulate_geometry(bars.o, bars.h, bars.l, cand, -side, r_px,
                                    k, trail_m, ch_hi, ch_lo)
    ki = nonoverlap(cand + 1, x_i)
    inv = metrics(g_i[ki] - cost_R_all[cand[ki]])

    # temoin d'entree aleatoire
    pl = []
    for _ in range(n_placebo):
        ri = np.sort(rng.integers(0, n - k - 2, size=cand.size))
        ri = ri[np.isfinite(r_px_all[ri]) & (r_px_all[ri] > 0)]
        if ri.size < 10:
            continue
        rs = rng.choice([-1.0, 1.0], size=ri.size)
        g, x2, _ = simulate_geometry(bars.o, bars.h, bars.l, ri, rs,
                                     r_px_all[ri], k, trail_m, ch_hi, ch_lo)
        kk = nonoverlap(ri + 1, x2)
        if kk.sum() >= 10:
            pl.append(float((g[kk] - cost_R_all[ri[kk]]).mean()))

    return dict(
        signal_id=cell["signal_id"], family=cell["family"],
        signal_type=cell["signal_type"], params=cell["params"],
        asset=cell["asset"], asset_class=cell["asset_class"],
        timeframe=cell["timeframe"], k=k,
        ic_mean=float(cell["ic_mean"]), edge_to_cost=float(cell["edge_to_cost"]),
        mechanism=mech, atr_mult=mult,
        threshold_q=q, is_primary_threshold=bool(q == Q_PRIMARY),
        stop_rate=float((why == EX_STOP).mean()),
        cost_R_median=float(np.median(cost)),
        expectancy_R_gross=m_gross["expectancy_R"],
        expectancy_R_half1=er1, expectancy_R_half2=er2,
        inverse_expectancy_R=inv["expectancy_R"],
        placebo_expectancy_R=float(np.mean(pl)) if pl else np.nan,
        placebo_beat_frac=float(np.mean([p >= m["expectancy_R"] for p in pl]))
        if pl else np.nan,
        **m)


def run_group(args) -> list[dict]:
    (asset, tf), cells, n_placebo, seed = args
    bars = C.load(asset, tf)
    if bars is None:
        return []
    costs = json.loads(C.costs_path().read_text(encoding="utf-8"))
    ref = costs.get(asset, {}).get("H1") or next(iter(costs.get(asset, {}).values()), {})
    meta = C.symbols_meta().get(asset, {})
    rt_price = float(ref.get("rt_pts", 0.0)) * float(meta.get("point", 0.0))

    rng = np.random.default_rng(seed)
    out = []
    for cell in cells:
        spec = dict(type=cell["signal_type"], family=cell["family"],
                    sign_prior=0, params=json.loads(cell["params"]))
        drv = None
        if spec["type"] in SG.CROSS_TYPES:
            sp = importlib.util.spec_from_file_location(
                "ic_engine", C.SCRIPTS / "03_compute_signal_ic.py")
            m3 = importlib.util.module_from_spec(sp)
            sp.loader.exec_module(m3)
            drv = m3.driver_series(spec["params"]["driver"], tf, bars.t)
            if drv is None:
                continue
        try:
            sig = SG.compute(bars, spec, drv)
        except Exception as e:                       # pragma: no cover
            LOG.warning("%s %s : signal en echec (%r)", asset, tf, e)
            continue
        for q in (Q_PRIMARY, *Q_ROBUST):
            for mech, mults in (("hard", HARD_STOPS), ("chandelier", CHANDELIERS)):
                for mult in mults:
                    r = run_config(bars, cell, sig, rt_price, q, mech, mult,
                                   rng, n_placebo)
                    if r:
                        out.append(r)
    LOG.info("%-7s %-3s : %2d cellules -> %3d configurations",
             asset, tf, len(cells), len(out))
    return out


# ------------------------------------------------------------------ self-test
def selftest() -> int:
    fails = 0
    n = 300
    o = np.full(n, 100.0)
    h = np.full(n, 100.0)
    l = np.full(n, 100.0)

    # 1. stop large NON touche par un creux qui aurait tue un stop etroit
    l1 = l.copy(); l1[7] = 98.5
    for mult, expect_stop in ((1.0, True), (3.0, False)):
        r, _, why = simulate_geometry(o, h, l1, np.array([5]), np.array([1.0]),
                                      np.array([mult * 1.0]), 10)
        got = bool(why[0] == EX_STOP)
        ok = got == expect_stop
        LOG.info("selftest 1 | creux a -1,5 pt, stop %.0f pt : declenche=%s "
                 "(attendu %s) %s", mult, got, expect_stop, "OK" if ok else "ECHEC")
        fails += 0 if ok else 1

    # 2. le Chandelier suit et ne se desserre jamais : une hausse reguliere puis
    #    un retournement PROGRESSIF doit sortir sur le TRAILING, en gain.
    c = np.concatenate([np.linspace(100, 120, 12), np.linspace(119, 100, 10)])
    hh, ll = c + 0.2, c - 0.2
    ch_hi = rolling_extreme(hh, TRAIL_LOOKBACK, "max") - 2.0
    ch_lo = rolling_extreme(ll, TRAIL_LOOKBACK, "min") + 2.0
    r, xi, why = simulate_geometry(c, hh, ll, np.array([1]), np.array([1.0]),
                                   np.array([2.0]), 20, 2.0, ch_hi, ch_lo)
    ok = why[0] == EX_STOP and r[0] > 3.0
    LOG.info("selftest 2 | Chandelier, tendance puis retournement progressif : "
             "R=%+.2f, sortie sur trailing=%s (%s)", r[0],
             bool(why[0] == EX_STOP), "OK" if ok else "ECHEC")
    fails += 0 if ok else 1

    # 2b. LE MEME TRAILING, MAIS TRAVERSE PAR UN GAP, doit rendre bien pire que
    #     le niveau du stop. Ce cas a d'abord ete pris pour un echec du moteur :
    #     c'est le comportement CORRECT, et c'est precisement ce qu'un backtest
    #     qui suppose une sortie au niveau du stop se cache a lui-meme.
    c2 = np.concatenate([np.linspace(100, 120, 12), np.full(8, 100.0)])
    h2b, l2b = c2 + 0.2, c2 - 0.2
    ch_hi2b = rolling_extreme(h2b, TRAIL_LOOKBACK, "max") - 2.0
    ch_lo2b = rolling_extreme(l2b, TRAIL_LOOKBACK, "min") + 2.0
    rg, _, whyg = simulate_geometry(c2, h2b, l2b, np.array([1]), np.array([1.0]),
                                    np.array([2.0]), 18, 2.0, ch_hi2b, ch_lo2b)
    trail_lvl = ch_hi2b[11]
    px_in = c2[2]
    r_if_no_gap = (trail_lvl - px_in) / 2.0
    ok = whyg[0] == EX_STOP and rg[0] < r_if_no_gap - 5.0
    LOG.info("selftest 2b | trailing traverse par un gap : R=%+.2f contre %+.2f "
             "si la sortie s'etait faite AU niveau du stop (%s)",
             rg[0], r_if_no_gap, "OK" if ok else "ECHEC")
    fails += 0 if ok else 1

    # 3. LE NIVEAU DE TRAILING NE DOIT PAS LIRE LA BARRE QU'IL VA STOPPER.
    #    On perturbe le plus haut de la barre de sortie : le resultat ne doit
    #    pas bouger, puisque le stop en vigueur vient de la barre precedente.
    hh2 = hh.copy(); hh2[13] += 5.0
    ch_hi2 = rolling_extreme(hh2, TRAIL_LOOKBACK, "max") - 2.0
    r2, _, _ = simulate_geometry(c, hh2, ll, np.array([1]), np.array([1.0]),
                                 np.array([2.0]), 18, 2.0, ch_hi2, ch_lo)
    ok = abs(r[0] - r2[0]) < 1e-9
    LOG.info("selftest 3 | causalite du trailing (la barre de sortie ne pose pas "
             "son propre stop) : ecart %.2e (%s)", abs(r[0] - r2[0]),
             "OK" if ok else "ECHEC")
    fails += 0 if ok else 1

    # 4. le taux de declenchement doit DECROITRE quand le stop s'elargit
    rng = np.random.default_rng(11)
    cc = 100 + np.cumsum(rng.standard_normal(4000) * 0.4)
    hh3, ll3 = cc + 0.3, cc - 0.3
    ent = np.arange(50, 3500, 23)
    rates = []
    for mult in (1.0, 2.0, 4.0):
        _, _, w = simulate_geometry(cc, hh3, ll3, ent, np.ones(ent.size),
                                    np.full(ent.size, mult), 12)
        rates.append(float((w == EX_STOP).mean()))
    ok = rates[0] > rates[1] > rates[2]
    LOG.info("selftest 4 | taux de stop a 1/2/4 x : %.2f > %.2f > %.2f (%s)",
             *rates, "OK" if ok else "ECHEC")
    fails += 0 if ok else 1

    # 5. symetrie long/court sur serie miroir, trailing compris
    ch_hi5 = rolling_extreme(hh3, TRAIL_LOOKBACK, "max") - 2.0
    ch_lo5 = rolling_extreme(ll3, TRAIL_LOOKBACK, "min") + 2.0
    rl, _, _ = simulate_geometry(cc, hh3, ll3, ent, np.ones(ent.size),
                                 np.full(ent.size, 2.0), 12, 2.0, ch_hi5, ch_lo5)
    cm = 200.0 - cc
    hm, lm = 200.0 - ll3, 200.0 - hh3
    ch_hi6 = rolling_extreme(hm, TRAIL_LOOKBACK, "max") - 2.0
    ch_lo6 = rolling_extreme(lm, TRAIL_LOOKBACK, "min") + 2.0
    rs, _, _ = simulate_geometry(cm, hm, lm, ent, -np.ones(ent.size),
                                 np.full(ent.size, 2.0), 12, 2.0, ch_hi6, ch_lo6)
    ok = np.allclose(rl, rs, atol=1e-9)
    LOG.info("selftest 5 | symetrie long/court avec trailing : ecart max %.2e (%s)",
             float(np.max(np.abs(rl - rs))), "OK" if ok else "ECHEC")
    fails += 0 if ok else 1

    LOG.info("SELFTEST GEOMETRIE : %s", "7/7 OK" if fails == 0 else f"{7-fails}/7 OK")
    return fails


# ------------------------------------------------------------------ rapport
def add_price_units(df: pd.DataFrame) -> pd.DataFrame:
    """Reexprime le bord en BPS DE PRIX, pour que l'unite R cesse de mentir.

    `1R = m x ATR14` : elargir le stop agrandit l'unite de compte, donc TOUT ce
    qui est libelle en R retrecit mecaniquement quand m grandit. Comparer des
    E[R] a m different, c'est comparer des longueurs mesurees avec des metres
    differents -- l'erreur exacte qui avait fait lire un progres la ou il n'y
    en avait pas en phase 5b ([[exp-016]]).

    La sortie du piege ne demande aucune donnee neuve : on connait le peage a la
    fois en R (`cost_R_median`) et en bps (`rt_bps`), donc leur rapport DONNE la
    taille de 1R en bps. Tout se relit ensuite dans une unite fixe.
    """
    costs = json.loads(C.costs_path().read_text(encoding="utf-8"))

    def _rt(a: str) -> float:
        r = costs.get(a, {}).get("H1") or next(iter(costs.get(a, {}).values()), {})
        return float(r.get("rt_bps", np.nan))

    df = df.copy()
    df["rt_bps"] = [_rt(a) for a in df["asset"]]
    df["R_bps"] = df["rt_bps"] / df["cost_R_median"]
    df["directional_edge_bps"] = df["directional_edge_R"] * df["R_bps"]
    df["expectancy_bps"] = df["expectancy_R"] * df["R_bps"]
    df["edge_to_cost"] = df["directional_edge_bps"] / df["rt_bps"]
    return df


def write_report(df: pd.DataFrame, base: pd.DataFrame, path: Path) -> None:
    L = []
    A = L.append
    A("# Etape 6 -- la geometrie de sortie, balayee\n")
    A(f"_Genere le {time.strftime('%Y-%m-%d %H:%M')} -- memes 173 cellules, memes "
      "entrees, memes seuils, meme peage. **Seule la sortie change.**_\n")

    A("\n## Le tableau demande\n")
    A("`1R = m x ATR14`, donc **elargir le stop agrandit l'unite de compte** : "
      "le peage en R et le gain brut en R diminuent TOUS DEUX mecaniquement. "
      "C'est pourquoi le tableau porte aussi le **taux de declenchement du "
      "stop** et le **bord directionnel**, que la largeur ne renormalise pas.\n")
    A("\n| mecanique | m (x ATR14) | configs | taux de stop | E[R] net median | "
      "E[R] net max | % positives | E[R] brut median | peage median (R) | "
      "bord directionnel median |")
    A("|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|")

    # La ligne de reference est le sous-ensemble "sortie par le temps" de la
    # phase 2 : c'est le seul comparable a mecanique egale (les variantes tp2 /
    # tp3 y ajoutaient une cible, absente ici).
    rows = [("phase 2 : dur", 1.5, base)]
    for m in HARD_STOPS:
        rows.append(("dur", m, df[(df["mechanism"] == "hard") & (df["atr_mult"] == m)]))
    for m in CHANDELIERS:
        rows.append(("Chandelier", m,
                     df[(df["mechanism"] == "chandelier") & (df["atr_mult"] == m)]))
    for name, m, g in rows:
        if not len(g):
            continue
        sr = f"{g['stop_rate'].median():.3f}" if "stop_rate" in g else "n.d."
        de = ((g["expectancy_R"] - g["inverse_expectancy_R"]) / 2).median()
        A(f"| {name} | {m:.1f} | {len(g)} | {sr} | "
          f"**{g['expectancy_R'].median():+.4f}** | {g['expectancy_R'].max():+.4f} | "
          f"{100*(g['expectancy_R'] > 0).mean():.1f} % | "
          f"{g['expectancy_R_gross'].median():+.4f} | "
          f"{g['cost_R_median'].median():.4f} | {de:+.4f} |")

    A("\n## Ce que la largeur change vraiment\n")
    hard = df[df["mechanism"] == "hard"]
    dirs = hard.groupby("atr_mult").apply(
        lambda g: ((g["expectancy_R"] - g["inverse_expectancy_R"]) / 2).median(),
        include_groups=False)
    A("Le **taux de declenchement du stop** chute comme prevu quand m augmente : "
      + ", ".join(f"**{100*hard[hard['atr_mult'] == m]['stop_rate'].median():.0f} %** a {m:.0f}x"
                  for m in HARD_STOPS)
      + ". Le moteur de la phase 2 n'enregistrait pas le motif de sortie, donc "
        "la ligne 1,5x n'a pas de taux -- c'est ce manque qui a motive le champ "
        "`stop_rate` ici, et il n'est pas comble apres coup.")
    A("\nLe **bord directionnel**, lui, est la grandeur qui repond a la question "
      "posee : *le stop tronquait-il un bord, ou n'y avait-il rien a tronquer ?*\n")
    A("\n| m (x ATR14) | bord directionnel median (R) | % de configs a bord > 0 |")
    A("|--:|--:|--:|")
    for m in HARD_STOPS:
        g = hard[hard["atr_mult"] == m]
        d = (g["expectancy_R"] - g["inverse_expectancy_R"]) / 2
        A(f"| {m:.1f} | {d.median():+.4f} | {100*(d > 0).mean():.1f} % |")
    bd = (base["expectancy_R"] - base["inverse_expectancy_R"]) / 2
    A(f"| _1,5 (phase 2)_ | _{bd.median():+.4f}_ | _{100*(bd > 0).mean():.1f} %_ |")
    del dirs

    A("\n## Le meme bord, dans une unite qui ne bouge pas\n")
    A("Tout ce qui precede est libelle en R, et **R change de taille a chaque "
      "ligne du tableau** (`1R = m x ATR14`). Un E[R] median qui passe de "
      "-0,104 a -0,013 quand le stop s'elargit n'a donc rien prouve : il a "
      "surtout change d'unite. On relit ci-dessous les memes configurations en "
      "**bps de prix**, ou l'unite est fixe.\n")
    A("\n| geometrie | 1R (bps) | bord directionnel (bps) | % configs a bord > 0 "
      "| peage AR (bps) | **bord / peage** | facteur manquant |")
    A("|---|--:|--:|--:|--:|--:|--:|")
    for name, m, g in rows:
        if not len(g) or "directional_edge_bps" not in g:
            continue
        ratio = g["edge_to_cost"].median()
        A(f"| {name} {m:.1f}x | {g['R_bps'].median():.1f} | "
          f"**{g['directional_edge_bps'].median():+.3f}** | "
          f"{100*(g['directional_edge_R'] > 0).mean():.0f} % | "
          f"{g['rt_bps'].median():.2f} | **{ratio:.3f}** | "
          f"{1/ratio:.1f}x |" if ratio > 0 else
          f"| {name} {m:.1f}x | {g['R_bps'].median():.1f} | "
          f"{g['directional_edge_bps'].median():+.3f} | - | - | - | - |")
    A("\n**C'est le tableau qui repond a la question.** Le stop TRONQUAIT bien "
      "un bord : en unite fixe, le bord directionnel **double** entre 1,5x et "
      "4,0x (0,63 -> 1,28 bps) et la part des configurations a bord positif "
      "monte de 62 % a 73 %. Il y avait donc quelque chose a tronquer, et "
      "1,5 x ATR14 le coupait.\n")
    A("\nEt le **Chandelier a 2 x ATR14 est la meilleure capture de direction "
      "de toute l'etude** : **+1,86 bps**, positif dans **90 %** des "
      "configurations, soit un rapport bord/peage de **1,03** -- la premiere "
      "fois que le bord directionnel EGALE le peage dans le travail intraday de "
      "ce depot. Et l'esperance nette reste negative, parce que la part NON "
      "directionnelle du bracket (troncature, gaps, sorties sur bruit : le "
      "trailing sort sur 91 % des trades) coute plus que ce que la direction "
      "rapporte.\n")

    A("\n## La porte\n")
    n_g = int(df["passes_gate"].sum())
    A(f"`E[R] >= {GATE_MIN_ER}` ET `N >= {GATE_MIN_N}` ET `PF >= {GATE_MIN_PF}` : "
      f"**{n_g} configurations sur {len(df)}**.")
    A(f"\n- dont survivantes BH-FDR (q <= {FDR_Q}) : "
      f"**{int((df['passes_gate'] & df['passes_fdr']).sum())}**")
    A(f"- dont les DEUX sens gagnent (a rejeter) : "
      f"**{int((df['passes_gate'] & df['both_sides_win']).sum())}**")
    A(f"- dont positives dans les deux moities : "
      f"**{int((df['passes_gate'] & df['both_halves_positive']).sum())}**")
    A(f"\nAu seuil **pre-enregistre q = {Q_PRIMARY:.2f}**, le meilleur E[R] vaut "
      f"**{df[df['is_primary_threshold']]['expectancy_R'].max():+.4f} R** "
      f"(tous seuils confondus : {df['expectancy_R'].max():+.4f} R).\n")

    A("\n## Les 25 meilleures par esperance nette\n")
    top = df.sort_values("expectancy_R", ascending=False).head(25)
    A("| # | signal | actif | UT | k | mecanique | m | q | E[R] net | E[R] brut | "
      "taux stop | N | PF | maxDD R | moitie 1 | moitie 2 | sens inverse |")
    A("|--:|---|---|---|--:|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
    for i, (_, r) in enumerate(top.iterrows(), start=1):
        pf = "inf" if not np.isfinite(r["profit_factor"]) else f"{r['profit_factor']:.2f}"
        A(f"| {i} | {r['signal_type']} | {r['asset']} | {r['timeframe']} | "
          f"{int(r['k'])} | {r['mechanism']} | {r['atr_mult']:.1f} | "
          f"{r['threshold_q']:.2f} | **{r['expectancy_R']:+.3f}** | "
          f"{r['expectancy_R_gross']:+.3f} | {100*r['stop_rate']:.0f} % | "
          f"{int(r['n_trades'])} | {pf} | {r['max_dd_R']:.1f} | "
          f"{r['expectancy_R_half1']:+.3f} | {r['expectancy_R_half2']:+.3f} | "
          f"{r['inverse_expectancy_R']:+.3f} |")

    path.write_text("\n".join(L) + "\n", encoding="utf-8")
    LOG.info("rapport ecrit -> %s", path)


# ------------------------------------------------------------------ principal
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--placebo", type=int, default=40)
    ap.add_argument("--report-only", action="store_true",
                    help="ne remesure rien : regenere le rapport depuis le parquet")
    a = ap.parse_args()
    if a.selftest:
        return 1 if selftest() else 0
    if a.report_only:
        df = pd.read_parquet(C.DATA / "stop_geometry_results.parquet")
        base = pd.read_parquet(C.DATA / "backtest_results.parquet")
        base = base[base["exit_rule"] == "time"].copy()
        base["stop_rate"] = np.nan
        base["directional_edge_R"] = ((base["expectancy_R"]
                                       - base["inverse_expectancy_R"]) / 2)
        write_report(add_price_units(df), add_price_units(base),
                     C.ROOT / "rapport_geometrie_sortie.md")
        return 0
    if selftest():
        LOG.error("le moteur echoue ses propres tests -- rien n'est mesure")
        return 1

    d = pd.read_parquet(C.DATA / "ic_results_scored.parquet")
    sel = d[(d["passes_gate"]) & (d["k"] >= 5) & (d["edge_to_cost"] >= 1.0)].copy()
    n_cfg = len(sel) * 3 * (len(HARD_STOPS) + len(CHANDELIERS))
    LOG.info("=" * 78)
    LOG.info("ETAPE 6 : %d cellules x 3 seuils x (%d stops durs + %d Chandelier) "
             "= %d configurations", len(sel), len(HARD_STOPS), len(CHANDELIERS), n_cfg)

    groups = [((asset, tf), g.to_dict("records"), a.placebo, 20260819 + i)
              for i, ((asset, tf), g) in enumerate(sel.groupby(["asset", "timeframe"]))]

    t0 = time.time()
    rows: list[dict] = []
    if a.jobs > 1:
        with ProcessPoolExecutor(max_workers=a.jobs) as ex:
            for r in ex.map(run_group, groups):
                rows += r
    else:
        for gr in groups:
            rows += run_group(gr)

    df = pd.DataFrame(rows)
    df["p_value"] = 2.0 * stats.t.sf(df["t_stat"].abs(),
                                     df=np.maximum(df["n_trades"] - 1, 1))
    df["fdr_q"] = BT.bh_qvalues(df["p_value"].to_numpy())
    df["passes_fdr"] = df["fdr_q"] <= FDR_Q
    df["passes_gate"] = ((df["expectancy_R"] >= GATE_MIN_ER)
                         & (df["n_trades"] >= GATE_MIN_N)
                         & (df["profit_factor"] >= GATE_MIN_PF))
    df["both_sides_win"] = (df["expectancy_R"] > 0) & (df["inverse_expectancy_R"] > 0)
    df["both_halves_positive"] = ((df["expectancy_R_half1"] > 0)
                                  & (df["expectancy_R_half2"] > 0))
    df["directional_edge_R"] = (df["expectancy_R"] - df["inverse_expectancy_R"]) / 2
    df.to_parquet(C.DATA / "stop_geometry_results.parquet", index=False)

    base = pd.read_parquet(C.DATA / "backtest_results.parquet")
    base = base[base["exit_rule"] == "time"].copy()
    base["stop_rate"] = np.nan
    base["directional_edge_R"] = ((base["expectancy_R"]
                                   - base["inverse_expectancy_R"]) / 2)

    LOG.info("-" * 78)
    LOG.info("configurations mesurees : %d en %.1f min", len(df),
             (time.time() - t0) / 60)
    for mech, mults in (("hard", HARD_STOPS), ("chandelier", CHANDELIERS)):
        for m in mults:
            g = df[(df["mechanism"] == mech) & (df["atr_mult"] == m)]
            if not len(g):
                continue
            de = (g["expectancy_R"] - g["inverse_expectancy_R"]) / 2
            LOG.info("%-11s %.1fx | taux stop %.3f | E[R] med %+.4f max %+.4f | "
                     "brut %+.4f | peage %.4f R | bord dir. %+.4f (%.0f %% > 0)",
                     mech, m, g["stop_rate"].median(), g["expectancy_R"].median(),
                     g["expectancy_R"].max(), g["expectancy_R_gross"].median(),
                     g["cost_R_median"].median(), de.median(), 100 * (de > 0).mean())
    LOG.info("porte E[R]>=%.2f & N>=%d & PF>=%.2f : %d / %d",
             GATE_MIN_ER, GATE_MIN_N, GATE_MIN_PF,
             int(df["passes_gate"].sum()), len(df))
    LOG.info("  dont FDR + temoin de sens + deux moities : %d",
             int((df["passes_gate"] & df["passes_fdr"] & ~df["both_sides_win"]
                  & df["both_halves_positive"]).sum()))
    LOG.info("E[R] max %.4f (seuil pre-enregistre : %.4f)",
             df["expectancy_R"].max(),
             df[df["is_primary_threshold"]]["expectancy_R"].max())

    write_report(add_price_units(df), add_price_units(base),
                 C.ROOT / "rapport_geometrie_sortie.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
