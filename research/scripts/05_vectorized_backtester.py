"""ETAPE 5 -- moteur de backtest vectorise en R-multiples sur les 173 cellules.

    python research/scripts/05_vectorized_backtester.py --selftest
    python research/scripts/05_vectorized_backtester.py [--jobs 8] [--placebo 40]

La phase 1 mesurait "ce signal sait-il quelque chose". Cette phase mesure "ce
que le signal sait survit-il a un stop dur, a une barriere de temps et au
peage". Ce sont deux questions differentes et ce depot a deja mesure qu'elles
ont des reponses opposees ([[exp-017]] : le SL obligatoire RETOURNE le signe du
bord ; [[exp-019]] : un IC significatif produit une sleeve significativement
PERDANTE).

SEPT DECISIONS D'EXECUTION, toutes conservatrices.

1. LE SEUIL D'ENTREE N'EXISTAIT PAS EN PHASE 1, IL EST DONC CREE ICI ET DIT.
   La porte IC portait sur un signal CONTINU : aucun seuil n'en sort. L'entree
   est donc definie ici par le RANG CAUSAL de S_t dans sa propre fenetre
   glissante (1 000 barres, 500 minimum) -- jamais par un quantile de
   l'echantillon entier, qui serait une fuite parfaite. Le seuil primaire est
   PRE-ENREGISTRE a q = 0,90 ; 0,80 et 0,95 sont rendus comme robustesse et
   marques comme tels.

2. LE SENS VIENT DU SIGNE DE L'IC MESURE, PAS DU MECANISME ANNONCE. Une anomalie
   de momentum sortie a IC negatif est traitee en contre-tendance, exactement
   comme le demande le mandat. `sens = signe(IC) x signe(la queue franchie)`.

3. UNE POSITION A LA FOIS. Balayage glouton causal : un signal est ignore si le
   poste est occupe. Sans cette regle, [[exp-019]] avait vu E[R] passer de
   +0,190 a +0,500 et fabriquer un faux survivant FDR. C'est la regle la plus
   importante du fichier.

4. LE GAP EST HONORE. Si la barre OUVRE au-dela du stop, la sortie se fait a
   l'ouverture -- donc a PIRE que -1R. Un moteur qui rend exactement -1R dans ce
   cas s'offre un stop garanti que le broker ne garantit pas.

5. STOP ET CIBLE TOUCHES DANS LA MEME BARRE -> LE STOP GAGNE. On ne sait pas
   dans quel ordre ils ont ete touches a l'interieur de la barre ; supposer la
   cible serait s'offrir gratuitement le meilleur des deux.

6. LE PEAGE EST DEDUIT EN R, PAS APPLIQUE AUX PRIX. `rt_pts` (plancher de spread
   non nul + commission + 1 pip de slippage PAR COTE) est deja un cout
   aller-retour en points ; l'appliquer AUSSI aux prix d'entree et de sortie le
   compterait deux fois. `cout_R = rt_pts x point / (1,5 x ATR14)`.

7. DEUX TEMOINS, PARCE QUE 173 CELLULES x 3 SORTIES x 3 SEUILS = 1 557 TESTS.
   (a) Le TEMOIN DE SENS : les memes entrees resolues dans l'autre sens. Si les
   deux sens gagnent, ce n'est pas un bord directionnel, c'est de la geometrie
   ou de la derive. (b) Le TEMOIN D'ENTREE ALEATOIRE : meme nombre de trades,
   meme geometrie, entrees tirees au hasard. Plus BH-FDR sur la t-stat de E[R].
"""
from __future__ import annotations

import argparse
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

LOG = C.get_logger("05_backtest")

# ------------------------------------------------------------------ reglages
SL_ATR_MULT = 1.5                 # 1R = 1,5 x ATR14, la lettre du mandat
RANK_WIN, RANK_MIN = 1000, 500    # fenetre du rang causal du signal
Q_PRIMARY = 0.90                  # seuil PRE-ENREGISTRE
Q_ROBUST = (0.80, 0.95)           # rendus, mais marques "robustesse"
EXITS = ("time", "tp2", "tp3")    # barriere de temps seule, ou cible a 2R / 3R
TP_MULT = {"time": None, "tp2": 2.0, "tp3": 3.0}

# ------------------------------------------------------------------ porte
GATE_MIN_ER = 0.18
GATE_MIN_N = 100
GATE_MIN_PF = 1.25
FDR_Q = 0.10


