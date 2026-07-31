"""Configuration loader.

A thin, typed wrapper over ``config.yaml`` so the rest of the code never parses
YAML by hand. All paths in the config are resolved relative to the repo root.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

# Repo root = parent of the ``edgelab`` package directory.
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "config.yaml"

logger = logging.getLogger("edgelab.config")


def risk_for(cfg: "Config", brick: str) -> dict:
    """Risk barriers for one brick: the generic ``risk:`` block, overridden by ``<brick>_risk:``.

    Keeps per-brick exits out of the framework defaults, which the generic pipeline and
    ``walk_forward.embargo_bars`` depend on. Unknown brick -> the plain defaults.
    """
    merged = dict(cfg.raw["risk"])
    merged.update(cfg.raw.get(f"{brick}_risk") or {})
    return merged


@dataclass(frozen=True)
class Config:
    """Parsed configuration. Sub-sections stay as plain dicts for flexibility."""

    raw: dict[str, Any]
    path: Path

    def __getitem__(self, key: str) -> Any:
        return self.raw[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.raw.get(key, default)

    # --- convenience accessors for the common sections ---
    @property
    def data(self) -> dict[str, Any]:
        return self.raw["data"]

    @property
    def costs(self) -> dict[str, Any]:
        return self.raw["costs"]

    @property
    def risk(self) -> dict[str, Any]:
        return self.raw["risk"]

    @property
    def propfirm(self) -> dict[str, Any]:
        return self.raw["propfirm"]

    @property
    def backtest(self) -> dict[str, Any]:
        return self.raw["backtest"]

    @property
    def portfolio(self) -> dict[str, Any]:
        return self.raw["portfolio"]

    @property
    def research(self) -> dict[str, Any]:
        return self.raw["research"]

    def resolve_path(self, rel: str | Path) -> Path:
        """Resolve a config-relative path against the repo root."""
        p = Path(rel)
        return p if p.is_absolute() else (REPO_ROOT / p)


def load_config(path: str | Path | None = None) -> Config:
    """Load and return the :class:`Config`. Defaults to ``edgelab/config.yaml``."""
    cfg_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    with open(cfg_path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    logger.debug("Loaded config from %s", cfg_path)
    return Config(raw=raw, path=cfg_path)
