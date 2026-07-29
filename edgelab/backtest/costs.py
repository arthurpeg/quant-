"""Transaction-cost model: spread + slippage charged on entry AND exit.

Cost is expressed in basis points of price per side and converted to a price
amount at fill time, so it scales with the instrument's price level.
"""
from __future__ import annotations

from dataclasses import dataclass

from edgelab.config import Config


@dataclass(frozen=True)
class CostModel:
    default_spread_bps: float
    default_slippage_bps: float
    per_symbol_spread_bps: dict[str, float]

    @classmethod
    def from_config(cls, cfg: Config) -> "CostModel":
        c = cfg.costs
        return cls(
            default_spread_bps=float(c["default_spread_bps"]),
            default_slippage_bps=float(c["default_slippage_bps"]),
            per_symbol_spread_bps={k: float(v) for k, v in
                                   (c.get("per_symbol_spread_bps") or {}).items()},
        )

    def rate_per_side(self, symbol: str) -> float:
        """Fractional cost of one fill (spread + slippage), e.g. 0.0003 = 3 bps."""
        spread = self.per_symbol_spread_bps.get(symbol, self.default_spread_bps)
        return (spread + self.default_slippage_bps) / 1e4

    def cost_amount(self, symbol: str, price: float, size: float) -> float:
        """Cash cost of a single fill of ``size`` units at ``price``."""
        return self.rate_per_side(symbol) * price * abs(size)