# ------------------------------------------------------------------ outils
def causal_rank(x: np.ndarray, win: int = RANK_WIN, minp: int = RANK_MIN) -> np.ndarray:
    """Rang de x_t parmi ses `win` DERNIERES OCCURRENCES, en [0, 1].

    Un quantile calcule sur l'echantillon entier serait une fuite parfaite et
    invisible : le seuil d'entree de 2019 connaitrait la distribution de 2026.
    La fenetre ne regarde donc que le passe.

    LA FENETRE COMPTE LES OCCURRENCES DU SIGNAL, PAS LES BARRES, et c'est un
    defaut deja paye ici : la moitie des familles du mandat sont des signaux de
    SESSION, definis sur ~25 % des barres seulement. Une fenetre de 1 000
    BARRES n'y contient que ~250 valeurs, donc jamais les 500 exigees -- le
    rang sortait entierement NaN et ces cellules produisaient silencieusement
    ZERO configuration. On range donc la serie compactee de ses valeurs
    valides, puis on redispose a leur place d'origine.
    """
    out = np.full(x.size, np.nan)
    idx = np.flatnonzero(np.isfinite(x))
    if idx.size < minp:
        return out
    out[idx] = (pd.Series(x[idx]).rolling(win, min_periods=minp)
                .rank(pct=True).to_numpy())
    return out


def nonoverlap(entry: np.ndarray, exit_: np.ndarray) -> np.ndarray:
    """Balayage glouton causal : garder un trade seulement si le poste est libre."""
    keep = np.zeros(entry.size, dtype=bool)
    free = -1
    e, x = entry.tolist(), exit_.tolist()
    for i in range(len(e)):
        if e[i] >= free:
            keep[i] = True
            free = x[i]
    return keep


def simulate(o, h, l, entry_i: np.ndarray, side: np.ndarray, r_px: np.ndarray,
             k: int, tp: float | None):
    """Resout chaque trade barre par barre. Rend (R brut, indice de sortie).

    Entree a l'OUVERTURE de `entry_i + 1`, sortie a l'ouverture de `entry_i+1+k`
    au plus tard. Boucle sur les k decalages (k <= 24) : c'est vectorise sur les
    trades, ce qui est la dimension qui compte.
    """
    n_t = entry_i.size
    e0 = entry_i + 1                              # barre d'entree
    px_in = o[e0]
    stop = px_in - side * r_px
    targ = px_in + side * tp * r_px if tp else None

    out_r = np.full(n_t, np.nan)
    out_i = e0 + k                                # sortie par defaut : temps
    done = np.zeros(n_t, dtype=bool)

    for j in range(k):
        b = e0 + j
        alive = ~done
        if not alive.any():
            break
        hi, lo, op = h[b], l[b], o[b]

        # DECISION 4 : le gap est honore -- si la barre OUVRE au-dela du stop,
        # la sortie se fait a l'ouverture, donc a pire que -1R.
        gap_sl = alive & (side * (op - stop) <= 0)
        # DECISION 5 : stop et cible dans la meme barre -> le stop gagne.
        hit_sl = alive & ~gap_sl & (side * (np.where(side > 0, lo, hi) - stop) <= 0)

        if tp:
            gap_tp = alive & ~gap_sl & (side * (op - targ) >= 0)
            hit_tp = (alive & ~gap_sl & ~hit_sl & ~gap_tp
                      & (side * (np.where(side > 0, hi, lo) - targ) >= 0))
        else:
            gap_tp = hit_tp = np.zeros(n_t, dtype=bool)

        for mask, price in ((gap_sl, op), (hit_sl, stop),
                            (gap_tp, op), (hit_tp, targ)):
            if mask.any():
                p = price[mask] if isinstance(price, np.ndarray) else price
                out_r[mask] = side[mask] * (p - px_in[mask]) / r_px[mask]
                out_i[mask] = b[mask]
                done[mask] = True

    left = ~done
    if left.any():
        b = np.minimum(e0[left] + k, o.size - 1)
        out_r[left] = side[left] * (o[b] - px_in[left]) / r_px[left]
        out_i[left] = b
    return out_r, out_i


def metrics(r: np.ndarray) -> dict:
    """Les metriques du mandat, plus la t-stat qui sert au FDR."""
    n = int(r.size)
    if n == 0:
        return dict(n_trades=0, expectancy_R=0.0, t_stat=0.0, win_rate=0.0,
                    profit_factor=0.0, total_R=0.0, max_dd_R=0.0,
                    max_consec_wins=0, max_consec_losses=0,
                    best_trade_R=0.0, worst_trade_R=0.0)
    m = float(r.mean())
    sd = float(r.std(ddof=1)) if n > 1 else 0.0
    gp = float(r[r > 0].sum())
    gl = float(-r[r < 0].sum())
    eq = np.cumsum(r)
    dd = float((eq - np.maximum.accumulate(eq)).min()) if n else 0.0

    win = r > 0
    def _streak(mask):
        best = cur = 0
        for v in mask.tolist():
            cur = cur + 1 if v else 0
            best = max(best, cur)
        return int(best)

    return dict(
        n_trades=n, expectancy_R=m,
        t_stat=float(m / (sd / np.sqrt(n))) if sd > 0 else 0.0,
        win_rate=float(win.mean()),
        profit_factor=float(gp / gl) if gl > 0 else float("inf"),
        total_R=float(r.sum()), max_dd_R=dd,
        max_consec_wins=_streak(win), max_consec_losses=_streak(~win),
        best_trade_R=float(r.max()), worst_trade_R=float(r.min()))


