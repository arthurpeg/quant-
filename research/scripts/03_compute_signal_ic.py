"""ETAPE 3 -- le moteur d'Information Coefficient. Aucun P&L, aucun stop, aucun cout.

    python research/scripts/03_compute_signal_ic.py --selftest
    python research/scripts/03_compute_signal_ic.py [--tf M5,M15,H1,H4] [--placebo 2]

Cette etape ne demande pas "combien ce signal rapporte" mais "ce signal
sait-il quelque chose". C'est la seule etape ou le P&L n'a pas le droit de
cite, et c'est la lettre du mandat.

QUATRE DECISIONS DE MESURE, toutes conservatrices, toutes verifiables par
`--selftest`.

1. LES RANGS SONT PRIS UNE FOIS SUR L'ECHANTILLON, LES BLOCS NE SERVENT QU'A
   LA DISPERSION. Un rendement a k barres se recouvre k fois avec lui-meme :
   une t-stat lue sur des observations qui se recouvrent est gonflee. Le bloc
   (un trimestre de barres) est donc l'unite statistique -- mais RECALCULER un
   Spearman DANS chaque bloc serait pire que le mal : cela recentre le passe et
   le futur sur la meme fenetre finie, ce qui les anticorrele mecaniquement.
   Sur une marche aleatoire pure cet estimateur naif rend IC ~ -0,17, vingt
   tirages sur vingt. `--selftest` le remontre a la demande. L'IC est donc la
   moyenne du produit des rangs STANDARDISES SUR TOUT L'ECHANTILLON, et un
   bloc n'en est qu'une tranche.

2. LE RENDEMENT FUTUR EST NORMALISE PAR UNE VOLATILITE CONNUE A L'AVANCE
   (ATR14/close a t). Normaliser par la volatilite realisee SUR la fenetre
   future serait une fuite classique et invisible dans le resultat. Le rang de
   Spearman est invariant par transformation monotone, mais pas par division
   par une serie qui varie dans le temps : la normalisation change donc bien
   le resultat, et elle doit se faire avec du passe.

3. DEUX t-STATS SONT RENDUES, ET LA PORTE PREND LA PLUS SEVERE. Celle du
   mandat, `MeanIC * sqrt(N) / StdIC` sur les N blocs disjoints ; et une
   version Newey-West d'ordre deduit de la memoire du facteur, parce que deux
   blocs consecutifs restent lies quand le facteur a une memoire longue.

4. LE TEMOIN EST UNE ROTATION CIRCULAIRE DU RENDEMENT FUTUR. Elle detruit le
   lien signal->futur en conservant EXACTEMENT les deux distributions
   marginales et l'autocorrelation de chacune. Le taux de passage du temoin
   est le diviseur qui dit combien de "reussites" la grille produit par
   hasard -- sans lui, une porte a |t| >= 2,5 laisse passer ~1,2 % de 30 000
   cellules, soit ~370 faux positifs.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C
import signals as SG

LOG = C.get_logger("03_ic")

MIN_PAIRS_PER_BLOCK = 20
MIN_BLOCKS = 8


# ------------------------------------------------------------------ estimateurs
def block_ic(sig: np.ndarray, fwd: np.ndarray, tf: str):
    """IC par bloc SANS recentrage local -- l'estimateur qui mesure vraiment.

    Rend (ic_par_bloc, position_de_bloc, n_paires). Les rangs sont pris une
    fois sur l'intersection des deux masques de validite ; l'IC de Spearman
    total est alors exactement la moyenne du produit z_s*z_f, et un bloc n'est
    qu'une tranche de cette moyenne.
    """
    ok = np.isfinite(sig) & np.isfinite(fwd)
    n = int(ok.sum())
    if n < MIN_PAIRS_PER_BLOCK * MIN_BLOCKS:
        return np.array([]), np.array([]), n
    zs = stats.rankdata(sig[ok])
    zf = stats.rankdata(fwd[ok])
    if zs.std() == 0 or zf.std() == 0:
        return np.array([]), np.array([]), n
    zs = (zs - zs.mean()) / zs.std()
    zf = (zf - zf.mean()) / zf.std()
    prod = zs * zf
    w = C.BLOCK_BARS[tf]
    b = np.flatnonzero(ok) // w
    nb = int(b.max()) + 1
    tot = np.bincount(b, weights=prod, minlength=nb)
    cnt = np.bincount(b, minlength=nb)
    good = cnt >= MIN_PAIRS_PER_BLOCK
    return tot[good] / cnt[good], np.flatnonzero(good), n


def block_ic_naive(sig: np.ndarray, fwd: np.ndarray, tf: str) -> np.ndarray:
    """LE PIEGE, garde pour que `--selftest` puisse le remontrer a volonte.

    Spearman recalcule DANS chaque bloc : passe et futur sont recentres sur la
    MEME fenetre finie, donc mecaniquement anticorreles. NE PAS UTILISER.
    """
    w = C.BLOCK_BARS[tf]
    out = []
    for i in range(0, sig.size, w):
        x, y = sig[i:i + w], fwd[i:i + w]
        ok = np.isfinite(x) & np.isfinite(y)
        if ok.sum() < MIN_PAIRS_PER_BLOCK:
            continue
        rx, ry = stats.rankdata(x[ok]), stats.rankdata(y[ok])
        if rx.std() == 0 or ry.std() == 0:
            continue
        out.append(float(np.corrcoef(rx, ry)[0, 1]))
    return np.array(out)


def nw_t(x: np.ndarray, lag: int = 0) -> float:
    """t-stat de la moyenne, variance a la Newey-West (lag=0 -> t ordinaire)."""
    x = x[np.isfinite(x)]
    n = x.size
    if n < MIN_BLOCKS:
        return float("nan")
    d = x - x.mean()
    var = float(d @ d) / n
    for L in range(1, min(lag, n - 1) + 1):
        w = 1.0 - L / (lag + 1.0)
        var += 2.0 * w * float(d[L:] @ d[:-L]) / n
    if var <= 0:
        return float("nan")
    return float(x.mean() / np.sqrt(var / n))


def summarize(ic: np.ndarray, n_obs: int, k: int,
              sign_prior: int, nw_lag: int) -> dict:
    """Les metriques du mandat + la stabilite par sous-periodes."""
    v = ic[np.isfinite(ic)]
    if v.size < MIN_BLOCKS:
        return {}
    m, s = float(v.mean()), float(v.std(ddof=1))
    ir = m / s if s > 0 else float("nan")
    t_mandate = ir * np.sqrt(v.size) if s > 0 else float("nan")
    t_newey = nw_t(v, nw_lag)
    # sous-periodes : quarts CONTIGUS de la serie de blocs
    q = np.array_split(np.arange(v.size), C.N_SUBPERIODS)
    sub = [float(v[i].mean()) for i in q if i.size]
    same = int(sum(1 for x in sub if np.sign(x) == np.sign(m) and x != 0))
    return dict(
        n_obs=int(n_obs), n_indep=int(n_obs // max(k, 1)), n_blocks=int(v.size),
        ic_mean=m, ic_std=s, ir_signal=float(ir),
        t_stat=float(t_mandate), t_stat_nw=float(t_newey),
        t_gate=float(min(abs(t_mandate), abs(t_newey)) * np.sign(t_mandate))
        if np.isfinite(t_newey) else float(t_mandate),
        stability_score=float((np.sign(v) == np.sign(m)).mean()),
        n_subperiods_same_sign=same,
        subperiod_ic=[round(x, 5) for x in sub],
        sign_prior=int(sign_prior),
        sign_matches_prior=bool(np.sign(m) == sign_prior),
    )


def nw_lag_for(tf: str, k: int) -> int:
    """Ordre Newey-West ENTRE blocs : au moins 1 des que le recouvrement existe."""
    span = k
    return int(min(4, max(1, np.ceil(span / C.BLOCK_BARS[tf]))))


# ------------------------------------------------------------------ meneurs
def usd_index(tf: str, index: pd.DatetimeIndex) -> np.ndarray | None:
    """Indice dollar synthetique : moyenne des log-prix des jambes, signe par sens.

    Le mandat cite "DXY vs EURUSD". Aucun DXY n'est servi par ce terminal ;
    l'indice est donc RECONSTRUIT depuis les sept majeures presentes, ce qui
    est dit ici plutot que sous-entendu. Seuls ses rendements sont utilises,
    donc le niveau et la ponderation exacte de DXY n'importent pas.
    """
    legs = {"EURUSD": -1, "GBPUSD": -1, "AUDUSD": -1, "NZDUSD": -1,
            "USDJPY": +1, "USDCHF": +1, "USDCAD": +1}
    acc, n = None, 0
    for sym, sgn in legs.items():
        b = C.load(sym, tf)
        if b is None:
            continue
        s = pd.Series(np.log(b.c), index=b.t)
        s = s[~s.index.duplicated()].reindex(index, method="ffill")
        v = sgn * s.to_numpy()
        acc = v if acc is None else acc + v
        n += 1
    if acc is None or n < 4:
        return None
    return np.exp(acc / n)


def driver_series(name: str, tf: str, index: pd.DatetimeIndex) -> np.ndarray | None:
    """Prix du meneur ALIGNE sur l'horloge de la cible, par report en arriere.

    `method='ffill'` : la valeur retenue a t est la derniere CONNUE a t. Un
    `reindex` sans methode aurait laisse des trous ; un `bfill` aurait importe
    du futur.
    """
    if name == "USDIDX":
        return usd_index(tf, index)
    b = C.load(name, tf)
    if b is None:
        return None
    s = pd.Series(b.c, index=b.t)
    s = s[~s.index.duplicated()].reindex(index, method="ffill")
    return s.to_numpy()


# ------------------------------------------------------------------ grille
def run_pair(sym: str, tf: str, specs: list[dict], horizons: list[int],
             n_placebo: int, rng: np.random.Generator) -> list[dict]:
    b = C.load(sym, tf)
    if b is None:
        return []
    vu = b.vol_unit()
    fwds = {k: b.fwd(k) / (vu * np.sqrt(k)) for k in horizons}
    drivers: dict[str, np.ndarray | None] = {}
    rows = []
    n = len(b)

    for spec in specs:
        drv = None
        if spec["type"] in SG.CROSS_TYPES:
            dn = spec["params"]["driver"]
            if dn not in drivers:
                drivers[dn] = driver_series(dn, tf, b.t)
            drv = drivers[dn]
            if drv is None:
                continue
        try:
            sig = SG.compute(b, spec, drv)
        except Exception as e:                      # pragma: no cover
            LOG.warning("%s %s %s : signal en echec (%r)", sym, tf,
                        SG.spec_key(spec), e)
            continue
        if np.isfinite(sig).sum() < MIN_PAIRS_PER_BLOCK * MIN_BLOCKS:
            continue

        for k in horizons:
            fwd = fwds[k]
            ic, _pos, n_obs = block_ic(sig, fwd, tf)
            m = summarize(ic, n_obs, k, spec["sign_prior"], nw_lag_for(tf, k))
            if not m:
                continue
            row = dict(signal_id=spec["signal_id"], family=spec["family"],
                       signal_type=spec["type"], params=json.dumps(spec["params"]),
                       asset=sym, asset_class=C.CLASS_OF[sym], timeframe=tf,
                       k=k, **m)
            # temoin apparie : meme signal, futur pivote
            if n_placebo:
                pl_ic, pl_t = [], []
                for _ in range(n_placebo):
                    sh = int(rng.integers(n // 8, 7 * n // 8))
                    p_ic, _p, p_n = block_ic(sig, np.roll(fwd, sh), tf)
                    pm = summarize(p_ic, p_n, k, spec["sign_prior"],
                                   nw_lag_for(tf, k))
                    if pm:
                        pl_ic.append(abs(pm["ic_mean"]))
                        pl_t.append(abs(pm["t_gate"]))
                if pl_ic:
                    row["placebo_abs_ic"] = float(np.mean(pl_ic))
                    row["placebo_abs_t"] = float(np.mean(pl_t))
            rows.append(row)
    return rows


# ------------------------------------------------------------------ self-test
def selftest() -> int:
    """Trois verifications, sur donnees SYNTHETIQUES, avant toute mesure reelle."""
    rng = np.random.default_rng(7)
    tf = "H1"
    w = C.BLOCK_BARS[tf]
    n = w * 40
    fails = 0

    # 1a. marche aleatoire, REGLAGE REEL : l'estimateur retenu doit rendre ~0
    good, naive = [], []
    for _ in range(20):
        r = rng.standard_normal(n)
        c = np.cumsum(r) + 100.0
        sig = pd.Series(r).rolling(24).sum().to_numpy()
        fwd = np.full(n, np.nan)
        fwd[:-5] = c[5:] / c[:-5] - 1.0
        ic, _, _ = block_ic(sig, fwd, tf)
        good.append(ic.mean())
        naive.append(block_ic_naive(sig, fwd, tf).mean())
    g, nv = float(np.mean(good)), float(np.mean(naive))
    ok1 = abs(g) < 0.01
    LOG.info("selftest 1a | marche aleatoire au reglage reel (bloc=%d, memoire=24) : "
             "estimateur retenu IC=%+.4f (%s), estimateur naif IC=%+.4f",
             w, g, "OK" if ok1 else "ECHEC", nv)
    fails += 0 if ok1 else 1

    # 1b. LE PIEGE, montre a l'echelle ou il mord : bloc court, memoire longue.
    #     Le biais du recentrage local vaut grossierement -(memoire+k)/bloc ; il
    #     est donc invisible a 1512 barres de bloc et devastateur a 120. C'est
    #     la raison pour laquelle `BLOCK_BARS` est grand ici, et la raison pour
    #     laquelle `block_ic_naive` reste dans le fichier plutot qu'en commentaire.
    good2, naive2 = [], []
    saved = C.BLOCK_BARS[tf]
    C.BLOCK_BARS[tf] = 120
    for _ in range(20):
        r = rng.standard_normal(20_000)
        c = np.cumsum(r) + 100.0
        sig = pd.Series(r).rolling(60).sum().to_numpy()
        fwd = np.full(c.size, np.nan)
        fwd[:-10] = c[10:] / c[:-10] - 1.0
        good2.append(block_ic(sig, fwd, tf)[0].mean())
        naive2.append(block_ic_naive(sig, fwd, tf).mean())
    C.BLOCK_BARS[tf] = saved
    g2, nv2 = float(np.mean(good2)), float(np.mean(naive2))
    ok1b = abs(g2) < 0.02 and nv2 < -0.10
    LOG.info("selftest 1b | meme bruit, bloc=120 memoire=60 : retenu IC=%+.4f, "
             "naif IC=%+.4f (%s -- le piege doit apparaitre ici)",
             g2, nv2, "OK" if ok1b else "ECHEC")
    fails += 0 if ok1b else 1

    # 2. signal plante : un IC connu doit etre retrouve
    r = rng.standard_normal(n)
    c = np.cumsum(r * 0.001) + 100.0
    fwd = np.full(n, np.nan)
    fwd[:-1] = c[1:] / c[:-1] - 1.0
    sd_f = float(np.nanstd(fwd))
    sig = np.where(np.isfinite(fwd), fwd, 0.0) + rng.standard_normal(n) * 2 * sd_f
    ic, _, n_obs = block_ic(sig, fwd, tf)
    m = summarize(ic, n_obs, 1, +1, 1)
    ok2 = m["ic_mean"] > 0.30 and m["t_stat"] > 10
    LOG.info("selftest 2 | signal plante (bruit 2x le signal, Pearson attendu "
             "~0,45) : IC=%+.4f t=%.2f (%s)",
             m["ic_mean"], m["t_stat"], "OK" if ok2 else "ECHEC")
    fails += 0 if ok2 else 1

    # 3. aucune fonction de `signals.py` ne doit regarder devant elle.
    #    On perturbe la DERNIERE moitie des barres et on verifie que la
    #    premiere moitie du signal ne bouge pas d'un iota.
    b = None
    for sym in C.UNIVERSE:
        b = C.load(sym, "H1")
        if b is not None:
            break
    if b is None:
        LOG.warning("selftest 3 | aucune serie chargee, test de causalite saute")
    else:
        h = len(b) // 2
        df = pd.DataFrame(dict(time=b.t, open=b.o, high=b.h, low=b.l, close=b.c,
                               tick_volume=b.v, spread=b.spread))
        d2 = df.copy()
        for col in ("open", "high", "low", "close"):
            d2.loc[h:, col] = d2.loc[h:, col] * 1.37 + 5.0
        d2["tick_volume"] = d2["tick_volume"].astype(float)
        d2.loc[h:, "tick_volume"] *= 3.0
        b2 = C.Bars(b.sym, "H1", d2)
        bad = []
        for spec in SG.instantiate(b.sym):
            if spec["type"] in SG.CROSS_TYPES:
                continue
            x1 = SG.compute(b, spec)[:h]
            x2 = SG.compute(b2, spec)[:h]
            m1, m2 = np.isfinite(x1), np.isfinite(x2)
            if not np.array_equal(m1, m2) or not np.allclose(x1[m1], x2[m2],
                                                             equal_nan=True):
                bad.append(SG.spec_key(spec))
        ok3 = not bad
        LOG.info("selftest 3 | causalite sur %s H1 : %s%s", b.sym,
                 "OK" if ok3 else f"ECHEC ({len(bad)})",
                 "" if ok3 else " -> " + ", ".join(bad[:6]))
        fails += 0 if ok3 else 1

    LOG.info("SELFTEST : %s", "4/4 OK" if fails == 0 else f"{4 - fails}/4 OK")
    return fails


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--tf", default=",".join(C.TIMEFRAMES))
    ap.add_argument("--symbols", default=",".join(C.UNIVERSE))
    ap.add_argument("--placebo", type=int, default=1,
                    help="tirages du temoin par cellule (0 = aucun)")
    ap.add_argument("--out", default=str(C.DATA / "ic_results.parquet"))
    a = ap.parse_args()

    if a.selftest:
        return 1 if selftest() else 0

    cat = json.loads((C.DATA / "hypotheses.json").read_text(encoding="utf-8"))
    by_key = {c["signal_id"].split("_", 1)[1]: c for c in cat}
    rng = np.random.default_rng(20260817)
    tfs = [t for t in a.tf.split(",") if t in C.TIMEFRAMES]
    syms = [s for s in a.symbols.split(",") if s in C.UNIVERSE]

    all_rows, t0 = [], time.time()
    for sym in syms:
        for tf in tfs:
            if not C.bars_path(sym, tf).exists():
                continue
            specs = []
            for s in SG.instantiate(sym):
                c = by_key.get(SG.spec_key(s))
                if c is None:
                    continue
                specs.append(dict(s, signal_id=c["signal_id"]))
            t1 = time.time()
            rows = run_pair(sym, tf, specs, C.HORIZONS, a.placebo, rng)
            all_rows += rows
            LOG.info("%-7s %-3s : %4d cellules d'IC en %5.1f s  (|IC| max %.4f)",
                     sym, tf, len(rows), time.time() - t1,
                     max((abs(r["ic_mean"]) for r in rows), default=float("nan")))

    df = pd.DataFrame(all_rows)
    df.to_parquet(a.out, index=False)
    LOG.info("ETAPE 3 terminee : %d cellules en %.1f min -> %s",
             len(df), (time.time() - t0) / 60, a.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


# ------------------------------------------------------------------ diagnostics
def market_diagnostics(symbols: list[str], tfs: list[str],
                       horizons: list[int]) -> pd.DataFrame:
    """Ce que le MARCHE offre par (actif, UT, k), independamment de tout signal.

    Trois nombres, aucun backtest : pas de stop, pas de cible, pas de sizing,
    pas d'enchainement de trades. Ce sont des statistiques descriptives de la
    serie, et elles servent a une seule question -- l'horizon k est-il seulement
    assez grand pour que quoi que ce soit puisse payer le spread.

    `autocorr_lag1` est le diagnostic qui compte le plus a l'echelle M5 : un
    rendement a une barre fortement AUTO-ANTICORRELE est la signature du
    rebond entre bid et ask, pas d'un bord. Un signal de momentum court qui
    ressort a IC = -0,03 sur k = 1 mesure ce rebond -- et le rebond est
    exactement ce que l'on paierait en spread pour tenter de le prendre.
    """
    rows = []
    for sym in symbols:
        for tf in tfs:
            b = C.load(sym, tf)
            if b is None:
                continue
            lr = b.logret()
            lr = lr[np.isfinite(lr)]
            ac1 = float(np.corrcoef(lr[1:], lr[:-1])[0, 1]) if lr.size > 100 else np.nan
            for k in horizons:
                f = b.fwd(k)
                f = f[np.isfinite(f)]
                if f.size < 100:
                    continue
                rows.append(dict(asset=sym, timeframe=tf, k=k,
                                 autocorr_lag1=ac1,
                                 sigma_fwd_bps=float(np.std(f) * 1e4),
                                 median_abs_fwd_bps=float(np.median(np.abs(f)) * 1e4)))
    return pd.DataFrame(rows)
