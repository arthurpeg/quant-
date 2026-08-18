"""Self-contained HTML backtest report for the two named books, NET of FTMO cost.

    book AGRESSIF = b1 + b2 + b4 @1R + HMASTO@0.5R + TLF@0.5R   (live, SANS crypto)
                    ⚠️ b3 RETIRÉE le 2026-08-18 sur instruction utilisateur. Halvée
                    le 2026-08-10 (swap FTMO -30 %/an des DEUX côtés = 5.71 R/an
                    contre 5.72 de brut), puis retirée : mesurée sur 2018-07→2026-07
                    nette de frais elle rend +0.2 R/an pour 21.3 R de drawdown
                    (RoMaD 0.01, le plus bas des six sleeves). `crypto_symbols: []`
                    dans config_live.yaml — les magics 103/104 ne sont plus pilotés.
                    KAER@0.5R tenait ce créneau jusqu'au 2026-08-10 ; HMASTO (magic
                    108) l'a remplacée.
    book FUNDED   = b1 + b2 + b4 @1R + b3@0.5R + TLF@0.5R   (HMASTO retirée 2026-08-12,
                    elle a échoué son seul hors-échantillon : NAS100 juin→déc 2017,
                    n=118, t=−2.61, sur une fenêtre où la brique 1 tenait à +23.6 R/an)

KELT (BTCUSD H1 Keltner) was RETIRED from both books on 2026-08-09: FTMO charges -30 %/yr
on BOTH sides of BTCUSD, which takes the sleeve to +5.00 R/yr at t=0.87 and made removing
it a strict improvement on drawdown and ruin. See wiki/log.md 2026-08-09.

Everything is rebuilt from the canonical modules — `monte_carlo_static.build_daily_R`
for the four bricks on the LIVE cadence and `intraday.hma_stoch.run_hma_stoch` for the
remaining forward-test sleeve — so the report can never drift from what the runner
trades. No
scratchpad imports, no cached blobs.

    python -m edgelab.reports.books_report

Writes the same page to three places, matching `build_reports.py`'s convention:
    edgelab/reports/books_backtest.html          the source page
    edgelab/reports/_out/books_backtest.html     alongside the runner's outputs
    RAPPORT_books_agressif_funded.html           repo root — the one you open from the
                                                 VS Code explorer / "Reveal in File Explorer"

The page is one file: inline SVG charts, inline CSS/JS, no network. Both themes are
selected (OS preference + an explicit toggle).
"""
from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from edgelab.intraday.hma_stoch import run_hma_stoch
from edgelab.intraday.research_sleeves import run_research_sleeve
from edgelab.intraday.two_leg_fade import run_two_leg_fade
from edgelab.reports.ftmo_costs import daily_cost, trade_cost_R
from edgelab.reports.monte_carlo_static import build_daily_R, simulate

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
OUT = HERE / "books_backtest.html"
COPIES = (HERE / "_out" / "books_backtest.html",
          ROOT / "RAPPORT_books_agressif_funded.html")
RISKS = (0.005, 0.0075, 0.01)