# ------------------------------------------------------------------ une cellule
def run_cell(bars, cell: dict, sig: np.ndarray, cost_R_all: np.ndarray,
             q: float, exit_kind: str, rng, n_placebo: int) -> dict | None:
    """Une configuration = (cellule, seuil, mode de sortie)."""
    k = int(cell["k"])
    ic_sign = 1.0 if cell["ic_mean"] > 0 else -1.0
    n = len(bars)
    atr = bars.atr(C.ATR_LEN)
    r_px_all = SL_ATR_MULT * atr

    pr = causal_rank(sig)
    hi_tail = pr >= q
    lo_tail = pr <= (1.0 - q)
    ok = (np.isfinite(sig) & np.isfinite(pr) & np.isfinite(r_px_all)
          & (r_px_all > 0) & (np.arange(n) + 1 + k < n))
    cand = np.flatnonzero(ok & (hi_tail | lo_tail))
    if cand.size < 20:
        return None

    # DECISION 2 : le sens vient du signe de l'IC mesure.
    side = np.where(hi_tail[cand], 1.0, -1.0) * ic_sign
    r_px = r_px_all[cand]
    tp = TP_MULT[exit_kind]

    gross, exit_i = simulate(bars.o, bars.h, bars.l, cand, side, r_px, k, tp)
    keep = nonoverlap(cand + 1, exit_i)           # DECISION 3
    if keep.sum() < 10:
        return None
    gross, cost = gross[keep], cost_R_all[cand[keep]]
    net = gross - cost                            # DECISION 6

    m = metrics(net)
    m_gross = metrics(gross)

    # MOITIES CHRONOLOGIQUES. Une esperance portee par une seule moitie de
    # l'histoire n'est pas une esperance, c'est un regime. Le decoupage se fait
    # sur les TRADES ordonnes dans le temps, donc sans reequilibrage.
    half = m["n_trades"] // 2
    er_h1 = float(net[:half].mean()) if half >= 5 else np.nan
    er_h2 = float(net[half:].mean()) if (m["n_trades"] - half) >= 5 else np.nan

    # TEMOIN (a) : les MEMES entrees, sens inverse, tout le reste constant.
    g_inv, x_inv = simulate(bars.o, bars.h, bars.l, cand, -side, r_px, k, tp)
    kinv = nonoverlap(cand + 1, x_inv)
    inv = metrics(g_inv[kinv] - cost_R_all[cand[kinv]])

    # TEMOIN (b) : entrees ALEATOIRES, meme effectif, meme geometrie.
    pl = []
    lo_b, hi_b = 0, n - k - 2
    for _ in range(n_placebo):
        ri = np.sort(rng.integers(lo_b, hi_b, size=cand.size))
        ri = ri[np.isfinite(r_px_all[ri]) & (r_px_all[ri] > 0)]
        if ri.size < 10:
            continue
        rs = rng.choice([-1.0, 1.0], size=ri.size)
        g, xi = simulate(bars.o, bars.h, bars.l, ri, rs, r_px_all[ri], k, tp)
        kk = nonoverlap(ri + 1, xi)
        if kk.sum() < 10:
            continue
        pl.append(float((g[kk] - cost_R_all[ri[kk]]).mean()))

    return dict(
        signal_id=cell["signal_id"], family=cell["family"],
        signal_type=cell["signal_type"], params=cell["params"],
        asset=cell["asset"], asset_class=cell["asset_class"],
        timeframe=cell["timeframe"], k=k,
        ic_mean=float(cell["ic_mean"]), ic_t=float(cell["t_stat"]),
        edge_to_cost=float(cell["edge_to_cost"]),
        threshold_q=q, is_primary_threshold=bool(q == Q_PRIMARY),
        exit_rule=exit_kind, direction_sign=int(ic_sign),
        cost_R_median=float(np.median(cost)),
        expectancy_R_gross=m_gross["expectancy_R"],
        expectancy_R_half1=er_h1, expectancy_R_half2=er_h2,
        inverse_expectancy_R=inv["expectancy_R"],
        inverse_n=inv["n_trades"],
        placebo_expectancy_R=float(np.mean(pl)) if pl else np.nan,
        placebo_beat_frac=float(np.mean([p >= m["expectancy_R"] for p in pl]))
        if pl else np.nan,
        **m)


# ------------------------------------------------------------------ un groupe
def run_group(args) -> list[dict]:
    (asset, tf), cells, n_placebo, seed = args
    bars = C.load(asset, tf)
    if bars is None:
        return []
    costs = json.loads(C.costs_path().read_text(encoding="utf-8"))
    ref = costs.get(asset, {}).get("H1") or next(iter(costs.get(asset, {}).values()), {})
    rt_price = float(ref.get("rt_pts", np.nan)) * float(ref.get("point", np.nan)) \
        if "point" in ref else np.nan
    if not np.isfinite(rt_price):
        meta = C.symbols_meta().get(asset, {})
        rt_price = float(ref.get("rt_pts", 0.0)) * float(meta.get("point", 0.0))
    cost_R_all = rt_price / (SL_ATR_MULT * bars.atr(C.ATR_LEN))

    rng = np.random.default_rng(seed)
    out = []
    for cell in cells:
        spec = dict(type=cell["signal_type"], family=cell["family"],
                    sign_prior=0, params=json.loads(cell["params"]))
        drv = None
        if spec["type"] in SG.CROSS_TYPES:
            import importlib.util
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
            for ex in EXITS:
                r = run_cell(bars, cell, sig, cost_R_all, q, ex, rng, n_placebo)
                if r:
                    out.append(r)
    LOG.info("%-7s %-3s : %2d cellules -> %3d configurations",
             asset, tf, len(cells), len(out))
    return out


