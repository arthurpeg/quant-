"""ETAPE 16 -- la bonne metrique pour un book de CHALLENGE : le temps espere
jusqu'au financement, re-challenges compris.

    python research/scripts/16_temps_jusqu_au_funded.py

POURQUOI CE FICHIER EXISTE. J'ai compare les dosages du book AGRESSIF sur le
%/an a risque egal et sur la RUINE FUNDED. Les deux sont hors sujet ici, et
l'utilisateur l'a releve :

  * AGRESSIF est le book de **CHALLENGE**. Le plan du depot est
    AGRESSIF@1,00 % -> FUNDED@0,50 % a la validation (`system.md`, log du
    2026-08-08 : *"Staying aggressive after funding is the trap"*). La ruine
    d'AGRESSIF en phase funded mesure donc un scenario que le plan interdit.
  * Le %/an a risque egal dimensionne au plafond **-10 % statique**, qui est la
    contrainte du compte FUNDED. Pendant le challenge, ce qui mord est le couple
    (cible +15 %, DD -10 %) et surtout le TEMPS.

CE QUI DECIDE VRAIMENT, ALORS. Un challenge rate coute deux choses : les frais
d'une nouvelle tentative, et le temps deja passe a echouer. La grandeur qui
integre les deux est :

    E[temps jusqu'au financement] = E[temps d'un echec] x (1-p)/p
                                    + E[temps d'une reussite]

ou p = P(valider). Une configuration qui valide 1,4 point moins souvent mais
0,4 mois plus vite peut donc etre MEILLEURE ou PIRE selon la duree des echecs --
et c'est une mesure, pas une intuition. On rend aussi E[tentatives payees].

TROIS PRECAUTIONS.

* Le tirage est celui du depot (`monte_carlo_static.simulate` -- block-bootstrap
  14 jours, 40 000 chemins, meme graine), mais il ne conserve pas la date des
  ECHECS. On le re-instrumente ici pour recuperer les deux distributions, en
  gardant EXACTEMENT la meme regle de challenge (cible 0,15/r, DD 0,10/r, perte
  du jour 0,05/r) et le meme generateur.
* Les chemins font 730 jours : un challenge qui n'a ni valide ni echoue au bout
  de deux ans est compte comme un echec de duree 730 j. C'est conservateur et
  ca concerne une part infime des tirages.
* Les deux candidates restent IN-SAMPLE. Le classement entre dosages est
  robuste (c'est le meme jeu de trades qui est dose differemment), le NIVEAU ne
  l'est pas.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
import common as C

from edgelab.reports.books_report import SLEEVES, _ftmo_costs, load_sleeves


def _load(name, fname):
    sp = importlib.util.spec_from_file_location(
        name, Path(__file__).resolve().parent / fname)
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


S14 = _load("swaptest", "14_swap_test_vs_book.py")
LOG = C.get_logger("16_temps")

W_NOW = dict(b1=1.0, b2=1.0, b3=0.5, b4=1.0, HMASTO=0.5, TLF=0.5)
MONTH = 30.44
RISKS = (0.0075, 0.01, 0.0125, 0.015)


def challenge_paths(R: np.ndarray, risk: float, N: int = 40000,
                    B: int = 14, seed: int = 7, L: int = 730) -> dict:
    """Meme regle et meme tirage que `monte_carlo_static`, mais on garde AUSSI
    la date des echecs -- c'est elle qui manque pour chiffrer un re-challenge."""
    rng = np.random.default_rng(seed)

    def path(n):
        o = []
        while len(o) < n:
            st = rng.integers(0, len(R) - B)
            o.extend(R[st:st + B])
        return np.array(o[:n])

    T, DD, DAY = 0.15 / risk, 0.10 / risk, 0.05 / risk
    t_pass, t_fail = [], []
    for _ in range(N):
        p = path(L)
        e = 0.0
        done = False
        for t, x in enumerate(p):
            if x <= -DAY:
                t_fail.append(t + 1)
                done = True
                break
            e += x
            if e <= -DD:
                t_fail.append(t + 1)
                done = True
                break
            if e >= T:
                t_pass.append(t + 1)
                done = True
                break
        if not done:
            t_fail.append(L)            # ni valide ni echoue en 2 ans -> echec
    tp = np.array(t_pass, dtype=float)
    tf = np.array(t_fail, dtype=float)
    p_pass = tp.size / N
    e_fail = float(tf.mean()) if tf.size else 0.0
    e_pass = float(tp.mean()) if tp.size else np.nan
    # E[temps jusqu'au financement] : (1-p)/p echecs en moyenne, puis une reussite
    e_total = (1 - p_pass) / p_pass * e_fail + e_pass if p_pass > 0 else np.inf
    return dict(p_pass=p_pass, n_pass=tp.size,
                med_pass=float(np.median(tp)) if tp.size else np.nan,
                mean_pass=e_pass, mean_fail=e_fail,
                med_fail=float(np.median(tf)) if tf.size else np.nan,
                e_attempts=1.0 / p_pass if p_pass > 0 else np.inf,
                e_fees=(1 - p_pass) / p_pass if p_pass > 0 else np.inf,
                e_total_days=e_total)