BOOKS = {
    "AGRESSIF": dict(w=dict(b1=1.0, b2=1.0, b3=0.0, b4=1.0, HMASTO=0.5, TLF=0.5,
                             RVWAP=1.0, RSKEW=1.0),
                     use="CHALLENGE — 1.00 %/trade",
                     note="Déployé en live sur la démo : magics 101, 102, 105, 108 (HMASTO) et 109/110 (TLF). "
                          "⚠️ BRIQUE 3 RETIRÉE le 2026-08-18 (magics 103/104 non pilotés) : nette des coûts FTMO "
                          "sur 2018-07→2026-07 elle rendait +0.2 R/an pour 21.3 R de drawdown (RoMaD 0.01). "
                          "Halvée le 2026-08-10, retirée le 2026-08-18. KAER/106 et KELT/107 retirées. "
                          "➕ RVWAP (GER40 H1, magic 111) et RSKEW (US30 H4, magic 112) AJOUTÉES le "
                          "2026-08-18 à 1R chacune, sur instruction utilisateur. Parité backtest↔live "
                          "prouvée (0 écart sur 400 trades chacune). ⚠️ IN-SAMPLE, sans forward-test."),
    # 2026-08-12 : composition revue (voir wiki/log.md, deux entrées du jour). L'ancienne
    # — b1@1R sans HMASTO ni TLF — est DOMINÉE : elle rendait 11.78 % de retrait annuel
    # médian pour 0.97 % de ruine, quand b1@0.5 + HMASTO@0.5 + TLF@0.5 rend 23.98 % pour
    # 1.66 %, à drawdown annuel moyen quasi identique (4.73 % contre 4.55 % du capital).
    # Le levier est la BRIQUE 1. ⚠️ La première justification écrite ici — « les trois
    # sleeves intraday US cassent ENSEMBLE » — était une sur-lecture d'UN épisode
    # (2025 T2) et la mesure l'a RÉFUTÉE le même jour (`scratchpad/lib_tail.py`) : au pire
    # décile mensuel, b1-HMASTO, b1-TLF et HMASTO-TLF co-occurrent 0 % du temps
    # (multiplicateur 0.00) ; au pire quintile 1.50x/0.75x, p >= 0.175. Aucune dépendance
    # de queue détectable.
    # LA VRAIE RAISON est une PERSISTANCE, pas une synchronisation : sur les 30 épisodes
    # de drawdown >= 5 R du livre, b1 PERD DANS 28 et en porte 46.9 % de la profondeur en
    # médiane (HMASTO 39.3 %, TLF 19.3 %). Réduire b1 de moitié rend +1.40 R d'expected
    # shortfall et -2.77 R sur la moyenne des 5 pires drawdowns, pour -6.46 R/an : c'est
    # 0.429 R de drawdown évité par R/an sacrifié, contre 0.178 pour HMASTO et 0.126 pour
    # TLF — le levier le plus efficace du livre par un facteur 2.4.
    # COROLLAIRE, et il verrouille deux poids pour une raison mesurée : b4 ne perd que dans
    # 5 épisodes sur 30 et porte une contribution MÉDIANE NÉGATIVE (-3.3 %) — c'est un
    # AMORTISSEUR. La réduire empire strictement la queue (ES -0.24, 5 pires DD +0.76), et
    # b2 de même (ES -0.05, +0.33). b2 et b4 restent donc à 1.0R.
    # 2026-08-12, RÉVISION DU SOIR (wiki/log.md). Deux faits nouveaux, tous deux
    # EXTÉRIEURS au backtest — la seule justification qu'accepte le test de stabilité :
    #  (a) HMASTO a ÉCHOUÉ le seul hors-échantillon qu'elle ait jamais subi (NAS100
    #      juin→déc 2017, contiguïté stricte : n=118, E[R] −0.191, t=−2.61, PF 0.53),
    #      sur une fenêtre où la BRIQUE 1 tenait (n=46, E[R] +0.291, +23.6 R/an) — donc
    #      la donnée n'est pas en cause. Et 7 de ses 9 années in-sample sont
    #      indiscernables de zéro : 2021 (+98) et 2024 (+102) portent tout.
    #      → HMASTO passe de 0.5R à 0.
    #  (b) b1 était à 0.5R parce qu'HMASTO couvrait déjà les indices US intraday.
    #      Cette justification tombe avec HMASTO. → b1 revient à 1.0R.
    # TLF reste à 0.5R sur SES DEUX JAMBES : leur corrélation mensuelle n'est que
    # +0.267 (deux sleeves, pas une), et la jambe US500 contribue MOINS aux drawdowns
    # du livre (part médiane 7.1 % contre 12.9 % pour NAS100) tout en ayant le meilleur
    # RoMaD standalone (0.89 contre 0.44). Sa réserve — le mouvement brut après signal
    # est tombé à −0.021 R (t=−0.15) sur la moitié récente contre −0.109 (t=−1.56) sur
    # NAS100 — est réelle mais ne justifie pas de retirer la meilleure des deux jambes.
    # À SURVEILLER, pas à couper.
    "FUNDED":   dict(w=dict(b1=1.0, b2=1.0, b3=0.5, b4=1.0, HMASTO=0.0, TLF=0.5,
                             RVWAP=0.0, RSKEW=0.0),
                     use="FUNDED — 0.50 %/trade",
                     note="Bascule à la validation du challenge. PAS ENCORE DÉPLOYÉ. "
                          "Composition révisée le 2026-08-12 au soir : HMASTO RETIRÉE "
                          "(elle a échoué le seul hors-échantillon qu'elle ait subi : "
                          "NAS100 juin→déc 2017, n=118, t=−2.61, PF 0.53, sur une fenêtre "
                          "où la brique 1 tenait à +23.6 R/an), brique 1 REMISE à 1.0R "
                          "puisqu'elle n'était réduite que parce qu'HMASTO couvrait déjà "
                          "les indices US intraday, TLF maintenue à 0.5R sur ses deux "
                          "jambes. ⚠️ CETTE COMPOSITION SORT D'UN "
                          "BACKTEST, ET AUCUNE SLEEVE DU LIVRE N'A DE RÉSULTAT EN FORWARD "
                          "TEST — le live compte 0 à 3 allers-retours par sleeve depuis le "
                          "déploiement (HMASTO n'a jamais déclenché). Rien n'est "
                          "concluable dans un sens ni dans l'autre. La seule hiérarchie "
                          "réelle est celle du BACKTEST : b1 à b4 ont passé la batterie "
                          "complète du projet (nulls, demi-échantillons, stress de coût, "
                          "décorrélation, réplication) et sont inscrites comme briques ; "
                          "HMASTO et TLF sont des candidates IN-SAMPLE déployées à 0.5R "
                          "pour observation, avec leurs réserves documentées. Réduire une "
                          "brique qui a passé cette batterie au profit de deux sleeves qui "
                          "ne l'ont pas passée est une décision de gouvernance, pas "
                          "d'optimisation — et si HMASTO/TLF sont abandonnées, la brique 1 "
                          "doit revenir à 1.0R, car elle ne paraît coûteuse QUE parce "
                          "qu'elles couvrent déjà les indices US intraday."),
}
SLEEVES = ["b1", "b2", "b3", "b4", "HMASTO", "TLF", "RVWAP", "RSKEW"]
SLEEVE_LABEL = {
    "b1": "brique 1 — NAS100 ORB (régime bas)", "b2": "brique 2 — XAUUSD turn-of-month",
    "b3": "brique 3 — BTC+ETH MACD+RSI", "b4": "brique 4 — NAS100 IBS",
    "RVWAP": "RVWAP — GER40 H1 VWAP de session NY",
    "RSKEW": "RSKEW — US30 H4 asymétrie 50",
    "HMASTO": "HMASTO — NAS100 M15 croisement HMA/EMA + RSI/Stoch (magic 108)",
    "TLF": "TLF — two-leg fade, NAS100+US500 M5 SHORT-ONLY (magics 109/110)",
}


# ---------------------------------------------------------------------------
# data
# ---------------------------------------------------------------------------
def _daily(R, times, idx):
    t = pd.DatetimeIndex(pd.to_datetime(times))
    t = t.tz_convert("UTC") if t.tz is not None else t.tz_localize("UTC")
    s = pd.Series(np.asarray(R, float), index=t.tz_localize(None).normalize())
    return s.groupby(level=0).sum().reindex(idx).fillna(0.0)


def load_sleeves() -> tuple[pd.DataFrame, pd.Timestamp, pd.Timestamp]:
    _, parts, (start, end), _ = build_daily_R()
    idx = pd.date_range(start, end, freq="D")
    b1, b2, b3, b4 = [p.reindex(idx).fillna(0.0) for p in parts]
    hm = run_hma_stoch("NAS100").trades
    # TLF trade DEUX symboles sous deux magics (109 NAS100, 110 US500), comme la brique 3
    # avec ses deux coins : on somme leurs R quotidiens en une seule sleeve.
    tlf = pd.concat([run_two_leg_fade(s_).trades for s_ in ("NAS100", "US500")])
    # RVWAP / RSKEW : les deux sleeves de `research/`, deployees le 2026-08-18. Le
    # backtest appele ici est celui-la meme que le scan live utilise
    # (`research_sleeves.decide`), et `check_live_parity_research.py` le prouve.
    rv = run_research_sleeve("RVWAP").trades
    rs = run_research_sleeve("RSKEW").trades
    M = pd.DataFrame({
        "b1": b1, "b2": b2, "b3": b3, "b4": b4,
        "HMASTO": _daily(hm["R"], hm["exit_time"], idx),
        "TLF": _daily(tlf["R"], tlf["exit_time"], idx),
        "RVWAP": _daily(rv["R"], rv["exit_time"], idx),
        "RSKEW": _daily(rs["R"], rs["exit_time"], idx),
    })
    for k, c in _ftmo_costs(idx).items():
        M[k] = M[k] - c
    return M, start, end