# ------------------------------------------------------------------ selection
def bh_qvalues(p: np.ndarray) -> np.ndarray:
    m = p.size
    order = np.argsort(p)
    ranked = p[order] * m / np.arange(1, m + 1)
    q_sorted = np.minimum.accumulate(ranked[::-1])[::-1]
    q = np.empty(m)
    q[order] = np.clip(q_sorted, 0, 1)
    return q


def apply_gate(df: pd.DataFrame) -> pd.Series:
    return ((df["expectancy_R"] >= GATE_MIN_ER)
            & (df["n_trades"] >= GATE_MIN_N)
            & (df["profit_factor"] >= GATE_MIN_PF))


# ------------------------------------------------------------------ self-test
def selftest() -> int:
    """Le moteur doit rendre les bons R sur des cas ou la reponse est connue."""
    fails = 0
    n = 400
    o = np.full(n, 100.0)
    h = np.full(n, 100.0)
    l = np.full(n, 100.0)

    # 1. stop touche exactement -> -1R
    h2, l2 = h.copy(), l.copy()
    l2[6] = 98.0
    r, xi = simulate(o, h2, l2, np.array([5]), np.array([1.0]),
                     np.array([2.0]), 10, None)
    ok = abs(r[0] + 1.0) < 1e-9
    LOG.info("selftest 1 | stop touche : R=%+.4f (%s)", r[0], "OK" if ok else "ECHEC")
    fails += 0 if ok else 1

    # 2. gap SOUS le stop -> pire que -1R, et c'est le point.
    #    Le gap doit tomber APRES la barre d'entree : l'entree se fait a
    #    l'ouverture de e0, donc un gap sur e0 lui-meme n'est pas un gap, c'est
    #    le prix d'entree. (Ce test s'est trompe une premiere fois exactement la.)
    o3 = o.copy(); o3[7] = 97.0
    h3 = h.copy(); h3[7] = 97.0
    l3 = l.copy(); l3[7] = 97.0
    r, _ = simulate(o3, h3, l3, np.array([5]), np.array([1.0]),
                    np.array([2.0]), 10, None)
    ok = abs(r[0] + 1.5) < 1e-9
    LOG.info("selftest 2 | gap sous le stop : R=%+.4f, attendu -1.5 (%s)",
             r[0], "OK" if ok else "ECHEC")
    fails += 0 if ok else 1

    # 3. cible a +2R touchee -> +2R
    h4 = h.copy(); h4[8] = 104.5
    r, _ = simulate(o, h4, l, np.array([5]), np.array([1.0]),
                    np.array([2.0]), 10, 2.0)
    ok = abs(r[0] - 2.0) < 1e-9
    LOG.info("selftest 3 | cible +2R : R=%+.4f (%s)", r[0], "OK" if ok else "ECHEC")
    fails += 0 if ok else 1

    # 4. stop ET cible dans la MEME barre -> le stop gagne
    h5 = h.copy(); l5 = l.copy()
    h5[7] = 104.5; l5[7] = 98.0
    r, _ = simulate(o, h5, l5, np.array([5]), np.array([1.0]),
                    np.array([2.0]), 10, 2.0)
    ok = abs(r[0] + 1.0) < 1e-9
    LOG.info("selftest 4 | stop et cible meme barre : R=%+.4f, le stop doit "
             "gagner (%s)", r[0], "OK" if ok else "ECHEC")
    fails += 0 if ok else 1

    # 5. symetrie long/court sur une serie miroir
    rng = np.random.default_rng(3)
    c = 100 + np.cumsum(rng.standard_normal(n) * 0.3)
    hh, ll = c + 0.4, c - 0.4
    ent = np.arange(20, 300, 17)
    rl, _ = simulate(c, hh, ll, ent, np.ones(ent.size), np.full(ent.size, 1.0), 8, None)
    cm = 200.0 - c
    rs, _ = simulate(cm, 200.0 - ll, 200.0 - hh, ent, -np.ones(ent.size),
                     np.full(ent.size, 1.0), 8, None)
    ok = np.allclose(rl, rs, atol=1e-9)
    LOG.info("selftest 5 | symetrie long/court sur serie miroir : ecart max "
             "%.2e (%s)", float(np.max(np.abs(rl - rs))), "OK" if ok else "ECHEC")
    fails += 0 if ok else 1

    # 6. la regle d'occupation refuse vraiment les chevauchements
    e = np.array([0, 1, 2, 20, 21, 40])
    x = np.array([10, 11, 12, 30, 31, 50])
    keep = nonoverlap(e, x)
    ok = keep.tolist() == [True, False, False, True, False, True]
    LOG.info("selftest 6 | une position a la fois : %s (%s)",
             keep.astype(int).tolist(), "OK" if ok else "ECHEC")
    fails += 0 if ok else 1

    # 7. le rang d'entree ne regarde pas devant lui
    x = rng.standard_normal(5000)
    a = causal_rank(x)
    x2 = x.copy(); x2[2500:] += 50.0
    b = causal_rank(x2)
    ok = np.allclose(a[:2500], b[:2500], equal_nan=True)
    LOG.info("selftest 7 | causalite du seuil d'entree : %s",
             "OK" if ok else "ECHEC")
    fails += 0 if ok else 1

    # 8. UN SIGNAL DE SESSION DOIT QUAND MEME RECEVOIR UN RANG.
    #    Defini sur ~20 % des barres, il n'a jamais 500 valeurs dans 1 000
    #    BARRES -- la fenetre doit donc compter les OCCURRENCES. Sans ce test,
    #    huit familles sur seize sortaient zero configuration en silence.
    sparse = np.full(20_000, np.nan)
    vis = np.arange(0, 20_000, 5)
    sparse[vis] = rng.standard_normal(vis.size)
    pr = causal_rank(sparse)
    n_ok = int(np.isfinite(pr).sum())
    ok = n_ok > 3000 and np.all(np.isnan(pr[np.isnan(sparse)]))
    LOG.info("selftest 8 | signal de session (1 barre sur 5) : %d rangs definis "
             "sur %d occurrences (%s)", n_ok, vis.size, "OK" if ok else "ECHEC")
    fails += 0 if ok else 1

    LOG.info("SELFTEST MOTEUR : %s", "8/8 OK" if fails == 0 else f"{8-fails}/8 OK")
    return fails


