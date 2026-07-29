"""Intraday CROSS-SECTIONAL index edge (market-neutral), anchored to the US open.

The wiki's "breadth" thread, taken intraday. For each day, across the cash indices
that are simultaneously live 09:30-11:00 ET:
    signal  = opening-drive return  (09:30 open -> 10:00 open)
    forward = next-hour return       (10:00 open -> 11:00 open)   [DISJOINT windows]
Cross-sectionally demean; test whether the signal predicts the forward (momentum)
or reverses it (reversal). L/S = long top-k / short bottom-k by signal, equal weight,
market-neutral, reported GROSS and NET of each name's per-bar half-spread cost.

VERDICT (2026-07-28, 11 Pepperstone indices, ~2188 days): IC +0.014 (t=1.47, NOT
significant); gross L/S Sharpe ~0; cost (SWI20 27bps, NETH25 50bps) makes it strongly
negative. No tradable intraday cross-sectional edge — same breadth-wall as exp-003/006.

WARNING remembered here: the signal and forward windows MUST be disjoint. A first
version overlapped by one 10-min bar and produced a spurious IC +0.168 (t=18).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from edgelab.intraday.orb import POINT_SIZE, load_bars

DEFAULT_BASKET = ["NAS100", "US30", "US500", "US2000", "GER40", "FRA40",
                  "UK100", "SWI20", "NETH25", "AUS200", "HK50"]


def _daily_panel(sym: str) -> pd.DataFrame | None:
    try:
        df = load_bars(sym, "M10")
    except FileNotFoundError:
        return None
    ny = df.tz_convert("America/New_York")
    mn = ny.index.hour * 60 + ny.index.minute
    w = ny[(mn >= 570) & (mn <= 660)]
    point = POINT_SIZE.get(sym, 0.1)
    recs = {}
    for day, g in w.groupby(w.index.date):
        gm = g.index.hour * 60 + g.index.minute

        def px(col, t):
            s = g[gm == t]
            return float(s[col].iloc[0]) if len(s) else np.nan

        o930, o1000, o1100 = px("open", 570), px("open", 600), px("open", 660)
        if np.isnan(o930) or np.isnan(o1000) or np.isnan(o1100):
            continue
        recs[day] = {"sig": (o1000 - o930) / o930, "fwd": (o1100 - o1000) / o1000,
                     "cost": float(g["spread"].median()) * point / o1000}
    return pd.DataFrame(recs).T if recs else None


def run_xsectional(basket: list[str] | None = None, top_k: int = 3,
                   min_names: int = 5) -> dict:
    """Return IC + gross/net L/S metrics for the intraday index cross-section."""
    basket = basket or DEFAULT_BASKET
    panels = {s: _daily_panel(s) for s in basket}
    panels = {k: v for k, v in panels.items() if v is not None and len(v) > 200}

    sig = pd.DataFrame({s: panels[s]["sig"] for s in panels})
    fwd = pd.DataFrame({s: panels[s]["fwd"] for s in panels})
    cost = pd.DataFrame({s: panels[s]["cost"] for s in panels})
    common = sig.dropna(thresh=min_names).index
    sig, fwd, cost = sig.loc[common], fwd.loc[common], cost.loc[common]
    sig_x = sig.sub(sig.mean(axis=1), axis=0)
    fwd_x = fwd.sub(fwd.mean(axis=1), axis=0)

    ics = []
    for d in sig_x.index:
        x, y = sig_x.loc[d].dropna(), fwd_x.loc[d].dropna()
        j = x.index.intersection(y.index)
        if len(j) >= min_names:
            ics.append(x[j].rank().corr(y[j].rank()))
    ic = pd.Series(ics)

    def ls(sign, net):
        rets = {}
        for d in sig_x.index:
            s = (sign * sig_x.loc[d]).dropna()
            if len(s) < 2 * top_k:
                continue
            lo, sh = s.nlargest(top_k).index, s.nsmallest(top_k).index
            r = fwd.loc[d][lo].mean() - fwd.loc[d][sh].mean()
            if net:
                r -= cost.loc[d][lo].mean() + cost.loc[d][sh].mean()
            rets[d] = r
        return pd.Series(rets)

    ann = np.sqrt(252)
    out = {"n_days": len(common), "avg_names": float(sig.notna().sum(axis=1).mean()),
           "ic_mean": float(ic.mean()),
           "ic_t": float(ic.mean() / ic.std() * np.sqrt(len(ic))) if ic.std() else 0.0}
    for sign, tag in [(+1, "momentum"), (-1, "reversal")]:
        rg, rn = ls(sign, False), ls(sign, True)
        out[f"{tag}_gross_sharpe"] = float(rg.mean() / rg.std() * ann) if rg.std() else 0.0
        out[f"{tag}_net_sharpe"] = float(rn.mean() / rn.std() * ann) if rn.std() else 0.0
    out["cost_bps_per_name"] = {s: round(float(cost[s].mean() * 1e4), 2) for s in cost}
    return out


if __name__ == "__main__":
    import json
    print(json.dumps(run_xsectional(), indent=2))