def _ftmo_costs(idx: pd.DatetimeIndex) -> dict:
    """Coût FTMO quotidien par sleeve, en R. Voir `edgelab/reports/ftmo_costs.py`.

    Seules b2, b3 et b4 portent la nuit. b1, HMASTO et TLF sont intraday pures (sortie le
    jour même, 0 unité de swap) et les indices sont sans commission sur ce compte : elles
    conservent 100 % de leur R, ce que `swap_units` produit tout seul.

    ⚠️ Ce coût n'est PAS une correction cosmétique. Sur la brique 3 il vaut 5,71 R/an
    contre 5,72 R/an de brut encore gagné depuis juillet 2022 : il l'annule exactement.
    """
    from dataclasses import replace as _replace

    from edgelab.backtest.costs import CostModel
    from edgelab.backtest.engine import BacktestEngine
    from edgelab.config import load_config, risk_for
    from edgelab.edges.ibs import IBSParams, run_ibs
    from edgelab.edges.turn_of_month import TurnOfMonthParams, run_turn_of_month
    from edgelab.reports.monte_carlo_static import load as _load, macd_rsi as _macd
    from edgelab.risk.trade_rules import atr as _atr

    out = {}

    # --- b2 : or, LONG-ONLY -> paie le cote cher --------------------------------
    g = run_turn_of_month("XAUUSD", TurnOfMonthParams(sl_atr=1.5))
    ent = pd.DatetimeIndex(pd.to_datetime(g["date"]))
    ext = ent + pd.to_timedelta(g["bars_held"].to_numpy(), unit="D")
    out["b2"] = daily_cost(ext, trade_cost_R("XAUUSD", ent, ext, g["entry"].to_numpy(),
                                             g["r_dist"].to_numpy(), direction=+1), idx)

    # --- b4 : NAS100 IBS, LONG-ONLY --------------------------------------------
    i0 = run_ibs("NAS100", IBSParams(sl_atr=2.5), cadence="live")
    out["b4"] = daily_cost(i0["exit_dt"],
                           trade_cost_R("NAS100", i0["entry_dt"], i0["exit_dt"],
                                        i0["entry"].to_numpy(), i0["r_dist"].to_numpy(),
                                        direction=+1), idx)

    # --- b3 : crypto, bidirectionnelle. Le moteur n'expose pas sa distance de stop,
    # on la reconstruit sur l'ATR de la barre PRECEDANT l'entree -- exactement comme le
    # moteur la dimensionne.
    cfg = load_config()
    crisk = risk_for(cfg, "crypto")
    eng = BacktestEngine(_replace(cfg, raw={**cfg.raw, "risk": crisk}),
                         cost_model=CostModel(10, 3, {"BTCUSD": 5, "ETHUSD": 8}),
                         cadence="live")
    tot = None
    for sym in ("BTCUSD", "ETHUSD"):
        d = _load(sym)
        a = _atr(d, int(crisk["atr_window"])).shift(1)
        tr = eng.run(d, _macd(d), sym, "x").trades
        sl = float(crisk["stop_loss_atr"]) * a.reindex(
            pd.DatetimeIndex(pd.to_datetime(tr["entry_time"], utc=True))).to_numpy()
        c = daily_cost(tr["exit_time"],
                       trade_cost_R(sym, tr["entry_time"], tr["exit_time"],
                                    tr["entry_price"].to_numpy(), sl), idx)
        tot = c if tot is None else tot + c
    out["b3"] = tot

    # --- RVWAP / RSKEW : indices sans commission chez ce broker. Elles tiennent la
    # nuit (24 barres H1 et 5 barres H4), donc elles PAIENT le swap -- contrairement a
    # b1/HMASTO/TLF qui sont intraday pures. Taux releves sur le terminal FTMO le
    # 2026-08-18 (`research/scripts/13_ftmo_read_specs.py`) : GER40 long 6.62 %/an et
    # court 0.42 ; US30 long 0.77 et court 7.52 -- les deux cotes d'US30 se sont
    # INVERSES depuis le releve du 2026-08-10, ce qui est mesure et non suppose.
    for _name, _sym in (("RVWAP", "GER40"), ("RSKEW", "US30")):
        _t = run_research_sleeve(_name).trades
        out[_name] = daily_cost(
            _t["exit_time"],
            trade_cost_R(_sym, _t["entry_time"], _t["exit_time"],
                         _t["entry"].to_numpy(), _t["sl_dist"].to_numpy(),
                         direction=_t["direction"].to_numpy()), idx)
    return out


def book_series(M: pd.DataFrame, w: dict) -> pd.Series:
    return pd.Series(M[SLEEVES].to_numpy() @ np.array([w[s] for s in SLEEVES]),
                     index=M.index)


def stats(s: pd.Series) -> dict:
    span = max((s.index.max() - s.index.min()).days / 365.25, 1e-9)
    cum = s.cumsum()
    dd = cum.cummax() - cum
    m = s.resample("ME").sum()
    m = m[:-1] if len(m) > 1 else m                    # drop the partial trailing month
    active = s[s != 0]
    return dict(
        total=float(s.sum()), Ryr=float(s.sum() / span), maxDD=float(dd.max()),
        RoMaD=float((s.sum() / span) / dd.max()) if dd.max() else np.nan,
        Sharpe=float(s.mean() / s.std() * np.sqrt(365)) if s.std() else np.nan,
        worst_day=float(s.min()), worst_week=float(s.rolling(7).sum().min()),
        worst_month=float(m.min()), best_month=float(m.max()),
        m_mean=float(m.mean()), m_med=float(m.median()), m_std=float(m.std()),
        # jour actif : moyenne ET mediane. Sur une serie de R, l'ecart entre les deux
        # mesure directement l'asymetrie -- une mediane negative avec une moyenne
        # positive est la signature d'une strategie a rares gros gains.
        d_mean=float(active.mean()) if len(active) else float("nan"),
        d_med=float(active.median()) if len(active) else float("nan"),
        pos_months=float((m > 0).mean()), n_months=int(len(m)),
        active_days=int(len(active)), span=float(span),
        years=int(s.groupby(s.index.year).sum().gt(0).sum()),
        n_years=int(s.index.year.nunique()),
    )


# ---------------------------------------------------------------------------
# svg helpers — thin marks, recessive grid, direct labels
# ---------------------------------------------------------------------------
def _sc(v, lo, hi, a, b):
    return a if hi == lo else a + (v - lo) * (b - a) / (hi - lo)