# ------------------------------------------------------------------ principal
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--jobs", type=int, default=max(1, (os_cpu() - 1)))
    ap.add_argument("--placebo", type=int, default=40)
    a = ap.parse_args()
    if a.selftest:
        return 1 if selftest() else 0

    if selftest():
        LOG.error("le moteur echoue ses propres tests -- rien n'est mesure")
        return 1

    d = pd.read_parquet(C.DATA / "ic_results_scored.parquet")
    sel = d[(d["passes_gate"]) & (d["k"] >= 5) & (d["edge_to_cost"] >= 1.0)].copy()
    LOG.info("=" * 78)
    LOG.info("PHASE 2 : %d cellules retenues de la phase 1 "
             "(k >= 5 ET bord/peage >= 1,0)", len(sel))
    LOG.info("grille = %d cellules x %d seuils x %d sorties = %d configurations",
             len(sel), 1 + len(Q_ROBUST), len(EXITS),
             len(sel) * (1 + len(Q_ROBUST)) * len(EXITS))

    groups = []
    for i, ((asset, tf), g) in enumerate(sel.groupby(["asset", "timeframe"])):
        groups.append(((asset, tf), g.to_dict("records"), a.placebo, 20260818 + i))

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
    df["fdr_q"] = bh_qvalues(df["p_value"].to_numpy())
    df["passes_fdr"] = df["fdr_q"] <= FDR_Q
    df["passes_gate"] = apply_gate(df)
    # temoin de sens : les DEUX sens gagnants = geometrie ou derive, pas un bord
    df["both_sides_win"] = (df["expectancy_R"] > 0) & (df["inverse_expectancy_R"] > 0)
    # Decomposition : ce que le SENS apporte, et ce que la geometrie + le peage
    # retirent. La moyenne des deux sens ne contient aucune information
    # directionnelle par construction -- c'est la derive du bracket.
    df["directional_edge_R"] = (df["expectancy_R"] - df["inverse_expectancy_R"]) / 2
    df["geometry_drag_R"] = (df["expectancy_R"] + df["inverse_expectancy_R"]) / 2
    df["both_halves_positive"] = ((df["expectancy_R_half1"] > 0)
                                  & (df["expectancy_R_half2"] > 0))
    df.to_parquet(C.DATA / "backtest_results.parquet", index=False)

    LOG.info("-" * 78)
    LOG.info("configurations mesurees : %d en %.1f min", len(df),
             (time.time() - t0) / 60)
    LOG.info("porte E[R]>=%.2f & N>=%d & PF>=%.2f : %d configurations",
             GATE_MIN_ER, GATE_MIN_N, GATE_MIN_PF, int(df["passes_gate"].sum()))
    LOG.info("  dont survivants BH-FDR (q<=%.2f)          : %d",
             FDR_Q, int((df["passes_gate"] & df["passes_fdr"]).sum()))
    LOG.info("  dont les DEUX sens gagnent (a rejeter)    : %d",
             int((df["passes_gate"] & df["both_sides_win"]).sum()))
    LOG.info("  dont battues par >10%% des temoins aleatoires : %d",
             int((df["passes_gate"] & (df["placebo_beat_frac"] > 0.10)).sum()))
    prim = df[df["is_primary_threshold"]]
    LOG.info("E[R] max %.4f | t max %.2f | q min %.4f",
             df["expectancy_R"].max(), df["t_stat"].max(), df["fdr_q"].min())
    LOG.info("E[R] max au seuil PRE-ENREGISTRE q=%.2f : %.4f "
             "(le maximum global vient d'un seuil de robustesse)",
             Q_PRIMARY, prim["expectancy_R"].max())
    LOG.info("bord DIRECTIONNEL median %.4f R (positif dans %.1f %% des configs) "
             "| derive geometrie+peage %.4f R",
             df["directional_edge_R"].median(),
             100 * (df["directional_edge_R"] > 0).mean(),
             df["geometry_drag_R"].median())
    LOG.info("E[R] positif dans les DEUX moities : %d / %d",
             int(df["both_halves_positive"].sum()), len(df))

    write_outputs(df, sel)
    return 0


