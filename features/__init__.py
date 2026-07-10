"""
Package `features` — feature engineering sans leakage.

Règle absolue (voir chaque module) :
  - Toute feature à l'instant t n'utilise QUE des données ≤ t (bougies clôturées).
  - Aucun rolling/ewm centré : center=False partout.
  - Normalisations en rolling (jamais sur des stats globales du dataset).
  - Signature homogène : df en entrée → DataFrame de features en sortie, index conservé.
"""

from . import momentum, volatility, volume, structure, temporal  # noqa: F401