def line_chart(series: dict, ylab: str = "", w=980, h=330, zero=False) -> str:
    """Multi-series time line. `series` = {name: (dates, values, colorvar)}.

    No in-plot axis label: the section heading names the unit, and a label at the top-left
    collides with the first y tick (caught on the first render)."""
    pad_l, pad_r, pad_t, pad_b = 58, 96, 22, 34
    xs = np.concatenate([np.asarray(d, dtype="datetime64[D]").astype(int)
                         for d, _, _ in series.values()])
    ys = np.concatenate([np.asarray(v, float) for _, v, _ in series.values()])
    x0, x1 = xs.min(), xs.max()
    y0, y1 = float(ys.min()), float(ys.max())
    if zero:
        y0 = min(y0, 0.0)
    pad = (y1 - y0) * 0.08 or 1
    y0, y1 = y0 - pad, y1 + pad
    parts = [f'<svg viewBox="0 0 {w} {h}" role="img" class="chart" '
             f'preserveAspectRatio="none">']
    # y grid
    ticks = np.linspace(y0, y1, 5)
    for t in ticks:
        y = _sc(t, y0, y1, h - pad_b, pad_t)
        parts.append(f'<line x1="{pad_l}" x2="{w-pad_r}" y1="{y:.1f}" y2="{y:.1f}" '
                     f'class="grid"/>')
        parts.append(f'<text x="{pad_l-10}" y="{y+4:.1f}" class="tick" '
                     f'text-anchor="end">{t:+.0f}</text>')
    # x ticks: one per year
    d0 = pd.Timestamp(np.datetime64(int(x0), "D"))
    d1 = pd.Timestamp(np.datetime64(int(x1), "D"))
    for yr in range(d0.year, d1.year + 1):
        xv = np.datetime64(f"{yr}-01-01", "D").astype(int)
        if not (x0 <= xv <= x1):
            continue
        x = _sc(xv, x0, x1, pad_l, w - pad_r)
        parts.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{pad_t}" y2="{h-pad_b}" '
                     f'class="grid"/>')
        parts.append(f'<text x="{x:.1f}" y="{h-pad_b+18}" class="tick" '
                     f'text-anchor="middle">{yr}</text>')
    for name, (dates, vals, col) in series.items():
        xi = np.asarray(dates, dtype="datetime64[D]").astype(int)
        pts = " ".join(f"{_sc(a, x0, x1, pad_l, w-pad_r):.1f},"
                       f"{_sc(b, y0, y1, h-pad_b, pad_t):.1f}"
                       for a, b in zip(xi, vals))
        parts.append(f'<polyline points="{pts}" fill="none" stroke="var({col})" '
                     f'stroke-width="2" stroke-linejoin="round"/>')
        ex = _sc(xi[-1], x0, x1, pad_l, w - pad_r)
        ey = _sc(vals[-1], y0, y1, h - pad_b, pad_t)
        parts.append(f'<circle cx="{ex:.1f}" cy="{ey:.1f}" r="4" fill="var({col})" '
                     f'stroke="var(--surface)" stroke-width="2"/>')
        parts.append(f'<text x="{ex+10:.1f}" y="{ey+4:.1f}" class="direct" '
                     f'fill="var({col})">{name}</text>')
    parts.append("</svg>")
    return "".join(parts)


def bars_by_year(years, sets: dict, w=980, h=280) -> str:
    """Grouped bars, one group per year, 4px rounded data-ends, 2px gap between bars."""
    pad_l, pad_r, pad_t, pad_b = 58, 20, 16, 34
    allv = np.concatenate([np.asarray(v, float) for v in sets.values()])
    y0, y1 = min(0.0, allv.min()) * 1.1, allv.max() * 1.12
    gw = (w - pad_l - pad_r) / len(years)
    n = len(sets)
    bw = (gw - 14) / n - 2
    zero = _sc(0, y0, y1, h - pad_b, pad_t)
    parts = [f'<svg viewBox="0 0 {w} {h}" role="img" class="chart" '
             f'preserveAspectRatio="none">']
    for t in np.linspace(y0, y1, 5):
        y = _sc(t, y0, y1, h - pad_b, pad_t)
        parts.append(f'<line x1="{pad_l}" x2="{w-pad_r}" y1="{y:.1f}" y2="{y:.1f}" class="grid"/>')
        parts.append(f'<text x="{pad_l-10}" y="{y+4:.1f}" class="tick" text-anchor="end">{t:+.0f}</text>')
    for gi, yr in enumerate(years):
        gx = pad_l + gi * gw + 7
        for si, (name, vals) in enumerate(sets.items()):
            v = float(vals[gi])
            x = gx + si * (bw + 2)
            y = _sc(v, y0, y1, h - pad_b, pad_t)
            top, hh = (y, zero - y) if v >= 0 else (zero, y - zero)
            col = f"--series-{si+1}"
            parts.append(f'<rect x="{x:.1f}" y="{top:.1f}" width="{bw:.1f}" '
                         f'height="{max(hh,1):.1f}" rx="4" fill="var({col})" '
                         f'class="mark" data-tip="{yr} · {name} · {v:+.1f} R"/>')
        parts.append(f'<text x="{gx + (gw-14)/2:.1f}" y="{h-pad_b+18}" class="tick" '
                     f'text-anchor="middle">{yr}</text>')
    parts.append(f'<line x1="{pad_l}" x2="{w-pad_r}" y1="{zero:.1f}" y2="{zero:.1f}" class="axis"/>')
    parts.append("</svg>")
    return "".join(parts)


def dd_panels(series: dict, w=980, ph=132) -> str:
    """One drawdown panel per book, stacked, on a SHARED y scale.

    Small multiples rather than one overlaid chart: two daily drawdown series cross each
    other constantly and the overlay is unreadable (caught on the first render). A shared
    scale is what makes the panels comparable."""
    pad_l, pad_r = 58, 96
    lo = min(float(np.min(v)) for _, v, _ in series.values()) * 1.06
    out = []
    for name, (dates, vals, col) in series.items():
        h = ph
        xi = np.asarray(dates, dtype="datetime64[D]").astype(int)
        x0, x1 = xi.min(), xi.max()
        parts = [f'<svg viewBox="0 0 {w} {h}" role="img" class="chart" '
                 f'preserveAspectRatio="none">']
        for t in (0, lo / 2, lo):
            y = _sc(t, lo, 0, h - 18, 12)
            parts.append(f'<line x1="{pad_l}" x2="{w-pad_r}" y1="{y:.1f}" y2="{y:.1f}" class="grid"/>')
            parts.append(f'<text x="{pad_l-10}" y="{y+4:.1f}" class="tick" text-anchor="end">{t:.0f}</text>')
        d0 = pd.Timestamp(np.datetime64(int(x0), "D")); d1 = pd.Timestamp(np.datetime64(int(x1), "D"))
        for yr in range(d0.year, d1.year + 1):
            xv = np.datetime64(f"{yr}-01-01", "D").astype(int)
            if not (x0 <= xv <= x1):
                continue
            x = _sc(xv, x0, x1, pad_l, w - pad_r)
            parts.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="12" y2="{h-18}" class="grid"/>')
            parts.append(f'<text x="{x:.1f}" y="{h-4}" class="tick" text-anchor="middle">{yr}</text>')
        pts = " ".join(f"{_sc(a, x0, x1, pad_l, w-pad_r):.1f},{_sc(b, lo, 0, h-18, 12):.1f}"
                       for a, b in zip(xi, vals))
        base = _sc(0, lo, 0, h - 18, 12)
        parts.append(f'<polygon points="{pad_l},{base:.1f} {pts} {w-pad_r},{base:.1f}" '
                     f'fill="var({col})" fill-opacity="0.16"/>')
        parts.append(f'<polyline points="{pts}" fill="none" stroke="var({col})" stroke-width="1.6"/>')
        worst = float(np.min(vals))
        parts.append(f'<text x="{w-pad_r+10}" y="{h/2:.0f}" class="direct" '
                     f'fill="var({col})">{name}</text>')
        parts.append(f'<text x="{w-pad_r+10}" y="{h/2+16:.0f}" class="tick">pire {worst:.1f} R</text>')
        parts.append("</svg>")
        out.append("".join(parts))
    return "".join(out)