def os_cpu() -> int:
    import os
    return os.cpu_count() or 4


def write_outputs(df: pd.DataFrame, sel: pd.DataFrame) -> None:
    """Le JSON des survivantes et le tableau des 25 meilleures."""
    # La porte du mandat, plus trois controles : FDR, temoin de sens, et les deux
    # moities chronologiques positives. Une esperance qui vit dans une seule
    # moitie de l'histoire est un regime, pas une esperance.
    surv = df[df["passes_gate"] & df["passes_fdr"] & ~df["both_sides_win"]
              & df["both_halves_positive"]].copy()
    surv = surv.sort_values("expectancy_R", ascending=False)

    recs = []
    for i, (_, r) in enumerate(surv.iterrows(), start=1):
        recs.append({
            "strategy_id": f"S{i:03d}_{r['signal_type'].upper()}_{r['asset']}"
                           f"_{r['timeframe']}_K{int(r['k'])}_{r['exit_rule'].upper()}",
            "source_hypothesis_id": r["signal_id"],
            "asset": r["asset"], "asset_class": r["asset_class"],
            "timeframe": r["timeframe"], "forward_horizon_k": int(r["k"]),
            "signal_definition": {"type": r["signal_type"],
                                  "params": json.loads(r["params"])},
            "execution": {
                "entry": "rang causal de S_t sur 1000 barres; entree a l'open de t+1",
                "threshold_q": float(r["threshold_q"]),
                "threshold_is_preregistered": bool(r["is_primary_threshold"]),
                "direction_sign": int(r["direction_sign"]),
                "stop_loss": f"{SL_ATR_MULT} x ATR14 a t (fixe) = 1R",
                "exit_rule": r["exit_rule"],
                "max_hold_bars": int(r["k"]),
            },
            "metrics": {
                "expectancy_R": round(float(r["expectancy_R"]), 4),
                "expectancy_R_gross": round(float(r["expectancy_R_gross"]), 4),
                "n_trades": int(r["n_trades"]),
                "win_rate": round(float(r["win_rate"]), 4),
                "profit_factor": round(float(r["profit_factor"]), 3),
                "total_R": round(float(r["total_R"]), 2),
                "max_drawdown_R": round(float(r["max_dd_R"]), 2),
                "max_consec_wins": int(r["max_consec_wins"]),
                "max_consec_losses": int(r["max_consec_losses"]),
                "best_trade_R": round(float(r["best_trade_R"]), 2),
                "worst_trade_R": round(float(r["worst_trade_R"]), 2),
                "t_stat": round(float(r["t_stat"]), 3),
            },
            "controls": {
                "cost_R_median": round(float(r["cost_R_median"]), 4),
                "inverse_direction_expectancy_R": round(float(r["inverse_expectancy_R"]), 4),
                "placebo_expectancy_R": (round(float(r["placebo_expectancy_R"]), 4)
                                         if pd.notna(r["placebo_expectancy_R"]) else None),
                "placebo_beat_fraction": (round(float(r["placebo_beat_frac"]), 4)
                                          if pd.notna(r["placebo_beat_frac"]) else None),
                "fdr_q": round(float(r["fdr_q"]), 5),
                "phase1_ic_mean": round(float(r["ic_mean"]), 5),
                "phase1_edge_to_cost": round(float(r["edge_to_cost"]), 3),
            },
        })
    (C.ROOT / "validated_strategies.json").write_text(
        json.dumps(recs, indent=2, ensure_ascii=False), encoding="utf-8")
    LOG.info("livrable : %d strategies -> research/validated_strategies.json", len(recs))

    write_report(df, sel, surv, C.ROOT / "rapport_backtest_R.md")