def main() -> int:
    M, _a, _b = load_sleeves()
    cst = _ftmo_costs(M.index)
    net = M.copy()
    for k, c in cst.items():
        if k in net.columns:
            net[k] = net[k] - c.reindex(net.index).fillna(0.0)
    cands = {n: S14.cand_series(s) for n, s in S14.CANDIDATES.items()}
    start = max(min(v[v != 0].index.min() for v in cands.values()), net.index.min())
    idx = net.index[net.index >= start]
    net = net.loc[idx]
    SK = cands["skew US30"].reindex(idx).fillna(0.0)
    GE = cands["vwap_z GER40"].reindex(idx).fillna(0.0)

    def mix(w):
        return pd.Series(net[SLEEVES].to_numpy() @ np.array([w.get(s, 0.0)
                                                             for s in SLEEVES]),
                         index=idx)

    A = mix(W_NOW)
    A3 = mix(dict(W_NOW, b3=0.0))
    books = {
        "A (actuel, b3@0,5R)": A,
        "A sans b3": A3,
        "A sans b3 + les 2 @0,5R": A3 + 0.5 * (SK + GE),
        "A sans b3 + les 2 @1R": A3 + SK + GE,
    }

    LOG.info("=" * 108)
    LOG.info("TEMPS ESPERE JUSQU'AU FINANCEMENT, re-challenges compris")
    LOG.info("AGRESSIF est le book de CHALLENGE : la ruine funded ne s'y applique "
             "pas (le plan bascule sur FUNDED a la validation).")

    for risk in RISKS:
        LOG.info("-" * 108)
        LOG.info("RISQUE %.2f %%/trade", 100 * risk)
        LOG.info("   %-26s %9s %9s %9s %10s %9s %12s", "configuration",
                 "P(valider)", "t reussi", "t echoue", "tentatives",
                 "frais payes", "E[temps]")
        best = None
        for n, x in books.items():
            r = challenge_paths(x.to_numpy(), risk)
            if best is None or r["e_total_days"] < best[1]:
                best = (n, r["e_total_days"])
            LOG.info("   %-26s %8.1f %% %6.1f mois %6.1f mois %9.2f %9.2f %8.1f mois",
                     n, 100 * r["p_pass"], r["mean_pass"] / MONTH,
                     r["mean_fail"] / MONTH, r["e_attempts"], r["e_fees"],
                     r["e_total_days"] / MONTH)
        LOG.info("   -> le plus rapide jusqu'au financement : **%s** (%.1f mois)",
                 best[0], best[1] / MONTH)

    LOG.info("=" * 108)
    LOG.info("LECTURE : un dosage plus fort raccourcit la reussite ET raccourcit "
             "l'echec (on casse plus vite), donc son cout n'est pas le temps mais "
             "les FRAIS de re-challenge. C'est le nombre de tentatives payees qui "
             "arbitre, pas la duree.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