def heatmap(m: pd.Series, w=980) -> str:
    """Month x year P&L. Polarity -> diverging, two hues with a NEUTRAL midpoint."""
    df = pd.DataFrame({"y": m.index.year, "m": m.index.month, "v": m.values})
    years = sorted(df.y.unique())
    cell, gap, pad_l, pad_t = 62, 2, 46, 24
    h = pad_t + len(years) * (cell * 0.46 + gap) + 26
    ch = cell * 0.46
    vmax = float(np.abs(df.v).max()) or 1.0
    parts = [f'<svg viewBox="0 0 {w} {h:.0f}" role="img" class="chart" '
             f'preserveAspectRatio="none">']
    months = ["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"]
    cw = (w - pad_l - 10) / 12
    for i, lab in enumerate(months):
        parts.append(f'<text x="{pad_l + i*cw + cw/2:.1f}" y="{pad_t-8}" class="tick" '
                     f'text-anchor="middle">{lab}</text>')
    for r, yr in enumerate(years):
        yy = pad_t + r * (ch + gap)
        parts.append(f'<text x="{pad_l-10}" y="{yy+ch*0.72:.1f}" class="tick" '
                     f'text-anchor="end">{yr}</text>')
        for c in range(1, 13):
            sel = df[(df.y == yr) & (df.m == c)]
            x = pad_l + (c - 1) * cw
            if sel.empty:
                parts.append(f'<rect x="{x:.1f}" y="{yy:.1f}" width="{cw-gap:.1f}" '
                             f'height="{ch:.1f}" rx="3" class="cell-empty"/>')
                continue
            v = float(sel.v.iloc[0])
            a = min(abs(v) / vmax, 1.0) * 0.86 + 0.10
            col = "--pos" if v > 0 else ("--neg" if v < 0 else "--muted")
            parts.append(f'<rect x="{x:.1f}" y="{yy:.1f}" width="{cw-gap:.1f}" '
                         f'height="{ch:.1f}" rx="3" fill="var({col})" '
                         f'fill-opacity="{a:.2f}" class="mark" '
                         f'data-tip="{yr}-{c:02d} · {v:+.2f} R"/>')
            parts.append(f'<text x="{x+(cw-gap)/2:.1f}" y="{yy+ch*0.70:.1f}" '
                         f'class="cellv" text-anchor="middle">{v:+.0f}</text>')
    parts.append("</svg>")
    return "".join(parts)


# ---------------------------------------------------------------------------
# page
# ---------------------------------------------------------------------------
def _tile(label, value, sub="", tone=""):
    cls = f" {tone}" if tone else ""
    return (f'<div class="tile"><div class="tl">{label}</div>'
            f'<div class="tv{cls}">{value}</div>'
            f'<div class="ts">{sub}</div></div>')