def write_report(df: pd.DataFrame, sel: pd.DataFrame, surv: pd.DataFrame,
                 path: Path) -> None:
    L, A = [], None
    A = L.append
    A("# Phase 2 -- backtest vectorise en R-multiples\n")
    A(f"_Genere le {time.strftime('%Y-%m-%d %H:%M')} -- 1R = "
      f"{SL_ATR_MULT} x ATR14, peage Pepperstone mesure, une position a la fois._\n")

    A("\n## Ce qui a ete teste\n")
    A(f"- **{len(sel)}** cellules heritees de la phase 1 (k >= 5 ET bord/peage >= 1,0).")
    A(f"- x {1+len(Q_ROBUST)} seuils d'entree x {len(EXITS)} regles de sortie "
      f"= **{len(df)}** configurations effectivement mesurees.")
    A(f"- Porte : `E[R] >= {GATE_MIN_ER}` ET `N >= {GATE_MIN_N}` ET "
      f"`PF >= {GATE_MIN_PF}`.\n")

    n_gate = int(df["passes_gate"].sum())
    n_fdr = int((df["passes_gate"] & df["passes_fdr"]).sum())
    n_both = int((df["passes_gate"] & df["both_sides_win"]).sum())
    A("\n## Le compte\n")
    A("| etape | configurations restantes |")
    A("|---|--:|")
    A(f"| mesurees | {len(df)} |")
    A(f"| porte E[R] / N / PF | **{n_gate}** |")
    A(f"| + survivantes BH-FDR (q <= {FDR_Q}) | {n_fdr} |")
    A(f"| − dont les DEUX sens gagnent (geometrie, pas bord) | −{n_both} |")
    n_half = int((df["passes_gate"] & df["passes_fdr"] & ~df["both_sides_win"]
                  & ~df["both_halves_positive"]).sum())
    A(f"| moins dont E[R] negatif dans une moitie de l'histoire | -{n_half} |")
    A(f"| **retenues** | **{len(surv)}** |")

    A("\n## Ce que le stop dur fait au bord\n")
    A("La phase 1 mesurait un IC **sans stop**. Ici chaque trade porte un stop a "
      f"{SL_ATR_MULT} x ATR14. La comparaison brut / net et le temoin de sens "
      "disent ce qu'il en reste.\n")
    A("\n| sortie | configs | E[R] brut median | E[R] net median | peage median (R) "
      "| passent la porte |")
    A("|---|--:|--:|--:|--:|--:|")
    for ex in EXITS:
        g = df[df["exit_rule"] == ex]
        if not len(g):
            continue
        A(f"| {ex} | {len(g)} | {g['expectancy_R_gross'].median():+.4f} | "
          f"{g['expectancy_R'].median():+.4f} | {g['cost_R_median'].median():.4f} | "
          f"{int(g['passes_gate'].sum())} |")

    A("\n| UT | configs | E[R] net median | peage median (R) | passent |")
    A("|---|--:|--:|--:|--:|")
    for tf in C.TIMEFRAMES:
        g = df[df["timeframe"] == tf]
        if not len(g):
            continue
        A(f"| {tf} | {len(g)} | {g['expectancy_R'].median():+.4f} | "
          f"{g['cost_R_median'].median():.4f} | {int(g['passes_gate'].sum())} |")

    A("\n## Le resultat central : le stop dur annule le bord\n")
    A("Chaque entree a ete resolue **dans les deux sens**, peage et geometrie "
      "constants. La difference des deux est ce que le SENS apporte ; leur "
      "moyenne est ce que le bracket coute, sans aucune information "
      "directionnelle dedans.\n")
    A(f"\n- Bord **directionnel** median : **{df['directional_edge_R'].median():+.4f} R** "
      f"-- positif dans **{100*(df['directional_edge_R'] > 0).mean():.1f} %** des "
      "configurations, c'est-a-dire un pile ou face.")
    A(f"- Derive **geometrie + peage** mediane : **{df['geometry_drag_R'].median():+.4f} R**.")
    A(f"- E[R] **brut** median : **{df['expectancy_R_gross'].median():+.4f} R** -- "
      "donc la geometrie perd deja avant le premier centime de frais.")
    A("\nLa phase 1 avait mesure un IC **sans stop** sur ces memes cellules. Avec "
      "un stop a 1,5 x ATR14 et une barriere de temps, **il n'en reste rien en "
      "moyenne**. C'est la mesure d'exp-017 reproduite sur une famille "
      "entierement differente : le stop obligatoire ne reduit pas le bord, il "
      "l'annule.\n")

    A("\n## L'effet de selection du seuil, nomme\n")
    A(f"Le seuil **q = {Q_PRIMARY:.2f} etait le seul PRE-ENREGISTRE** ; "
      f"{Q_ROBUST} sont des controles de robustesse. Le maximum global vient du "
      "seuil le plus serre -- donc du plus permissif en degres de liberte.\n")
    A("\n| seuil q | pre-enregistre | configs | E[R] max | E[R] median | % positives |")
    A("|--:|---|--:|--:|--:|--:|")
    for q in sorted(df["threshold_q"].unique()):
        g = df[df["threshold_q"] == q]
        A(f"| {q:.2f} | {'**oui**' if q == Q_PRIMARY else 'non'} | {len(g)} | "
          f"**{g['expectancy_R'].max():+.4f}** | {g['expectancy_R'].median():+.4f} | "
          f"{100*(g['expectancy_R'] > 0).mean():.1f} % |")
    pmax = float(df[df["is_primary_threshold"]]["expectancy_R"].max())
    A(f"\n**Au seuil pre-enregistre le meilleur E[R] vaut {pmax:.4f} R**, soit "
      f"{100*pmax/GATE_MIN_ER:.0f} % de la porte. Le {df['expectancy_R'].max():.4f} R "
      "du classement general n'est atteint qu'en s'autorisant un seuil qui "
      "n'avait pas ete annonce.\n")

    A("\n### Ce qui monte quand meme avec la selectivite\n")
    A("Les meilleures cellules ordonnent leur E[R] **de facon monotone** avec le "
      "seuil d'entree, sur un axe qui n'a servi a rien d'autre. Du bruit ne "
      "s'ordonne pas ainsi : c'est le seul indice positif de la phase.\n")
    best_cells = (df[df["exit_rule"] == "time"]
                  .sort_values("expectancy_R", ascending=False)
                  .drop_duplicates(["signal_type", "asset", "timeframe", "k"])
                  .head(4))
    A("\n| cellule (sortie temps) | q=0,80 | q=0,90 pre-enr. | q=0,95 | "
      "moitie 1 | moitie 2 | N |")
    A("|---|--:|--:|--:|--:|--:|--:|")
    for _, r in best_cells.iterrows():
        sub = df[(df["signal_type"] == r["signal_type"]) & (df["asset"] == r["asset"])
                 & (df["timeframe"] == r["timeframe"]) & (df["k"] == r["k"])
                 & (df["exit_rule"] == "time")]
        v = {round(float(x.threshold_q), 2): x for x in sub.itertuples()}
        cols = [f"{v[q].expectancy_R:+.3f}" if q in v else "-" for q in (0.80, 0.90, 0.95)]
        hi = v.get(0.95)
        tail = (f"{hi.expectancy_R_half1:+.3f} | {hi.expectancy_R_half2:+.3f} | "
                f"{int(hi.n_trades)} |") if hi is not None else "- | - | - |"
        A(f"| {r['signal_type']} {r['asset']} {r['timeframe']} k={int(r['k'])} | "
          + " | ".join(cols) + " | " + tail)

    A("\n## Les 25 meilleures par esperance nette\n")
    top = df.sort_values("expectancy_R", ascending=False).head(25)
    A("| # | signal | actif | UT | k | sortie | q | E[R] net | E[R] brut | N | "
      "gain % | PF | maxDD R | moitie 1 | moitie 2 | sens inverse | temoin |")
    A("|--:|---|---|---|--:|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
    for i, (_, r) in enumerate(top.iterrows(), start=1):
        pf = "inf" if not np.isfinite(r["profit_factor"]) else f"{r['profit_factor']:.2f}"
        A(f"| {i} | {r['signal_type']} | {r['asset']} | {r['timeframe']} | "
          f"{int(r['k'])} | {r['exit_rule']} | {r['threshold_q']:.2f} | "
          f"**{r['expectancy_R']:+.3f}** | {r['expectancy_R_gross']:+.3f} | "
          f"{int(r['n_trades'])} | {100*r['win_rate']:.1f} | {pf} | "
          f"{r['max_dd_R']:.1f} | {r['expectancy_R_half1']:+.3f} | "
          f"{r['expectancy_R_half2']:+.3f} | {r['inverse_expectancy_R']:+.3f} | "
          f"{r['placebo_expectancy_R']:+.3f} |")

    A("\n## Temoins\n")
    A("**Temoin de sens** : les memes entrees resolues dans l'autre sens, peage "
      "et geometrie constants. Si les deux sens gagnent, l'apport n'est pas "
      "directionnel -- c'est de la derive ou la geometrie du bracket.\n")
    A(f"\n- Configurations ou les deux sens gagnent : "
      f"**{int(df['both_sides_win'].sum())} / {len(df)}** "
      f"({100*df['both_sides_win'].mean():.1f} %).")
    A(f"- Parmi celles qui passent la porte : **{n_both} / {n_gate}**.")
    A("\n**Temoin d'entree aleatoire** : meme effectif, meme geometrie, entrees "
      "tirees au hasard, sens tire a pile ou face.\n")
    A(f"\n- E[R] median du temoin : **{df['placebo_expectancy_R'].median():+.4f} R** "
      f"(reel : {df['expectancy_R'].median():+.4f} R).")
    beat = df["placebo_beat_frac"] > 0.10
    A(f"- Configurations battues par plus de 10 % de leurs temoins : "
      f"**{int(beat.sum())} / {len(df)}**.")

    path.write_text("\n".join(L) + "\n", encoding="utf-8")
    LOG.info("rapport ecrit -> %s", path)


if __name__ == "__main__":
    raise SystemExit(main())
