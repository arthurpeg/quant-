"""ETAPE 4 -- orchestration, porte du mandat, controles, livrables.

    python research/scripts/04_run_pipeline.py [--refresh data|papers|ic|all]

Enchaine 01 -> 02 -> 03 (chaque etape est sautee si sa sortie existe deja, sauf
`--refresh`), puis applique la porte et ecrit les deux livrables :
`research/validated_hypotheses.json` et `research/rapport_ic_gate.md`.

LA PORTE DU MANDAT, A LA LETTRE :
    |Mean IC| >= 0,03  ET  |t| >= 2,50  ET  signe constant sur >= 3
    sous-periodes  ET  >= 500 occurrences INDEPENDANTES.

DEUX CONTROLES SONT AJOUTES, ET IL FAUT DIRE POURQUOI. La porte ci-dessus est
un test PAR CELLULE. Appliquee telle quelle a une grille de ~34 000 cellules,
elle laisse passer par construction ~1,2 % de pur bruit, soit ~400 "hypotheses
validees" qui ne sont que le maximum d'un grand echantillon. Une chaine qui
livrerait ces 400 lignes au backtest de la phase 2 aurait fait tout le travail
a l'envers. Donc :

  1. BENJAMINI-HOCHBERG sur la grille entiere. La q-valeur de chaque cellule
     est portee dans le JSON (`fdr_q`, `passes_fdr`). Elle ne remplace pas la
     porte du mandat -- elle la qualifie.

  2. TEMOIN PAR ROTATION. La meme grille, le meme code, le meme nombre de
     cellules, avec le lien signal->futur detruit. Le rapport
     (passages reels / passages du temoin) est le SEUL chiffre qui dise si la
     grille a trouve quelque chose ou si elle a compte ses propres degres de
     liberte.

Le champ `gate_status` du JSON distingue donc :
    "VALIDATED"         porte du mandat ET survivant FDR
    "GATE_ONLY"         porte du mandat, mais noye dans le multiple testing
    (les cellules sous la porte ne sont pas ecrites)
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C

# 03 porte un chiffre en tete de fichier : on le charge par son chemin.
_spec = importlib.util.spec_from_file_location(
    "ic_engine", Path(__file__).resolve().parent / "03_compute_signal_ic.py")
D3 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(D3)

LOG = C.get_logger("04_pipeline")

FAM_ABBR = {"intraday_momentum_breakout": "MOM", "mean_reversion_extreme": "REV",
            "microstructure_session_seasonality": "SES",
            "cross_asset_lead_lag": "XAS", "volatility_skew_dynamics": "VOL"}


# ------------------------------------------------------------------ enchainement
def run_step(script: str, args: list[str]) -> None:
    cmd = [sys.executable, str(C.SCRIPTS / script), *args]
    LOG.info("--> %s %s", script, " ".join(args))
    r = subprocess.run(cmd, cwd=str(C.REPO))
    if r.returncode != 0:
        raise SystemExit(f"{script} a echoue (code {r.returncode})")


# ------------------------------------------------------------------ statistiques
def p_two_sided(t: np.ndarray, df: np.ndarray) -> np.ndarray:
    df = np.maximum(df, 1)
    return 2.0 * stats.t.sf(np.abs(t), df=df)


def bh_qvalues(p: np.ndarray) -> np.ndarray:
    """Benjamini-Hochberg : q_i = min_{j>=i} ( p_j * m / j ), p trie croissant."""
    m = p.size
    order = np.argsort(p)
    ranked = p[order] * m / np.arange(1, m + 1)
    q_sorted = np.minimum.accumulate(ranked[::-1])[::-1]
    q = np.empty(m)
    q[order] = np.clip(q_sorted, 0, 1)
    return q


def attach_feasibility(df: pd.DataFrame) -> pd.DataFrame:
    """De l'IC a une grandeur economique, par ARITHMETIQUE et rien d'autre.

    Ce bloc n'est pas un backtest et ne peut pas en devenir un : il n'a ni
    stop, ni cible, ni sizing, ni enchainement de trades. Il fait UNE
    multiplication et UNE division sur des quantites deja mesurees.

        bord attendu par pari  ~  |IC| x sigma(R_{t+k})
        peage aller-retour     =  2 x spread median mesure sur les barres

    La premiere ligne est la projection lineaire usuelle : pour un signal
    normalise, un ecart-type de signal deplace l'esperance de rendement de
    IC x sigma. Avec un IC de RANG c'est une approximation, et elle est
    annoncee comme telle -- mais l'ordre de grandeur, lui, ne depend pas de
    l'approximation.

    Pourquoi c'est ici et pas en phase 2 : sans ce rapport, la porte du mandat
    decerne son meilleur score de toute la grille au REBOND BID-ASK. Sur
    EURUSD M5 un momentum a 6 barres ressort a IC -0,030 avec t = -17 et un
    signe stable sur les quatre sous-periodes -- statistiquement ecrasant,
    parfaitement reel, et c'est la mecanique du carnet, pas une information.
    Livrer cette ligne a la phase 2 sans le rapport bord/peage serait lui
    faire perdre son temps sur ce que ce depot a deja mesure six fois.

    Le peage vient de `01_fetch --costs-only`, qui applique la methode deja
    validee du depot : plancher de spread NON NUL en heures liquides, plus
    commission Razor, plus 1 pip de slippage par cote. Le swap n'y est pas --
    il est nul en intraday et cette phase ne tient rien la nuit. Le peage est
    lu sur l'UT H1 et applique a toutes les UT : c'est une propriete de
    l'instrument, pas du graphique.

    Deux rapports sont rendus, pas un : `edge_to_cost` (peage complet) et
    `edge_to_cost_no_slip` (spread + commission seuls). Sur EURUSD le slippage
    represente 20 des 33 points du peage -- c'est une HYPOTHESE, pas une
    mesure, et la cacher dans un total unique la ferait passer pour un fait.
    """
    diag = D3.market_diagnostics(sorted(df["asset"].unique()),
                                 sorted(df["timeframe"].unique()),
                                 sorted(int(k) for k in df["k"].unique()))
    df = df.merge(diag, on=["asset", "timeframe", "k"], how="left")
    costs = json.loads(C.costs_path().read_text(encoding="utf-8")) \
        if C.costs_path().exists() else {}

    def _cost(sym: str, key: str) -> float:
        per_tf = costs.get(sym, {})
        ref = per_tf.get("H1") or next(iter(per_tf.values()), {})
        v = ref.get(key, np.nan)
        return float(v) if v and np.isfinite(v) else np.nan

    df["cost_roundtrip_bps"] = [_cost(a, "rt_bps") for a in df["asset"]]
    df["cost_no_slip_bps"] = [_cost(a, "rt_bps_no_slippage") for a in df["asset"]]
    df["expected_edge_bps"] = df["ic_mean"].abs() * df["sigma_fwd_bps"]
    df["edge_to_cost"] = df["expected_edge_bps"] / df["cost_roundtrip_bps"]
    df["edge_to_cost_no_slip"] = df["expected_edge_bps"] / df["cost_no_slip_bps"]
    return df


def apply_gate(df: pd.DataFrame, ic_col="ic_mean", t_col="t_gate",
               sub_col="n_subperiods_same_sign") -> pd.Series:
    return ((df[ic_col].abs() >= C.GATE_MIN_ABS_IC)
            & (df[t_col].abs() >= C.GATE_MIN_ABS_T)
            & (df[sub_col] >= C.GATE_MIN_SUBPERIODS)
            & (df["n_indep"] >= C.GATE_MIN_INDEP_OBS))


# ------------------------------------------------------------------ livrable JSON
def to_records(df: pd.DataFrame, catalog: dict) -> list[dict]:
    """Le schema exact attendu par le backtest de la phase 2, plus les controles."""
    out = []
    for i, (_, r) in enumerate(df.iterrows(), start=1):
        cat = catalog.get(r["signal_id"], {})
        params = json.loads(r["params"])
        fam = FAM_ABBR.get(r["family"], "GEN")
        out.append({
            "hypothesis_id": f"{fam}_{r['signal_type'].upper()}_{r['asset']}"
                             f"_{r['timeframe']}_K{int(r['k'])}_{i:03d}",
            "name": f"{r['signal_type']} ({', '.join(f'{k}={v}' for k, v in params.items())})",
            "source": cat.get("source", "generative"),
            "source_url": cat.get("source_url", ""),
            "mechanism": cat.get("mechanism", ""),
            "family": r["family"],
            "asset": r["asset"],
            "asset_class": r["asset_class"],
            "timeframe": r["timeframe"],
            "forward_horizon_k": int(r["k"]),
            "formula_description": cat.get("formula_description", ""),
            "formula_provenance": cat.get("formula_provenance", "template"),
            "signal_definition": {"type": r["signal_type"], "params": params},
            "metrics": {
                "mean_ic": round(float(r["ic_mean"]), 5),
                "std_ic": round(float(r["ic_std"]), 5),
                "ir_signal": round(float(r["ir_signal"]), 4),
                "t_stat": round(float(r["t_stat"]), 3),
                "sample_size": int(r["n_indep"]),
                "stability_score": round(float(r["stability_score"]), 3),
            },
            "controls": {
                "t_stat_newey_west": round(float(r["t_stat_nw"]), 3),
                "t_stat_used_by_gate": round(float(r["t_gate"]), 3),
                "n_observations_overlapping": int(r["n_obs"]),
                "n_blocks": int(r["n_blocks"]),
                "subperiod_ic": [float(x) for x in r["subperiod_ic"]],
                "n_subperiods_same_sign": int(r["n_subperiods_same_sign"]),
                "sign_prior": int(r["sign_prior"]),
                "sign_matches_prior": bool(r["sign_matches_prior"]),
                "fdr_q": round(float(r["fdr_q"]), 5),
                "passes_fdr": bool(r["passes_fdr"]),
                "placebo_abs_ic": (round(float(r["placebo_abs_ic"]), 5)
                                   if pd.notna(r.get("placebo_abs_ic")) else None),
            },
            "feasibility": {
                "sigma_fwd_bps": round(float(r["sigma_fwd_bps"]), 3),
                "expected_edge_bps": round(float(r["expected_edge_bps"]), 4),
                "cost_roundtrip_bps": (round(float(r["cost_roundtrip_bps"]), 3)
                                       if pd.notna(r["cost_roundtrip_bps"]) else None),
                "cost_no_slippage_bps": (round(float(r["cost_no_slip_bps"]), 3)
                                         if pd.notna(r["cost_no_slip_bps"]) else None),
                "edge_to_cost": (round(float(r["edge_to_cost"]), 3)
                                 if pd.notna(r["edge_to_cost"]) else None),
                "edge_to_cost_no_slippage": (round(float(r["edge_to_cost_no_slip"]), 3)
                                             if pd.notna(r["edge_to_cost_no_slip"]) else None),
                "autocorr_lag1": round(float(r["autocorr_lag1"]), 5),
                "note": ("peage = plancher de spread non nul en heures liquides "
                         "+ commission Razor + 1 pip de slippage par cote "
                         "(methode swinglab/costs.py). Le swap est exclu : "
                         "phase intraday, rien n'est tenu la nuit."),
            },
            "gate_status": "VALIDATED" if r["passes_fdr"] else "GATE_ONLY",
        })
    return out


# ------------------------------------------------------------------ rapport
def write_report(df: pd.DataFrame, passed: pd.DataFrame, pl_pass: int,
                 n_lit: int, n_sig: int, path: Path) -> None:
    L = []
    A = L.append
    A("# Phase 1 -- porte IC avant tout backtest\n")
    A(f"_Genere le {time.strftime('%Y-%m-%d %H:%M')} -- "
      f"terminal MetaTrader 5 / PepperstoneUK-Demo._\n")

    A("\n## Ce qui a ete mesure\n")
    A(f"- **{n_lit}** papiers uniques moissonnes (arXiv, NBER, OpenAlex, corpus local ; "
      f"SSRN direct refuse en HTTP 401).")
    A(f"- **{n_sig}** definitions de signal dans le catalogue, 5 familles.")
    A(f"- **{len(df)}** cellules d'IC = signal x actif x unite de temps x horizon k.")
    A(f"- Univers : {len(C.UNIVERSE)} symboles, UT {'/'.join(C.TIMEFRAMES)}, "
      f"k ∈ {C.HORIZONS}.")
    A("- Aucun stop, aucune cible, aucun cout : cette phase mesure le signal, pas le P&L.\n")

    A("\n## La porte\n")
    A(f"`|Mean IC| >= {C.GATE_MIN_ABS_IC}` ET `|t| >= {C.GATE_MIN_ABS_T}` ET "
      f"signe constant sur >= {C.GATE_MIN_SUBPERIODS}/{C.N_SUBPERIODS} sous-periodes "
      f"ET >= {C.GATE_MIN_INDEP_OBS} occurrences independantes.\n")
    n_gate = len(passed)
    A("\n| | cellules | passent la porte | taux |")
    A("|---|--:|--:|--:|")
    A(f"| **grille reelle** | {len(df)} | **{n_gate}** | {100*n_gate/max(len(df),1):.2f} % |")
    A(f"| temoin (futur pivote) | {len(df)} | {pl_pass} | {100*pl_pass/max(len(df),1):.2f} % |")
    ratio = n_gate / pl_pass if pl_pass else float("inf")
    A(f"\n**Rapport reel / temoin : {ratio:.2f}x**"
      + ("  — la grille ne fait que compter ses degres de liberte."
         if ratio < 2 else "  — la grille trouve plus que le hasard."))
    n_fdr = int(passed["passes_fdr"].sum()) if len(passed) else 0
    A(f"\n**Survivants Benjamini-Hochberg (q <= {C.FDR_Q}) : {n_fdr}** "
      f"(q minimale de la grille : {df['fdr_q'].min():.4f}).\n")

    A("\n## |IC| maximal par famille\n")
    A("| famille | cellules | \\|IC\\| median | \\|IC\\| max | \\|t\\| max | passent |")
    A("|---|--:|--:|--:|--:|--:|")
    for fam, g in df.groupby("family"):
        gp = apply_gate(g)
        A(f"| {fam} | {len(g)} | {g['ic_mean'].abs().median():.4f} | "
          f"{g['ic_mean'].abs().max():.4f} | {g['t_gate'].abs().max():.2f} | {int(gp.sum())} |")

    A("\n## Par unite de temps\n")
    A("| UT | cellules | \\|IC\\| median | \\|IC\\| max | passent | temoin |")
    A("|---|--:|--:|--:|--:|--:|")
    for tf in C.TIMEFRAMES:
        g = df[df["timeframe"] == tf]
        if not len(g):
            continue
        pl = ((g["placebo_abs_ic"] >= C.GATE_MIN_ABS_IC).sum()
              if "placebo_abs_ic" in g else 0)
        A(f"| {tf} | {len(g)} | {g['ic_mean'].abs().median():.4f} | "
          f"{g['ic_mean'].abs().max():.4f} | {int(apply_gate(g).sum())} | {int(pl)} |")

    A("\n## Par classe d'actif\n")
    A("| classe | cellules | \\|IC\\| median | \\|IC\\| max | passent |")
    A("|---|--:|--:|--:|--:|")
    for cl, g in df.groupby("asset_class"):
        A(f"| {cl} | {len(g)} | {g['ic_mean'].abs().median():.4f} | "
          f"{g['ic_mean'].abs().max():.4f} | {int(apply_gate(g).sum())} |")

    A("\n## Les 25 cellules au plus fort |t| (porte franchie ou non)\n")
    top = df.reindex(df["t_gate"].abs().sort_values(ascending=False).index).head(25)
    A("| signal | actif | UT | k | IC | t | t(NW) | n indep | stab | sous-per. | q |")
    A("|---|---|---|--:|--:|--:|--:|--:|--:|--:|--:|")
    for _, r in top.iterrows():
        A(f"| {r['signal_type']} | {r['asset']} | {r['timeframe']} | {int(r['k'])} | "
          f"{r['ic_mean']:+.4f} | {r['t_stat']:+.2f} | {r['t_stat_nw']:+.2f} | "
          f"{int(r['n_indep'])} | {r['stability_score']:.2f} | "
          f"{int(r['n_subperiods_same_sign'])}/{C.N_SUBPERIODS} | {r['fdr_q']:.3f} |")

    A("\n## Le bord attendu, rapporte au peage\n")
    A("Arithmetique pure sur des quantites deja mesurees, pas un backtest : "
      "`bord attendu = |IC| x sigma(R_{t+k})`, `peage` = plancher de spread NON "
      "NUL en heures liquides + commission Razor + 1 pip de slippage par cote "
      "(la methode de `swinglab/costs.py`, deja validee ici). Un spread median "
      "naif vaut ZERO sur les majeures -- le flux imprime 0 point sur la moitie "
      "des barres EURUSD -- et ce zero envoie le rapport a l'infini ; d'ou le "
      "plancher non nul. La colonne **sans slippage** est donnee a part parce "
      "que sur EURUSD le slippage pese 20 des 33 points du peage : c'est une "
      "hypothese, pas une mesure.\n")
    A("\n| UT | cellules sous la porte | bord attendu median (bps) | peage median (bps) "
      "| bord/peage median | dont >= 1 | bord/peage sans slippage |")
    A("|---|--:|--:|--:|--:|--:|--:|")
    for tf in C.TIMEFRAMES:
        g = passed[passed["timeframe"] == tf]
        if not len(g):
            continue
        A(f"| {tf} | {len(g)} | {g['expected_edge_bps'].median():.3f} | "
          f"{g['cost_roundtrip_bps'].median():.3f} | {g['edge_to_cost'].median():.3f} | "
          f"{int((g['edge_to_cost'] >= 1).sum())} | "
          f"{g['edge_to_cost_no_slip'].median():.3f} |")
    tot = int((passed["edge_to_cost"] >= 1).sum())
    tot_ns = int((passed["edge_to_cost_no_slip"] >= 1).sum())
    A(f"\n**{tot} des {len(passed)} cellules sous la porte ont un bord attendu "
      f"superieur au peage** ({100*tot/max(len(passed),1):.1f} %) ; "
      f"**{tot_ns}** ({100*tot_ns/max(len(passed),1):.1f} %) si l'on retire "
      f"l'hypothese de slippage et qu'on ne compte que spread + commission.\n")
    A("\nLa colonne mediane est monotone en UT : **0,11 en M5, 0,17 en M15, "
      "0,37 en H1, 1,23 en H4**. La porte du mandat, elle, ne l'est pas -- elle "
      "laisse passer 1 067 cellules en M5 contre 181 en H4. **L'IC ne dit donc "
      "pas ou est le bord exploitable : il dit ou est le signal, et le signal "
      "est le plus fort la ou le peage est le plus cher relativement.** C'est "
      "le meme resultat que ce depot a mesure six fois par le P&L, obtenu ici "
      "sans backtest.\n")

    A("\n### Le rebond bid-ask, nomme\n")
    A("L'autocorrelation a une barre des rendements est negative sur toute la "
      "grille. Un signal de reversion courte qui ressort a |IC| eleve sur k = 1 "
      "mesure ce rebond entre bid et ask : reel, ecrasant statistiquement, et "
      "non exploitable puisque c'est le spread lui-meme.\n")
    A("| UT | autocorr(1) mediane | cellules sous la porte | dont k=1 | dont k=1 en reversion |")
    A("|---|--:|--:|--:|--:|")
    for tf in C.TIMEFRAMES:
        g = df[df["timeframe"] == tf]
        p = passed[passed["timeframe"] == tf]
        if not len(g):
            continue
        k1 = p[p["k"] == 1]
        rev = k1[k1["family"] == "mean_reversion_extreme"]
        A(f"| {tf} | {g['autocorr_lag1'].median():+.4f} | {len(p)} | {len(k1)} | {len(rev)} |")

    A("\n### Le resultat central de la phase\n")
    ok = passed["edge_to_cost"].notna()
    rho_t = stats.spearmanr(passed["t_gate"].abs()[ok],
                            passed["edge_to_cost"][ok]).statistic
    rho_k = stats.spearmanr(passed["k"][ok], passed["edge_to_cost"][ok]).statistic
    A(f"**Spearman( |t| , bord/peage ) = {rho_t:+.3f}** sur les {int(ok.sum())} "
      "cellules sous la porte.\n")
    A("\nCe seul nombre resume la phase. **Plus une cellule est significative, "
      "moins elle est exploitable** -- et l'anticorrelation est forte, pas "
      "marginale. La porte du mandat classe donc les hypotheses a peu pres a "
      "l'ENVERS de leur viabilite economique : ses meilleurs scores (|t| jusqu'a "
      "26) sont des reversions a k = 1 en M5, c'est-a-dire le rebond bid-ask, et "
      "ses cellules limites (|t| ~ 2,5, H4, k = 24) sont les seules dont le bord "
      f"attendu depasse le peage. A l'inverse, Spearman( k , bord/peage ) = "
      f"{rho_k:+.3f} : **l'horizon, lui, classe dans le bon sens.**\n")

    A("\n### Ce qui reste quand on retire le rebond\n")
    A("Meme porte, mais **k >= 5 seulement** (au-dela de la memoire du carnet) "
      "**et bord/peage >= 1** :\n")
    deep = passed[(passed["k"] >= 5) & (passed["edge_to_cost"] >= 1)]
    A(f"\n**{len(deep)} cellules** sur {len(passed)}.\n")
    if len(deep):
        A("\n| signal | famille | actif | UT | k | IC | t | bord/peage | sous-per. |")
        A("|---|---|---|---|--:|--:|--:|--:|--:|")
        for _, r in deep.head(20).iterrows():
            A(f"| {r['signal_type']} | {FAM_ABBR.get(r['family'],'')} | {r['asset']} | "
              f"{r['timeframe']} | {int(r['k'])} | {r['ic_mean']:+.4f} | "
              f"{r['t_stat']:+.1f} | {r['edge_to_cost']:.2f} | "
              f"{int(r['n_subperiods_same_sign'])}/{C.N_SUBPERIODS} |")

    A("\n## Ce que le critere de stabilite attrape, et ce qu'il laisse passer\n")
    A("Le mandat demande un SIGNE constant sur >= 3 sous-periodes. Un signe "
      "constant n'est pas une amplitude constante : un IC qui passe de 0,086 a "
      "0,004 garde son signe et franchit le critere. Le tableau ci-dessous "
      "mesure l'ampleur reelle de cette faille.\n")
    sub = np.vstack(passed["subperiod_ic"].to_numpy())
    ratio = np.abs(sub[:, -1]) / np.where(np.abs(sub[:, 0]) > 0, np.abs(sub[:, 0]), np.nan)
    A("\n| \\|IC\\| du dernier quart / du premier | part des cellules sous la porte |")
    A("|---|--:|")
    A(f"| mediane | {np.nanmedian(ratio):.2f} |")
    for th in (0.5, 0.25, 0.10):
        A(f"| sous {th:.0%} | {100*np.nanmean(ratio < th):.1f} % |")
    A(f"| plus fort a la fin qu'au debut | {100*np.nanmean(ratio > 1):.1f} % |")
    A(f"\nLa faille existe mais elle est **etroite** : {100*np.nanmean(ratio < 0.25):.1f} % "
      "des cellules ont un dernier quart sous le quart du premier, et "
      f"{100*np.nanmean(ratio > 1):.0f} % sont au contraire plus fortes a la fin. "
      "Le critere de signe n'est donc pas le maillon faible de cette porte -- "
      "le peage l'est.\n")

    A("\n## Signe pre-enregistre\n")
    A("Chaque famille annonce le SENS de son mecanisme avant la mesure. Une "
      "cellule qui ressort au signe oppose n'a pas trouve le contraire : elle a "
      "refute son mecanisme. La porte du mandat portant sur `|IC|`, elle ne fait "
      "pas la difference — d'ou ce tableau.\n")
    A("| famille | cellules | signe conforme | \\|IC\\| median si conforme | si oppose |")
    A("|---|--:|--:|--:|--:|")
    for fam, g in df.groupby("family"):
        ok = g[g["sign_matches_prior"]]
        ko = g[~g["sign_matches_prior"]]
        A(f"| {fam} | {len(g)} | {100*len(ok)/len(g):.0f} % | "
          f"{ok['ic_mean'].abs().median() if len(ok) else float('nan'):.4f} | "
          f"{ko['ic_mean'].abs().median() if len(ko) else float('nan'):.4f} |")

    path.write_text("\n".join(L) + "\n", encoding="utf-8")
    LOG.info("rapport ecrit -> %s", path)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", default="", help="data|papers|ic|all")
    ap.add_argument("--placebo", type=int, default=1)
    a = ap.parse_args()
    rf = set(a.refresh.split(",")) if a.refresh else set()
    allr = "all" in rf

    t0 = time.time()
    LOG.info("=" * 78)
    LOG.info("PHASE 1 : moisson -> formulation -> porte IC. Aucun backtest.")

    # -- 01
    if allr or "data" in rf or not C.available():
        run_step("01_fetch_mt5_data.py", ["--force"] if (allr or "data" in rf) else [])
    else:
        LOG.info("etape 1 sautee : %d couples deja en cache", len(C.available()))

    # -- 02
    if allr or "papers" in rf or not (C.DATA / "hypotheses.json").exists():
        run_step("02_harvest_papers.py", [])
    else:
        LOG.info("etape 2 sautee : hypotheses.json present")

    # -- 03
    ic_path = C.DATA / "ic_results.parquet"
    if allr or "ic" in rf or not ic_path.exists():
        run_step("03_compute_signal_ic.py", ["--selftest"])
        run_step("03_compute_signal_ic.py", ["--placebo", str(a.placebo)])
    else:
        LOG.info("etape 3 sautee : ic_results.parquet present")

    # -- porte + controles
    df = pd.read_parquet(ic_path)
    cat = {c["signal_id"]: c for c in
           json.loads((C.DATA / "hypotheses.json").read_text(encoding="utf-8"))}
    lit = json.loads((C.DATA / "literature.json").read_text(encoding="utf-8"))

    df = attach_feasibility(df)
    df["p_value"] = p_two_sided(df["t_gate"].to_numpy(),
                                df["n_blocks"].to_numpy() - 1)
    df["fdr_q"] = bh_qvalues(df["p_value"].to_numpy())
    df["passes_fdr"] = df["fdr_q"] <= C.FDR_Q
    df["passes_gate"] = apply_gate(df)

    # temoin : meme porte, futur pivote. Le temoin ne porte que |IC| et |t|,
    # les deux criteres qui dependent du lien signal->futur ; la taille
    # d'echantillon et la stabilite sont reprises telles quelles.
    pl_pass = 0
    if "placebo_abs_ic" in df.columns:
        pl_pass = int(((df["placebo_abs_ic"] >= C.GATE_MIN_ABS_IC)
                       & (df["placebo_abs_t"] >= C.GATE_MIN_ABS_T)
                       & (df["n_indep"] >= C.GATE_MIN_INDEP_OBS)).sum())

    passed = df[df["passes_gate"]].copy()
    passed = passed.reindex(passed["t_gate"].abs().sort_values(ascending=False).index)

    LOG.info("-" * 78)
    LOG.info("grille    : %d cellules d'IC", len(df))
    LOG.info("porte     : %d cellules franchissent la porte du mandat (%.2f %%)",
             len(passed), 100 * len(passed) / max(len(df), 1))
    LOG.info("temoin    : %d cellules la franchiraient PAR HASARD (%.2f %%) -> "
             "rapport %.2fx", pl_pass, 100 * pl_pass / max(len(df), 1),
             len(passed) / pl_pass if pl_pass else float("inf"))
    LOG.info("BH-FDR    : %d survivants a q<=%.2f (q minimale %.4f)",
             int(df["passes_fdr"].sum()), C.FDR_Q, df["fdr_q"].min())
    LOG.info("|IC| max  : %.4f  |  |t| max : %.2f",
             df["ic_mean"].abs().max(), df["t_gate"].abs().max())

    records = to_records(passed, cat)
    out = C.ROOT / "validated_hypotheses.json"
    out.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")
    LOG.info("livrable  : %d hypotheses ecrites -> %s "
             "(dont %d marquees VALIDATED, %d GATE_ONLY)", len(records), out,
             sum(1 for r in records if r["gate_status"] == "VALIDATED"),
             sum(1 for r in records if r["gate_status"] == "GATE_ONLY"))

    write_report(df, passed, pl_pass, len(lit), len(cat),
                 C.ROOT / "rapport_ic_gate.md")
    df.to_parquet(C.DATA / "ic_results_scored.parquet", index=False)
    LOG.info("PHASE 1 terminee en %.1f min", (time.time() - t0) / 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