def build(out: Path = OUT) -> Path:
    M, start, end = load_sleeves()
    books = {n: book_series(M, c["w"]) for n, c in BOOKS.items()}
    st = {n: stats(s) for n, s in books.items()}
    monthly = {n: (lambda m: m[:-1])(s.resample("ME").sum()) for n, s in books.items()}
    years = sorted(set(M.index.year))
    yearly = {n: [float(s[s.index.year == y].sum()) for y in years] for n, s in books.items()}
    mc = {n: simulate(s.values, N=20000) for n, s in books.items()}

    COL = {"AGRESSIF": "--series-1", "FUNDED": "--series-2"}
    eq = {n: (s.index, s.cumsum().to_numpy(), COL[n]) for n, s in books.items()}
    ddc = {n: (s.index, -(s.cumsum().cummax() - s.cumsum()).to_numpy(), COL[n])
           for n, s in books.items()}

    # per-sleeve contribution inside each book
    sl_rows = []
    for s in SLEEVES:
        r = {"sleeve": s, "label": SLEEVE_LABEL[s]}
        for n, c in BOOKS.items():
            w = c["w"][s]
            ser = M[s] * w
            span = max((M.index.max() - M.index.min()).days / 365.25, 1e-9)
            r[n] = (w, float(ser.sum() / span))
        sl_rows.append(r)

    corr = M.resample("ME").sum().corr()

    def num(v, d=1, sign=True):
        f = f"{{:+.{d}f}}" if sign else f"{{:.{d}f}}"
        return f.format(v)

    # ---------- tiles ----------
    tiles = {}
    for n, s in st.items():
        tiles[n] = "".join([
            _tile("R / an", num(s["Ryr"]), f"{s['total']:+.0f} R au total",
                  "pos" if s["Ryr"] > 0 else "neg"),
            _tile("R / mois (moy.)", num(s["m_mean"], 2), f"médiane {s['m_med']:+.2f} R"),
            _tile("mois positifs", f"{s['pos_months']*100:.1f} %", f"sur {s['n_months']} mois"),
            _tile("max drawdown", num(s["maxDD"], 1, False) + " R", f"RoMaD {s['RoMaD']:.2f}"),
            _tile("Sharpe", f"{s['Sharpe']:.2f}", "quotidien annualisé"),
            _tile("pire journée", num(s["worst_day"], 2), f"pire mois {s['worst_month']:+.1f} R", "neg"),
            _tile("R / jour actif (moy.)", num(s["d_mean"], 3),
                  f"médiane {s['d_med']:+.3f} R sur {s['active_days']} jours"),
        ])

    # ---------- monthly % table ----------
    pct_rows = ""
    for r in RISKS:
        cells = "".join(
            f"<td>{st[n]['m_mean']*r*100:+.2f} %</td><td class='muted'>{st[n]['m_med']*r*100:+.2f} %</td>"
            f"<td class='neg'>{st[n]['worst_month']*r*100:+.2f} %</td>"
            for n in BOOKS)
        pct_rows += f"<tr><th>{r*100:.2f} %</th>{cells}</tr>"

    # ---------- prop tables ----------
    prop_rows = ""
    for n in BOOKS:
        for c, f in zip(mc[n]["chal"], mc[n]["fund"]):
            if c["risk"] not in RISKS:
                continue
            mo = f"{c['med_months']:.1f} mo" if c["med_months"] else "—"
            mo_a = f"{c['mean_months']:.1f} mo" if c.get("mean_months") else "—"
            first = c["risk"] == RISKS[0]
            prop_rows += (
                f"<tr><th>{n if first else ''}</th><td>{c['risk']*100:.2f} %</td>"
                f"<td>{c['p_pass']*100:.1f} %</td><td>{mo}</td><td class='muted'>{mo_a}</td>"
                f"<td>{c['p_fail_dd']*100:.1f} %</td><td>{c['p_fail_daily']*100:.1f} %</td>"
                f"<td>{f['mean_wd']:.1f} %</td><td class='muted'>{f['med_wd']:.1f} %</td>"
                f"<td class='{'neg' if f['p_ruin'] > .10 else ''}'>{f['p_ruin']*100:.1f} %</td></tr>")

    mc_rows = ""
    for n in BOOKS:
        a, d = mc[n]["annual"], mc[n]["mdd"]
        mc_rows += (f"<tr><th>{n}</th><td>{(a>0).mean()*100:.1f} %</td>"
                    f"<td>{np.percentile(a,5):+.1f}</td><td>{np.median(a):+.1f}</td>"
                    f"<td class='muted'>{a.mean():+.1f}</td>"
                    f"<td>{np.percentile(a,95):+.1f}</td>"
                    f"<td>{np.median(d):.1f}</td><td class='muted'>{d.mean():.1f}</td>"
                    f"<td>{np.percentile(d,95):.1f}</td></tr>")

    sleeve_rows = ""
    for r in sl_rows:
        cells = "".join(
            f"<td>{r[n][0]:g}R</td><td>{r[n][1]:+.1f}</td>" if r[n][0] > 0
            else "<td class='muted'>—</td><td class='muted'>—</td>" for n in BOOKS)
        sleeve_rows += f"<tr><th>{html.escape(r['label'])}</th>{cells}</tr>"

    corr_rows = ""
    for a in SLEEVES:
        cs = ""
        for b in SLEEVES:
            v = float(corr.loc[a, b])
            if a == b:
                cs += "<td class='muted'>1.00</td>"
            else:
                hot = "hi" if abs(v) >= 0.30 else ""
                cs += f"<td class='{hot}'>{v:+.2f}</td>"
        corr_rows += f"<tr><th>{a}</th>{cs}</tr>"

    heat = "".join(
        f'<h3>{n}</h3><figure>{heatmap(monthly[n])}</figure>' for n in BOOKS)

    gen = datetime.now().strftime("%Y-%m-%d %H:%M")
    css = CSS
    body = f"""
<div class="wrap">
 <header class="masthead">
  <p class="eyebrow">edgelab · backtest</p>
  <h1>Book AGRESSIF &amp; book FUNDED</h1>
  <p class="lede">Les deux livres nommés du plan en deux phases : le book <b>AGRESSIF</b>
   pour passer le challenge (vitesse), le book <b>FUNDED</b> une fois financé (survie).
   Tout est reconstruit depuis les modules canoniques — le rapport ne peut pas diverger
   de ce que le runner trade.</p>
  <div class="meta">
    <span>fenêtre <b>{start:%Y-%m-%d} → {end:%Y-%m-%d}</b></span>
    <span>1R = risque par trade, <b>sans capitalisation</b></span>
    <span>cadence <b>live</b> (briques 3 &amp; 4)</span>
    <span>généré le <b>{gen}</b></span>
  </div>
 </header>

 <section class="cards">
  {''.join(f'''<article class="card">
    <div class="chip" style="background:var({COL[n]})"></div>
    <h2 class="bookname">{n}</h2>
    <p class="use">{BOOKS[n]['use']}</p>
    <p class="compo">{' + '.join(f"{s}@{BOOKS[n]['w'][s]:g}R" for s in SLEEVES if BOOKS[n]['w'][s] > 0)}</p>
    <p class="note">{BOOKS[n]['note']}</p>
    <div class="tiles">{tiles[n]}</div>
  </article>''' for n in BOOKS)}
 </section>

 <section>
  <h2>Courbe de capital (R cumulés)</h2>
  <p class="sub">Somme des R de chaque sleeve, pondérée. Un stop plein = −1R net de coûts.</p>
  <figure>{line_chart(eq)}
   <figcaption>Les deux courbes partent de 0 le {start:%d/%m/%Y}.</figcaption></figure>
 </section>

 <section>
  <h2>Drawdown</h2>
  <p class="sub">Écart au plus haut de la courbe, en R. C'est le chemin, pas la volatilité,
   qui est contraint par le plancher statique de −10 %.</p>
  <figure>{dd_panels(ddc)}
   <figcaption>Échelle partagée entre les deux panneaux.</figcaption></figure>
 </section>

 <section>
  <h2>R par année civile</h2>
  <figure>{bars_by_year(years, {n: yearly[n] for n in BOOKS})}
   <figcaption>Survolez une barre pour la valeur exacte.</figcaption></figure>
 </section>

 <section>
  <h2>R par mois</h2>
  <p class="sub">Vert = mois positif, rouge = négatif ; l'intensité est proportionnelle
   à l'amplitude. Le mois en cours est exclu.</p>
  {heat}
 </section>

 <section>
  <h2>Rendement mensuel en % du compte</h2>
  <p class="sub">Sans capitalisation : <span class="mono">% du mois = R du mois × risque
   par trade</span>.</p>
  <table><thead><tr><th>risque/trade</th>
   {''.join(f'<th colspan="3">{n}</th>' for n in BOOKS)}</tr>
   <tr><th></th>{''.join('<th>moyenne</th><th>médiane</th><th>pire mois</th>' for _ in BOOKS)}</tr>
   </thead><tbody>{pct_rows}</tbody></table>
 </section>

 <section>
  <h2>Contribution par sleeve</h2>
  <p class="sub">R/an apporté par chaque sleeve <em>à sa pondération dans le livre</em>.</p>
  <table><thead><tr><th>sleeve</th>
   {''.join(f'<th colspan="2">{n}</th>' for n in BOOKS)}</tr>
   <tr><th></th>{''.join('<th>poids</th><th>R/an</th>' for _ in BOOKS)}</tr>
   </thead><tbody>{sleeve_rows}</tbody></table>
 </section>

 <section>
  <h2>Corrélations mensuelles entre sleeves</h2>
  <p class="sub">Mensuelles, pas quotidiennes : sur des sleeves peu fréquentes la
   corrélation quotidienne est un artefact de rareté et sous-estime massivement le
   recouvrement (mesuré : 0.05 en quotidien contre 0.52 en mensuel).
   Les cellules ≥ |0.30| sont surlignées.</p>
  <table class="corr"><thead><tr><th></th>
   {''.join(f'<th>{s}</th>' for s in SLEEVES)}</tr></thead>
   <tbody>{corr_rows}</tbody></table>
 </section>

 <section>
  <h2>Monte-Carlo — distribution annuelle</h2>
  <p class="sub">Block-bootstrap (blocs de 14 jours, 20 000 tirages), la fonction
   canonique du projet.</p>
  <table><thead><tr><th>livre</th><th>P(année +)</th><th>5ᵉ pct</th><th>médiane</th>
   <th>moyenne</th><th>95ᵉ pct</th><th>maxDD médian</th><th>maxDD moyen</th>
   <th>maxDD 95ᵉ</th></tr></thead>
   <tbody>{mc_rows}</tbody></table>
 </section>

 <section>
  <h2>Règles prop — challenge et funded</h2>
  <p class="sub">Cible +15 %, plancher statique −10 %, perte quotidienne −5 %.
   Funded : payout mensuel remettant le solde à l'initial.</p>
  <table><thead><tr><th>livre</th><th>risque</th><th>P(PASS)</th><th>délai méd.</th>
   <th>délai moy.</th><th>P(fail DD)</th><th>P(fail jour)</th>
   <th>retiré/an (moy.)</th><th>retiré/an (méd.)</th><th>P(ruine)/an</th>
   </tr></thead><tbody>{prop_rows}</tbody></table>
 </section>

 <section class="warn">
  <h2>Ce que ce rapport ne prouve pas</h2>
  <ul>
   <li><b>AUCUNE sleeve de ce livre n'a de résultat en forward test — pas seulement
    HMASTO et TLF.</b> Relevé sur le terminal le 2026-08-12 : depuis le déploiement, b1
    a fait <b>1</b> aller-retour, b2 <b>1</b>, b3 <b>2 positions encore ouvertes</b>,
    b4 <b>~2</b>, TLF <b>1</b>, et <b>HMASTO n'a jamais déclenché</b>. À ce nombre de
    trades rien n'est concluable, dans un sens ni dans l'autre : <b>tout ce qui est
    montré sur cette page est du backtest.</b> La seule hiérarchie réelle entre les
    sleeves est celle du backtest — b1 à b4 ont passé la batterie complète du projet
    (nulls A et B, demi-échantillons, stress de coût, décorrélation, réplication
    cross-actifs) et sont inscrites comme briques ; HMASTO et TLF sont des candidates
    <b>in-sample</b> déployées à 0.5R pour observation, jamais promues.
    TLF porte en plus quatre réserves mesurées : sans 2020 ET 2022 son t tombe à +1.77,
    son échelle de détection n'est pas monotone (M5 +3.05, M10 −1.54), elle ne réplique
    sur aucun actif hors indices US (2/13), et sa direction a été retournée
    <i>a posteriori</i> sur une surface de 2 709 cellules.</li>
   <li><b>HMASTO en particulier :</b> Elle est in-sample, mono-actif
    (elle ne réplique sur aucun autre indice) et a été sélectionnée comme meilleure
    cellule par RoMaD d'un criblage de 112 mécanismes. Sans elle, AGRESSIF redevient
    le livre gelé à 4 briques : plus lent, pas cassé.</li>
   <li><b>Les coûts FTMO SONT désormais dans ces courbes</b> (depuis le 2026-08-11) :
    commission et swap, prélevés <b>trade par trade</b>, aux taux relevés en direct sur le
    terminal FTMO le 2026-08-10. Le coût en R vaut <code>unités × taux/nuit ÷ stop%</code>,
    donc il frappe les sleeves à stop serré et à détention longue, et il est
    <b>invariant à la taille de position</b>. b1, HMASTO et TLF sont intraday pures :
    zéro nuit portée, zéro swap, et les indices sont sans commission ici. Ordre de
    grandeur : sur la brique 3 le swap vaut <b>5,71 R/an contre 5,72 R/an de brut encore
    gagné depuis juillet 2022</b> — il l'annule exactement, ce qui a motivé son passage à
    0.5R le 2026-08-10, puis son <b>retrait complet d'AGRESSIF le 2026-08-18</b>
    (+0.2 R/an pour 21.3 R de drawdown sur la fenêtre complète nette).</li>
   <li><b>Les sleeves ne décroissent pas au même rythme.</b> Entre la première et la
    seconde moitié de l'échantillon : brique 1 ×2.19, brique 2 ×1.68, brique 4 ×0.88,
    HMASTO ×1.45, <b>brique 3 ×0.32</b>. C'est ce qui a fait halver la brique 3 le
    2026-08-10 puis la <b>retirer d'AGRESSIF le 2026-08-18</b> ; FUNDED la porte
    encore à 0.5R. ⚠️ Le ×1.45 d'HMASTO est une décroissance mesurée
    <i>à l'intérieur</i> de l'échantillon de construction : hors de lui, sur la seule
    fenêtre jamais vue (NAS100 juin→déc 2017), la sleeve rend <b>−40.5 R/an à t=−2.61</b>.
    C'est ce qui l'a fait sortir de FUNDED le 2026-08-12.</li>
   <li><b>Le maximum théorique d'un jour dépasse la règle quotidienne.</b> AGRESSIF peut
    tenir 4 positions simultanées = 4,0R depuis le retrait de b3 (6 = 5,5R avant) ;
    à 1 %/trade une journée où tout part au stop coûterait −4 % contre une limite
    de −5 %, donc la règle quotidienne <b>ne peut plus être franchie par construction</b>. Ce n'est jamais arrivé (pire journée réelle
    −3,58 R) — la protection vient de la décorrélation, pas de la construction.</li>
   <li>Le block-bootstrap <b>sous-estime les régimes baissiers crypto prolongés</b> ;
    la ruine réelle est vraisemblablement au-dessus des chiffres ci-dessus.</li>
  </ul>
 </section>

 <footer>edgelab · <span class="mono">python -m edgelab.reports.books_report</span></footer>
</div>
<div id="tip" role="status"></div>
<button id="themebtn" title="thème clair / sombre" aria-label="basculer le thème">◐</button>
<script>{JS}</script>
"""
    doc = (f"<!doctype html><html lang=fr><head><meta charset=utf-8>"
           f"<title>Book AGRESSIF &amp; FUNDED — backtest</title>"
           f'<meta name="viewport" content="width=device-width, initial-scale=1">'
           f"<style>{css}</style></head><body>{body}</body></html>")
    out.write_text(doc, encoding="utf-8")
    for dest in COPIES:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(doc, encoding="utf-8")
    return out


