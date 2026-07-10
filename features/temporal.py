"""
features/temporal.py
====================
Features temporelles (encodage cyclique) + session active. Tout en UTC en interne.

- Heure cyclique : Hour_Sin = sin(2π h/24), Hour_Cos = cos(2π h/24).
- Jour de semaine cyclique (0=Lun..4=Ven, base 5) : DoW_Sin, DoW_Cos.
- (optionnel) Session active (asia/london/newyork) en one-hot.

Purement déterministe à partir de l'index : aucune donnée de marché, donc aucun leakage.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import config
import calendar_utils as cal


def compute(df: pd.DataFrame) -> pd.DataFrame:
    """Calcule les features temporelles à partir de l'index UTC. df → DataFrame de features."""
    idx = df.index.tz_convert("UTC")
    out = pd.DataFrame(index=df.index)

    # Heure de la journée (cyclique)
    hour = idx.hour.to_numpy() + idx.minute.to_numpy() / 60.0
    out["hour_sin"] = np.sin(2.0 * np.pi * hour / 24.0)
    out["hour_cos"] = np.cos(2.0 * np.pi * hour / 24.0)

    # Jour de semaine forex (0=Lun..4=Ven), base 5 pour le cycle
    dow = idx.dayofweek.to_numpy().astype(float)      # Lun=0..Dim=6
    dow5 = np.clip(dow, 0, 4)                          # dimanche soir rattaché à vendredi (base 5)
    out["dow_sin"] = np.sin(2.0 * np.pi * dow5 / 5.0)
    out["dow_cos"] = np.cos(2.0 * np.pi * dow5 / 5.0)

    # Session active (one-hot, sessions pouvant se chevaucher)
    if config.ENABLE_SESSION_ONEHOT:
        masks = cal.session_masks(df.index)
        for name in config.SESSIONS:
            out[f"session_{name}"] = masks[name].astype(np.int8).to_numpy()

    return out
