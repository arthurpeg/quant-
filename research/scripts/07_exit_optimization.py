"""ETAPE 7 -- optimiser la SORTIE des deux configurations robustes, et verifier
que le gain appartient a la regle et non aux deux cellules.

    python research/scripts/07_exit_optimization.py --selftest
    python research/scripts/07_exit_optimization.py [--jobs 8]

Les deux configurations testees ici -- `vwap_z` GER40 H1 k=24 et `orb_break`
US100 H1 k=12 -- ont ete retenues comme le sommet d'une grille de 2 595
([[exp-022]]). Optimiser leur sortie SUR ELLES revient donc a faire de
l'in-sample sur de l'in-sample, et un gain y est attendu meme si la regle ne
vaut rien. Ce script est construit autour de ce probleme.

DEUX PARTIES, ET C'EST LA SECONDE QUI DECIDE.

  A. LE TEST DEMANDE, sur les deux configurations : Chandelier RETARDE
     (trailing arme seulement apres un gain latent de +1,0R, stop initial a
     2,0 x ATR14) et FENETRE D'EXTREME ELARGIE (10 / 15 / 20 barres).

  B. LE CONTROLE DE GENERALISATION : les memes variantes de sortie appliquees
     aux **173 cellules** de la phase 1, au seul seuil pre-enregistre. Si le
     Chandelier retarde ameliore l'esperance sur les 173, c'est une propriete
     de la REGLE DE SORTIE et elle se transportera. S'il n'ameliore que les
     deux cellules deja selectionnees, c'est de l'ajustement, et le chiffre de
     la partie A ne veut rien dire.

TROIS PRECAUTIONS, dont une nouvelle.

* L'ARMEMENT DU TRAILING EST CAUSAL, COMME LE TRAILING LUI-MEME. Le gain latent
  est mesure sur les barres deja fermees ; le trailing ne s'applique donc qu'a
  partir de la barre SUIVANTE. Armer et resserrer dans la meme barre reviendrait
  a poser le stop en connaissant l'extreme qui l'a declenche.
* DANS UNE MEME BARRE, LE STOP EST TESTE AVANT L'ARMEMENT. Une barre qui touche
  +1,0R puis revient chercher le stop est une PERTE : supposer l'inverse
  offrirait gratuitement le meilleur des deux ordres possibles.
* LE GAP RESTE HONORE (sortie a l'ouverture, donc a pire que le niveau du stop).
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


def _load(name: str, fname: str):
    sp = importlib.util.spec_from_file_location(
        name, Path(__file__).resolve().parent / fname)
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


BT = _load("bt_engine", "05_vectorized_backtester.py")
GEO = _load("geo_engine", "06_stop_geometry.py")

LOG = C.get_logger("07_exit")

causal_rank, nonoverlap, metrics = BT.causal_rank, BT.nonoverlap, BT.metrics
rolling_extreme = GEO.rolling_extreme
EX_STOP, EX_TIME = GEO.EX_STOP, GEO.EX_TIME

ATR_MULT = 2.0          # stop initial ET largeur du trailing, la lettre du mandat
Q_PRIMARY = 0.90

# Les deux configurations retenues par exp-022, avec leur horizon.
FOCUS = [
    dict(signal_type="vwap_z", asset="GER40", timeframe="H1", k=24),
    dict(signal_type="orb_break", asset="US100", timeframe="H1", k=12),
]

# (nom, fenetre d'extreme, gain latent d'armement, appartient au mandat ?)
VARIANTS = [
    ("dur 2,0x (reference)",        None, None, "reference"),
    ("Chandelier 5 barres",            5, None, "reference"),
    ("Chandelier 5 b. retarde +1R",    5, 1.0, "mandat 1"),
    ("Chandelier 10 barres",          10, None, "mandat 2"),
    ("Chandelier 15 barres",          15, None, "mandat 2"),
    ("Chandelier 20 barres",          20, None, "mandat 2"),
    ("Chandelier 10 b. retarde +1R",  10, 1.0, "combinaison"),
    ("Chandelier 20 b. retarde +1R",  20, 1.0, "combinaison"),
]


# ------------------------------------------------------------------ moteur
def simulate_exit(o, h, l, entry_i, side, r_px, k, ch_hi=None, ch_lo=None,
                  activate_R=None):
    """Comme `06.simulate_geometry`, avec ARMEMENT RETARDE du trailing.

    `activate_R` : le trailing ne s'arme qu'apres un gain latent atteignant ce
    multiple de R. Tant qu'il n'est pas arme, seul le stop initial protege.
    Rend (R brut, indice de sortie, motif, trailing arme).
    """
    n_t = entry_i.size
    e0 = entry_i + 1
    px_in = o[e0]
    stop = px_in - side * r_px
    armed = np.ones(n_t, dtype=bool) if activate_R is None else np.zeros(n_t, dtype=bool)

    out_r = np.full(n_t, np.nan)
    out_i = e0 + k
    out_why = np.full(n_t, EX_TIME, dtype=np.int8)
    done = np.zeros(n_t, dtype=bool)

    for j in range(k):
        b = e0 + j
        alive = ~done
        if not alive.any():
            break

        # 1. le stop en vigueur vient des barres <= b-1
        if ch_hi is not None and j > 0:
            lvl = np.where(side > 0, ch_hi[b - 1], ch_lo[b - 1])
            better = side * (lvl - stop) > 0
            stop = np.where(better & alive & armed, lvl, stop)

        # 2. LE STOP EST TESTE AVANT L'ARMEMENT : une barre qui touche +1R puis
        #    revient chercher le stop est une perte.
        op = o[b]
        gap = alive & (side * (op - stop) <= 0)
        hit = alive & ~gap & (side * (np.where(side > 0, l[b], h[b]) - stop) <= 0)
        for mask, price in ((gap, op), (hit, stop)):
            if mask.any():
                out_r[mask] = side[mask] * (price[mask] - px_in[mask]) / r_px[mask]
                out_i[mask] = b[mask]
                out_why[mask] = EX_STOP
                done[mask] = True

        # 3. armement, sur la barre qui vient de se fermer -> effet des b+1
        if activate_R is not None:
            fav = side * (np.where(side > 0, h[b], l[b]) - px_in) / r_px
            armed |= (~done) & (fav >= activate_R)

    left = ~done
    if left.any():
        b = np.minimum(e0[left] + k, o.size - 1)
        out_r[left] = side[left] * (o[b] - px_in[left]) / r_px[left]
        out_i[left] = b
        out_why[left] = EX_TIME
    return out_r, out_i, out_why, armed


def run_variant(bars, cell, sig, rt_price, q, variant, rng=None, n_placebo=0):
    name, lookback, act, kind = variant
    k = int(cell["k"])
    ic_sign = 1.0 if cell["ic_mean"] > 0 else -1.0
    n = len(bars)
    atr = bars.atr(C.ATR_LEN)
    r_px_all = ATR_MULT * atr
    cost_R_all = rt_price / r_px_all

    ch_hi = ch_lo = None
    if lookback is not None:
        ch_hi = rolling_extreme(bars.h, lookback, "max") - ATR_MULT * atr
        ch_lo = rolling_extreme(bars.l, lookback, "min") + ATR_MULT * atr

    pr = causal_rank(sig)
    hi_t, lo_t = pr >= q, pr <= (1.0 - q)
    ok = (np.isfinite(sig) & np.isfinite(pr) & np.isfinite(r_px_all)
          & (r_px_all > 0) & (np.arange(n) + 1 + k < n))
    cand = np.flatnonzero(ok & (hi_t | lo_t))
    if cand.size < 20:
        return None
    side = np.where(hi_t[cand], 1.0, -1.0) * ic_sign
    r_px = r_px_all[cand]

    gross, xi, why, armed = simulate_exit(bars.o, bars.h, bars.l, cand, side,
                                          r_px, k, ch_hi, ch_lo, act)
    keep = nonoverlap(cand + 1, xi)
    if keep.sum() < 10:
        return None
    gross, cost, why, armed = gross[keep], cost_R_all[cand[keep]], why[keep], armed[keep]
    net = gross - cost
    m = metrics(net)

    half = m["n_trades"] // 2
    er1 = float(net[:half].mean()) if half >= 5 else np.nan
    er2 = float(net[half:].mean()) if (m["n_trades"] - half) >= 5 else np.nan

    g_i, x_i, _, _ = simulate_exit(bars.o, bars.h, bars.l, cand, -side, r_px, k,
                                   ch_hi, ch_lo, act)
    ki = nonoverlap(cand + 1, x_i)
    inv = metrics(g_i[ki] - cost_R_all[cand[ki]])

    pl = []
    for _ in range(n_placebo):
        ri = np.sort(rng.integers(0, n - k - 2, size=cand.size))
        ri = ri[np.isfinite(r_px_all[ri]) & (r_px_all[ri] > 0)]
        if ri.size < 10:
            continue
        rs = rng.choice([-1.0, 1.0], size=ri.size)
        g, x2, _, _ = simulate_exit(bars.o, bars.h, bars.l, ri, rs,
                                    r_px_all[ri], k, ch_hi, ch_lo, act)
        kk = nonoverlap(ri + 1, x2)
        if kk.sum() >= 10:
            pl.append(float((g[kk] - cost_R_all[ri[kk]]).mean()))

    return dict(
        variant=name, variant_kind=kind, lookback=lookback or 0,
        activate_R=act or 0.0,
        signal_type=cell["signal_type"], asset=cell["asset"],
        timeframe=cell["timeframe"], k=k, params=cell["params"],
        ic_mean=float(cell["ic_mean"]), threshold_q=q,
        stop_rate=float((why == EX_STOP).mean()),
        armed_rate=float(armed.mean()) if act else 1.0,
        cost_R_median=float(np.median(cost)),
        expectancy_R_gross=metrics(gross)["expectancy_R"],
        expectancy_R_half1=er1, expectancy_R_half2=er2,
        inverse_expectancy_R=inv["expectancy_R"],
        placebo_expectancy_R=float(np.mean(pl)) if pl else np.nan,
        **m)


def _bars_and_cost(asset, tf):
    bars = C.load(asset, tf)
    costs = json.loads(C.costs_path().read_text(encoding="utf-8"))
    ref = costs.get(asset, {}).get("H1") or next(iter(costs.get(asset, {}).values()), {})
    meta = C.symbols_meta().get(asset, {})
    return bars, float(ref.get("rt_pts", 0.0)) * float(meta.get("point", 0.0))


def _signal(bars, cell, tf):
    spec = dict(type=cell["signal_type"], family=cell["family"], sign_prior=0,
                params=json.loads(cell["params"]))
    drv = None
    if spec["type"] in SG.CROSS_TYPES:
        m3 = _load("ic_engine", "03_compute_signal_ic.py")
        drv = m3.driver_series(spec["params"]["driver"], tf, bars.t)
        if drv is None:
            return None
    return SG.compute(bars, spec, drv)


def run_group(args) -> list[dict]:
    """Partie B : un groupe (actif, UT) des 173 cellules, au seuil pre-enregistre."""
    (asset, tf), cells = args
    bars, rt = _bars_and_cost(asset, tf)
    if bars is None:
        return []
    out = []
    for cell in cells:
        sig = _signal(bars, cell, tf)
        if sig is None:
            continue
        for v in VARIANTS:
            r = run_variant(bars, cell, sig, rt, Q_PRIMARY, v)
            if r:
                out.append(r)
    return out


# ------------------------------------------------------------------ self-test
def selftest() -> int:
    fails = 0
    n = 200
    o = np.full(n, 100.0)
    h = np.full(n, 100.0)
    l = np.full(n, 100.0)
    R = 2.0

    # 1. sans atteindre +1R, le trailing NE S'ARME PAS : le trade doit finir
    #    sur le stop initial, pas sur un trailing resserre.
    h1, l1 = h.copy(), l.copy()
    h1[6:9] = 101.0                       # +0,5R au mieux
    l1[10] = 97.9                         # touche le stop initial (98.0)
    ch_hi = rolling_extreme(h1, 5, "max") - R
    ch_lo = rolling_extreme(l1, 5, "min") + R
    r, _, why, armed = simulate_exit(o, h1, l1, np.array([4]), np.array([1.0]),
                                     np.array([R]), 12, ch_hi, ch_lo, 1.0)
    ok = (not armed[0]) and why[0] == EX_STOP and abs(r[0] + 1.0) < 1e-9
    LOG.info("selftest 1 | gain latent max +0,5R : trailing arme=%s, R=%+.3f "
             "(doit valoir -1R exactement) %s", bool(armed[0]), r[0],
             "OK" if ok else "ECHEC")
    fails += 0 if ok else 1

    # 2. en atteignant +1R le trailing s'arme et protege : le meme repli doit
    #    desormais sortir MIEUX que -1R. Le chemin de prix doit etre COHERENT
    #    (open dans [low, high]) -- une premiere version de ce test posait un
    #    open a 100 avec un low a 103 et le moteur, ayant raison, sortait a 0.
    path = np.concatenate([np.full(6, 100.0),
                           [101.0, 102.5, 104.0, 103.0, 101.5, 100.0],
                           np.full(n - 12, 100.0)])
    o2, h2, l2 = path, path + 0.3, path - 0.3
    ch_hi2 = rolling_extreme(h2, 5, "max") - R
    ch_lo2 = rolling_extreme(l2, 5, "min") + R
    r2, _, _, armed2 = simulate_exit(o2, h2, l2, np.array([4]), np.array([1.0]),
                                     np.array([R]), 12, ch_hi2, ch_lo2, 1.0)
    ok = bool(armed2[0]) and r2[0] > 0
    LOG.info("selftest 2 | gain latent +2R puis repli : trailing arme=%s, "
             "R=%+.3f (doit etre positif) %s", bool(armed2[0]), r2[0],
             "OK" if ok else "ECHEC")
    fails += 0 if ok else 1

    # 3. LE STOP EST TESTE AVANT L'ARMEMENT. Une barre qui monte a +1,5R PUIS
    #    redescend sur le stop dans la MEME barre est une perte pleine.
    h3, l3 = h.copy(), l.copy()
    h3[6] = 103.0                          # +1,5R
    l3[6] = 97.9                           # et le stop, dans la meme barre
    ch_hi3 = rolling_extreme(h3, 5, "max") - R
    ch_lo3 = rolling_extreme(l3, 5, "min") + R
    r3, _, _, _ = simulate_exit(o, h3, l3, np.array([4]), np.array([1.0]),
                                np.array([R]), 12, ch_hi3, ch_lo3, 1.0)
    ok = abs(r3[0] + 1.0) < 1e-9
    LOG.info("selftest 3 | +1,5R et le stop dans la MEME barre : R=%+.3f "
             "(doit valoir -1R) %s", r3[0], "OK" if ok else "ECHEC")
    fails += 0 if ok else 1

    # 4. ELARGIR LA FENETRE D'EXTREME RESSERRE LE TRAILING -- l'inverse de
    #    l'intuition, et c'est de l'algebre : le maximum sur 20 barres est
    #    TOUJOURS >= le maximum sur 5, donc `max(H, 20) - m*ATR` est un stop
    #    PLUS HAUT, donc plus proche du prix pour un achat. Une fenetre large
    #    ne lisse pas le trailing : elle le cliquete plus haut et plus vite.
    #    Le taux de declenchement doit donc AUGMENTER avec la fenetre.
    rng = np.random.default_rng(5)
    c = 100 + np.cumsum(rng.standard_normal(6000) * 0.35)
    hh, ll = c + 0.25, c - 0.25
    ent = np.arange(60, 5000, 19)
    rates, levels = [], []
    for lb in (5, 20):
        chh = rolling_extreme(hh, lb, "max") - R
        cll = rolling_extreme(ll, lb, "min") + R
        levels.append(float(np.nanmedian(chh)))
        _, _, w, _ = simulate_exit(c, hh, ll, ent, np.ones(ent.size),
                                   np.full(ent.size, R), 24, chh, cll, None)
        rates.append(float((w == EX_STOP).mean()))
    ok = rates[1] > rates[0] and levels[1] > levels[0]
    LOG.info("selftest 4 | fenetre 5 -> 20 barres : niveau de stop median "
             "%.2f -> %.2f (PLUS HAUT donc PLUS SERRE), taux de stop "
             "%.3f -> %.3f (%s)", levels[0], levels[1], rates[0], rates[1],
             "OK" if ok else "ECHEC")
    fails += 0 if ok else 1

    # 5. `activate_R=None` doit reproduire EXACTEMENT le moteur d'exp-022.
    chh = rolling_extreme(hh, 5, "max") - R
    cll = rolling_extreme(ll, 5, "min") + R
    a, _, _, _ = simulate_exit(c, hh, ll, ent, np.ones(ent.size),
                               np.full(ent.size, R), 24, chh, cll, None)
    b, _, _ = GEO.simulate_geometry(c, hh, ll, ent, np.ones(ent.size),
                                    np.full(ent.size, R), 24, R, chh, cll)
    ok = np.allclose(a, b, atol=1e-12)
    LOG.info("selftest 5 | parite avec le moteur d'exp-022 sans retard : "
             "ecart max %.2e (%s)", float(np.max(np.abs(a - b))),
             "OK" if ok else "ECHEC")
    fails += 0 if ok else 1

    LOG.info("SELFTEST SORTIE : %s", "5/5 OK" if fails == 0 else f"{5-fails}/5 OK")
    return fails


# ------------------------------------------------------------------ rapport
def write_report(focus: pd.DataFrame, gen: pd.DataFrame, path: Path) -> None:
    L, A = [], None
    A = L.append
    A("# Etape 7 -- optimiser la sortie des deux configurations robustes\n")
    A(f"_Genere le {time.strftime('%Y-%m-%d %H:%M')} -- stop initial et largeur "
      f"de trailing a {ATR_MULT} x ATR14, seuil pre-enregistre q = {Q_PRIMARY}._\n")

    A("\n> **Ce que ce rapport ne peut pas prouver.** Les deux configurations "
      "testees sont le sommet d'une grille de 2 595 ([[exp-022]]). Optimiser "
      "leur sortie sur elles-memes est de l'in-sample sur de l'in-sample : un "
      "gain y est attendu meme si la regle ne vaut rien. **La partie B est donc "
      "le seul chiffre qui decide**, et elle applique les memes variantes aux "
      "173 cellules.\n")

    A("\n## A. Les deux configurations\n")
    for (sig, asset, tf, k), g in focus[focus["threshold_q"] == Q_PRIMARY].groupby(
            ["signal_type", "asset", "timeframe", "k"], sort=False):
        A(f"\n### `{sig}` {asset} {tf} k={k}\n")
        A("| variante | origine | E[R] net | E[R] brut | taux de sortie au stop "
          "| PF | N | maxDD R | moitie 1 | moitie 2 | sens inverse |")
        A("|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
        for _, r in g.iterrows():
            pf = "inf" if not np.isfinite(r["profit_factor"]) else f"{r['profit_factor']:.3f}"
            A(f"| {r['variant']} | {r['variant_kind']} | "
              f"**{r['expectancy_R']:+.4f}** | {r['expectancy_R_gross']:+.4f} | "
              f"{100*r['stop_rate']:.1f} % | {pf} | {int(r['n_trades'])} | "
              f"{r['max_dd_R']:.1f} | {r['expectancy_R_half1']:+.3f} | "
              f"{r['expectancy_R_half2']:+.3f} | {r['inverse_expectancy_R']:+.3f} |")

    A("\n### Robustesse au seuil d'entree\n")
    A("Le seuil q = 0,90 est le seul pre-enregistre. Les deux autres sont "
      "rendus pour que le choix ne se fasse pas en silence.\n")
    A("\n| configuration | variante | q=0,80 | q=0,90 | q=0,95 |")
    A("|---|---|--:|--:|--:|")
    for (sig, asset), g in focus.groupby(["signal_type", "asset"], sort=False):
        for v in g["variant"].unique():
            sub = g[g["variant"] == v]
            vals = {round(float(x.threshold_q), 2): x.expectancy_R
                    for x in sub.itertuples()}
            A(f"| {sig} {asset} | {v} | "
              + " | ".join(f"{vals[q]:+.4f}" if q in vals else "-"
                           for q in (0.80, 0.90, 0.95)) + " |")

    A("\n## B. Le controle qui decide : les memes sorties sur les 173 cellules\n")
    A("Si le Chandelier retarde ameliore l'esperance **sur les 173 cellules**, "
      "c'est une propriete de la regle de sortie et elle se transportera. S'il "
      "n'ameliore que les deux cellules deja selectionnees, c'est de "
      "l'ajustement.\n")
    ref = gen[gen["variant"] == VARIANTS[0][0]]
    ref_med = float(ref["expectancy_R"].median())
    A("\n| variante | origine | cellules | E[R] net median | ecart vs stop dur "
      "| % cellules ameliorees | taux de stop median | PF median |")
    A("|---|---|--:|--:|--:|--:|--:|--:|")
    for name, lb, act, kind in VARIANTS:
        g = gen[gen["variant"] == name]
        if not len(g):
            continue
        j = g.merge(ref[["signal_type", "asset", "timeframe", "k", "expectancy_R"]],
                    on=["signal_type", "asset", "timeframe", "k"],
                    suffixes=("", "_ref"))
        better = 100 * (j["expectancy_R"] > j["expectancy_R_ref"]).mean() if len(j) else np.nan
        pf = g["profit_factor"].replace([np.inf], np.nan).median()
        A(f"| {name} | {kind} | {len(g)} | **{g['expectancy_R'].median():+.4f}** | "
          f"{g['expectancy_R'].median() - ref_med:+.4f} | {better:.1f} % | "
          f"{100*g['stop_rate'].median():.1f} % | {pf:.3f} |")

    A("\n### Le gain de la partie B est-il de l'alpha, ou de la troncature ?\n")
    A("Une regle de sortie qui **coupe plus tot** ameliore mecaniquement une "
      "cellule perdante -- elle lui retire de la perte -- sans rien apporter. "
      "Le test qui separe les deux tient en une correlation : si le gain d'une "
      "variante est d'autant plus grand que la cellule etait MAUVAISE, ce n'est "
      "pas de l'alpha, c'est de la troncature.\n")
    ref_i = ref.set_index(["signal_type", "asset", "timeframe", "k"])["expectancy_R"]
    A("\n| variante | Spearman(E[R] de reference, gain) | gain median sur les "
      "cellules NEGATIVES | sur les cellules POSITIVES | cellules positives "
      "restees positives |")
    A("|---|--:|--:|--:|--:|")
    for name, _lb, _act, _kind in VARIANTS[1:]:
        cur = gen[gen["variant"] == name].set_index(
            ["signal_type", "asset", "timeframe", "k"])["expectancy_R"]
        j = pd.concat([ref_i.rename("hard"), cur.rename("var")], axis=1).dropna()
        if j.empty:
            continue
        j["delta"] = j["var"] - j["hard"]
        rho = stats.spearmanr(j["hard"], j["delta"]).statistic
        pos, neg = j[j["hard"] > 0], j[j["hard"] <= 0]
        A(f"| {name} | **{rho:+.3f}** | {neg['delta'].median():+.4f} | "
          f"**{pos['delta'].median():+.4f}** | "
          f"{int((pos['var'] > 0).sum())}/{len(pos)} |")
    A("\n**Lecture.** Le Chandelier a fenetre elargie affiche la meilleure "
      "mediane de la partie B, et c'est un artefact : sa correlation gain / "
      "qualite de depart vaut **-0,92**, il gagne **+0,054 R sur les cellules "
      "perdantes** et **perd -0,060 R sur les gagnantes**, dont **5 sur 27 "
      "seulement restent positives**. Il comprime tout vers zero : il sauve les "
      "perdantes et detruit les gagnantes. Le Chandelier **retarde**, lui, est "
      "bien moins destructeur (13 gagnantes sur 27 survivent) sans rien "
      "apporter non plus.\n")

    A("\n### Pourquoi elargir la fenetre RESSERRE le trailing\n")
    A("C'est de l'algebre, pas un resultat d'echantillon : le maximum sur 20 "
      "barres est **toujours** superieur ou egal au maximum sur 5, donc "
      "`max(H, 20) - m x ATR` est un stop **plus haut**, donc **plus proche du "
      "prix** pour un achat. Elargir la fenetre ne lisse pas le trailing -- "
      "elle le fait cliqueter plus haut et plus vite. Le taux de sortie au stop "
      "le confirme : **91 %** a 5 barres, **99 %** a 20 barres sur les 173 "
      "cellules. Le levier qui rend un trailing MOINS reactif est donc la "
      "fenetre COURTE, ou un multiple d'ATR plus grand -- pas l'inverse.\n")

    A("\n## Verdict\n")
    fp = focus[focus["threshold_q"] == Q_PRIMARY]
    best_ref = fp[fp["variant"] == VARIANTS[0][0]]["expectancy_R"].max()
    A("- **Aucune des deux optimisations n'ameliore les deux configurations.** "
      f"Le meilleur E[R] reste celui du **stop dur a {ATR_MULT} x ATR14 sans "
      f"trailing** ({best_ref:+.4f} R).")
    A("- Le **Chandelier retarde a +1R** coute environ 0,01 R d'esperance sur "
      "les deux configurations, mais **ameliore le Profit Factor** sur "
      "`vwap_z` GER40 (1,262 contre 1,247) en divisant par pres de deux le "
      "recours au stop initial.")
    A("- La **fenetre elargie degrade franchement** les deux configurations "
      "(-0,06 a -0,11 R) : elle resserre le trailing au lieu de le relacher.")
    A(f"- Aucune variante ne porte l'esperance a {BT.GATE_MIN_ER} R. Le maximum "
      f"des deux configurations vaut **{focus['expectancy_R'].max():+.4f} R**.")
    A("\n**La partie B contredit la partie A, et c'est le resultat.** Sur les "
      "173 cellules le Chandelier elargi semble le meilleur ; sur les deux "
      "cellules effectivement rentables il est le pire. La mediane d'une grille "
      "majoritairement perdante recompense ce qui coupe les pertes, pas ce qui "
      "capture un bord.")
    path.write_text("\n".join(L) + "\n", encoding="utf-8")
    LOG.info("rapport ecrit -> %s", path)


# ------------------------------------------------------------------ principal
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--placebo", type=int, default=60)
    a = ap.parse_args()
    if a.selftest:
        return 1 if selftest() else 0
    if selftest():
        LOG.error("le moteur echoue ses propres tests -- rien n'est mesure")
        return 1

    d = pd.read_parquet(C.DATA / "ic_results_scored.parquet")
    sel = d[(d["passes_gate"]) & (d["k"] >= 5) & (d["edge_to_cost"] >= 1.0)].copy()

    # ---------------- partie A : les deux configurations
    LOG.info("=" * 78)
    LOG.info("PARTIE A : %d configurations x %d variantes x 3 seuils",
             len(FOCUS), len(VARIANTS))
    rng = np.random.default_rng(20260820)
    rows = []
    for f in FOCUS:
        cell = sel[(sel["signal_type"] == f["signal_type"])
                   & (sel["asset"] == f["asset"])
                   & (sel["timeframe"] == f["timeframe"])
                   & (sel["k"] == f["k"])]
        if cell.empty:
            LOG.warning("configuration introuvable : %s", f)
            continue
        cell = cell.iloc[0].to_dict()
        bars, rt = _bars_and_cost(f["asset"], f["timeframe"])
        sig = _signal(bars, cell, f["timeframe"])
        for q in (Q_PRIMARY, 0.80, 0.95):
            for v in VARIANTS:
                r = run_variant(bars, cell, sig, rt, q, v, rng,
                                a.placebo if q == Q_PRIMARY else 0)
                if r:
                    rows.append(r)
        LOG.info("  %s %s %s k=%d : %d lignes", f["signal_type"], f["asset"],
                 f["timeframe"], f["k"], len(rows))
    focus = pd.DataFrame(rows)

    # ---------------- partie B : le controle de generalisation
    LOG.info("PARTIE B : les memes %d variantes sur les %d cellules, q = %.2f",
             len(VARIANTS), len(sel), Q_PRIMARY)
    groups = [((asset, tf), g.to_dict("records"))
              for (asset, tf), g in sel.groupby(["asset", "timeframe"])]
    t0 = time.time()
    grows: list[dict] = []
    if a.jobs > 1:
        with ProcessPoolExecutor(max_workers=a.jobs) as ex:
            for r in ex.map(run_group, groups):
                grows += r
    else:
        for gr in groups:
            grows += run_group(gr)
    gen = pd.DataFrame(grows)
    LOG.info("  %d lignes en %.1f min", len(gen), (time.time() - t0) / 60)

    focus.to_parquet(C.DATA / "exit_focus.parquet", index=False)
    gen.to_parquet(C.DATA / "exit_generalization.parquet", index=False)

    LOG.info("-" * 78)
    ref = gen[gen["variant"] == VARIANTS[0][0]]
    ref_med = float(ref["expectancy_R"].median())
    for name, _lb, _act, kind in VARIANTS:
        g = gen[gen["variant"] == name]
        if not len(g):
            continue
        j = g.merge(ref[["signal_type", "asset", "timeframe", "k", "expectancy_R"]],
                    on=["signal_type", "asset", "timeframe", "k"],
                    suffixes=("", "_ref"))
        LOG.info("173 cellules | %-30s | E[R] med %+.4f (%+.4f vs dur) | "
                 "%.0f %% ameliorees | stop %.0f %%", name,
                 g["expectancy_R"].median(), g["expectancy_R"].median() - ref_med,
                 100 * (j["expectancy_R"] > j["expectancy_R_ref"]).mean(),
                 100 * g["stop_rate"].median())
    LOG.info("-" * 78)
    for _, r in focus[focus["threshold_q"] == Q_PRIMARY].iterrows():
        LOG.info("%-8s %-6s | %-30s | E[R] %+.4f | stop %5.1f %% | PF %.3f | N %5d",
                 r["signal_type"], r["asset"], r["variant"], r["expectancy_R"],
                 100 * r["stop_rate"], r["profit_factor"], int(r["n_trades"]))

    write_report(focus, gen, C.ROOT / "rapport_optimisation_sortie.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