CSS = """
:root{--ground:#f4f6f8;--surface:#fff;--ink:#131a24;--muted:#5b6675;--line:#e4e8ee;
 --accent:#0f7c8c;--pos:#1f9d61;--neg:#cf4636;--grid:#eef1f5;
 --series-1:#2a78d6;--series-2:#eb6834;
 --mono:ui-monospace,"SF Mono","Cascadia Code",Menlo,Consolas,monospace;
 --sans:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--ground:#0b1016;
 --surface:#141c27;--ink:#e7edf5;--muted:#93a1b5;--line:#232e3d;--accent:#33b3c3;
 --pos:#38c281;--neg:#e26a5f;--grid:#1a2331;--series-1:#3987e5;--series-2:#d95926}}
:root[data-theme=dark]{--ground:#0b1016;--surface:#141c27;--ink:#e7edf5;--muted:#93a1b5;
 --line:#232e3d;--accent:#33b3c3;--pos:#38c281;--neg:#e26a5f;--grid:#1a2331;
 --series-1:#3987e5;--series-2:#d95926}
*{box-sizing:border-box}
body{margin:0;background:var(--ground);color:var(--ink);font-family:var(--sans);
 line-height:1.55;font-size:15px;-webkit-font-smoothing:antialiased}
.wrap{max-width:1080px;margin:0 auto;padding:clamp(20px,4vw,52px) clamp(14px,3vw,28px) 90px}
.eyebrow{font-family:var(--mono);font-size:11px;letter-spacing:.18em;text-transform:uppercase;
 color:var(--accent);margin:0 0 10px}
h1{font-size:clamp(26px,4.5vw,40px);line-height:1.08;margin:0 0 12px;letter-spacing:-.02em;font-weight:680}
.lede{color:var(--muted);max-width:70ch;margin:0;font-size:16px}
.masthead{border-bottom:1px solid var(--line);padding-bottom:24px;margin-bottom:30px}
.meta{font-family:var(--mono);font-size:12px;color:var(--muted);margin-top:16px;
 display:flex;flex-wrap:wrap;gap:6px 22px}
.meta b{color:var(--ink);font-weight:600}
section{margin:0 0 42px}
h2{font-size:13px;font-family:var(--mono);letter-spacing:.1em;text-transform:uppercase;
 color:var(--muted);margin:0 0 6px;font-weight:600}
h3{font-size:12px;font-family:var(--mono);letter-spacing:.08em;color:var(--muted);
 margin:18px 0 6px;font-weight:600}
.sub{color:var(--muted);margin:0 0 14px;max-width:74ch;font-size:14px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(430px,1fr));gap:18px}
.card{background:var(--surface);border:1px solid var(--line);border-radius:14px;
 padding:20px 20px 8px;position:relative}
.chip{width:26px;height:4px;border-radius:2px;display:block;margin-bottom:12px}
.bookname{font-size:20px;font-family:var(--sans);letter-spacing:-.01em;text-transform:none;
 color:var(--ink);margin:0;font-weight:680}
.use{font-family:var(--mono);font-size:12px;color:var(--accent);margin:2px 0 8px}
.compo{font-family:var(--mono);font-size:12px;color:var(--ink);margin:0 0 4px;word-spacing:2px}
.note{color:var(--muted);font-size:13px;margin:0 0 14px}
.tiles{display:grid;grid-template-columns:repeat(3,1fr);gap:2px 14px}
.tile{padding:10px 0 12px;border-top:1px solid var(--line)}
.tl{font-size:11px;color:var(--muted);font-family:var(--mono);letter-spacing:.04em}
.tv{font-size:21px;font-weight:660;letter-spacing:-.02em;font-variant-numeric:tabular-nums}
.tv.pos{color:var(--pos)}.tv.neg{color:var(--neg)}
.ts{font-size:11px;color:var(--muted);font-family:var(--mono)}
figure{margin:0;background:var(--surface);border:1px solid var(--line);border-radius:14px;
 padding:14px 10px 6px}
figcaption{color:var(--muted);font-size:12px;padding:2px 8px 8px;font-family:var(--mono)}
.chart{width:100%;height:auto;display:block;overflow:visible}
.grid{stroke:var(--grid);stroke-width:1}
.axis{stroke:var(--line);stroke-width:1}
.tick{font-size:11px;fill:var(--muted);font-family:var(--mono)}
.axlab{font-size:11px;fill:var(--muted);font-family:var(--mono)}
.direct{font-size:12px;font-family:var(--mono);font-weight:600}
.cellv{font-size:9px;fill:var(--ink);font-family:var(--mono);opacity:.72;pointer-events:none}
.cell-empty{fill:var(--grid)}
.mark{cursor:crosshair}.mark:hover{stroke:var(--ink);stroke-width:1.5}
table{width:100%;border-collapse:collapse;font-size:13.5px;background:var(--surface);
 border:1px solid var(--line);border-radius:12px;overflow:hidden;
 font-variant-numeric:tabular-nums}
th,td{padding:8px 10px;text-align:right;border-bottom:1px solid var(--line)}
thead th{font-family:var(--mono);font-size:11px;letter-spacing:.05em;color:var(--muted);
 text-transform:uppercase;font-weight:600}
tbody th{text-align:left;font-weight:560}
tbody tr:last-child td,tbody tr:last-child th{border-bottom:none}
td.muted,.muted{color:var(--muted)}
td.neg,.neg{color:var(--neg)}
.corr td{font-family:var(--mono);font-size:12.5px}
.corr td.hi{color:var(--neg);font-weight:680}
.mono{font-family:var(--mono);font-size:.92em}
.warn{background:var(--surface);border:1px solid var(--line);border-left:3px solid var(--neg);
 border-radius:12px;padding:18px 22px}
.warn ul{margin:8px 0 0;padding-left:20px}.warn li{margin:0 0 9px;color:var(--muted)}
.warn li b{color:var(--ink)}
footer{color:var(--muted);font-size:12px;border-top:1px solid var(--line);padding-top:16px;
 font-family:var(--mono)}
#tip{position:fixed;pointer-events:none;opacity:0;transition:opacity .1s;background:var(--ink);
 color:var(--ground);font-family:var(--mono);font-size:12px;padding:5px 9px;border-radius:6px;
 z-index:9;white-space:nowrap}
#themebtn{position:fixed;right:16px;bottom:16px;width:38px;height:38px;border-radius:50%;
 border:1px solid var(--line);background:var(--surface);color:var(--ink);cursor:pointer;
 font-size:16px;box-shadow:0 2px 10px #0002}
@media(max-width:700px){.tiles{grid-template-columns:repeat(2,1fr)}
 table{font-size:12px}th,td{padding:6px 6px}}
"""

JS = """
const tip=document.getElementById('tip');
document.addEventListener('mouseover',e=>{const t=e.target.getAttribute?.('data-tip');
 if(!t)return;tip.textContent=t;tip.style.opacity=1;});
document.addEventListener('mousemove',e=>{if(tip.style.opacity==='1'){
 tip.style.left=(e.clientX+14)+'px';tip.style.top=(e.clientY-30)+'px';}});
document.addEventListener('mouseout',e=>{if(e.target.getAttribute?.('data-tip'))
 tip.style.opacity=0;});
document.getElementById('themebtn').onclick=()=>{
 const r=document.documentElement;
 const cur=r.getAttribute('data-theme')||
   (matchMedia('(prefers-color-scheme:dark)').matches?'dark':'light');
 r.setAttribute('data-theme',cur==='dark'?'light':'dark');};
"""


if __name__ == "__main__":
    p = build()
    kb = p.stat().st_size / 1024
    print(f"-> {p}  ({kb:.0f} kB)")
    for d in COPIES:
        print(f"-> {d}")
