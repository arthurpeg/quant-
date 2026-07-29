"""The edge-validation gate — the discipline that stops fake edges getting through.

Encodes the falsification bar from Mesfin (arXiv 2605.04004), plus a decorrelation
requirement against an existing brick:
  * t-stat of per-bet P&L  > ``min_t``      (default 2.0)
  * mean per-bet P&L       > 0              (net of cost — cost must already be in)
  * cross-year consistency >= ``min_year_frac`` of years positive
  * |corr| to the reference brick < ``max_corr`` (so it actually diversifies)
A candidate must clear ALL of these to be a serious brick.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class GateResult:
    n: int
    mean: float
    t_stat: float
    sharpe_annual: float
    years_positive: int
    years_total: int
    corr_to_brick: float | None
    passed: bool
    reasons: list[str]

    def summary(self) -> str:
        c = "n/a" if self.corr_to_brick is None else f"{self.corr_to_brick:+.2f}"
        verdict = "PASS" if self.passed else "FAIL"
        return (f"[{verdict}] n={self.n} mean={self.mean:+.4f} t={self.t_stat:+.2f} "
                f"Sharpe={self.sharpe_annual:+.2f} yrs+={self.years_positive}/{self.years_total} "
                f"corr={c}" + ("" if self.passed else f"  ({'; '.join(self.reasons)})"))


def validate_edge(bets: pd.Series, brick_bets: pd.Series | None = None,
                  min_t: float = 2.0, min_year_frac: float = 0.7,
                  max_corr: float = 0.30, periods_per_year: int = 252) -> GateResult:
    """Validate a series of per-bet net P&L (indexed by date) against the gate.

    ``bets`` : one value per trade/bet, net of cost, DatetimeIndex (or date index).
    ``brick_bets`` : the reference brick's daily P&L for the decorrelation check.
    """
    bets = bets.dropna()
    n = len(bets)
    reasons: list[str] = []
    if n < 30:
        return GateResult(n, float(bets.mean()) if n else 0.0, 0.0, 0.0, 0, 0, None,
                          False, ["<30 bets"])

    mean = float(bets.mean())
    std = float(bets.std(ddof=1))
    t_stat = mean / std * np.sqrt(n) if std > 0 else 0.0
    sharpe = mean / std * np.sqrt(periods_per_year) if std > 0 else 0.0

    idx = pd.to_datetime(bets.index)
    years = idx.year
    by_year = bets.groupby(years).sum()
    yrs_pos, yrs_tot = int((by_year > 0).sum()), int(len(by_year))

    corr = None
    if brick_bets is not None and len(brick_bets):
        a = bets.groupby(idx.date).sum()
        b = brick_bets.copy()
        b.index = pd.to_datetime(b.index).date
        common = pd.Index(a.index).union(b.index)
        aa = a.reindex(common).fillna(0.0)
        bb = b.reindex(common).fillna(0.0)
        if aa.std() > 0 and bb.std() > 0:
            corr = float(np.corrcoef(aa.values, bb.values)[0, 1])

    if t_stat <= min_t:
        reasons.append(f"t={t_stat:.2f}<= {min_t}")
    if mean <= 0:
        reasons.append("mean<=0")
    if yrs_tot and yrs_pos / yrs_tot < min_year_frac:
        reasons.append(f"cross-year {yrs_pos}/{yrs_tot}")
    if corr is not None and abs(corr) >= max_corr:
        reasons.append(f"|corr|={abs(corr):.2f}>= {max_corr}")

    passed = not reasons
    return GateResult(n, mean, t_stat, sharpe, yrs_pos, yrs_tot, corr, passed, reasons)
