# Phase 1 -- porte IC avant tout backtest

_Genere le 2026-08-18 00:22 -- terminal MetaTrader 5 / PepperstoneUK-Demo._


## Ce qui a ete mesure

- **3864** papiers uniques moissonnes (arXiv, NBER, OpenAlex, corpus local ; SSRN direct refuse en HTTP 401).
- **168** definitions de signal dans le catalogue, 5 familles.
- **28300** cellules d'IC = signal x actif x unite de temps x horizon k.
- Univers : 20 symboles, UT M5/M15/H1/H4, k ∈ [1, 3, 5, 12, 24].
- Aucun stop, aucune cible, aucun cout : cette phase mesure le signal, pas le P&L.


## La porte

`|Mean IC| >= 0.03` ET `|t| >= 2.5` ET signe constant sur >= 3/4 sous-periodes ET >= 500 occurrences independantes.


| | cellules | passent la porte | taux |
|---|--:|--:|--:|
| **grille reelle** | 28300 | **2467** | 8.72 % |
| temoin (futur pivote) | 28300 | 123 | 0.43 % |

**Rapport reel / temoin : 20.06x**  — la grille trouve plus que le hasard.

**Survivants Benjamini-Hochberg (q <= 0.1) : 2467** (q minimale de la grille : 0.0000).


## |IC| maximal par famille

| famille | cellules | \|IC\| median | \|IC\| max | \|t\| max | passent |
|---|--:|--:|--:|--:|--:|
| cross_asset_lead_lag | 5800 | 0.0123 | 0.0779 | 20.59 | 296 |
| intraday_momentum_breakout | 7100 | 0.0140 | 0.1284 | 23.68 | 867 |
| mean_reversion_extreme | 7200 | 0.0156 | 0.1355 | 26.11 | 1186 |
| microstructure_session_seasonality | 3800 | 0.0075 | 0.0728 | 7.09 | 67 |
| volatility_skew_dynamics | 4400 | 0.0063 | 0.0790 | 12.79 | 51 |

## Par unite de temps

| UT | cellules | \|IC\| median | \|IC\| max | passent | temoin |
|---|--:|--:|--:|--:|--:|
| M5 | 7250 | 0.0148 | 0.0703 | 1067 | 13 |
| M15 | 7250 | 0.0120 | 0.0877 | 750 | 33 |
| H1 | 7150 | 0.0092 | 0.1284 | 469 | 135 |
| H4 | 6650 | 0.0112 | 0.1355 | 181 | 555 |

## Par classe d'actif

| classe | cellules | \|IC\| median | \|IC\| max | passent |
|---|--:|--:|--:|--:|
| commodity | 4175 | 0.0101 | 0.1354 | 204 |
| crypto | 2650 | 0.0167 | 0.1024 | 649 |
| fx | 14650 | 0.0124 | 0.1355 | 1358 |
| index | 6825 | 0.0098 | 0.1325 | 256 |

## Les 25 cellules au plus fort |t| (porte franchie ou non)

| signal | actif | UT | k | IC | t | t(NW) | n indep | stab | sous-per. | q |
|---|---|---|--:|--:|--:|--:|--:|--:|--:|--:|
| atr_band_z | EURGBP | M5 | 1 | +0.0517 | +26.11 | +26.17 | 494347 | 1.00 | 4/4 | 0.000 |
| rsi_dev | EURGBP | M5 | 1 | +0.0485 | +25.53 | +26.17 | 494353 | 1.00 | 4/4 | 0.000 |
| rsi_dev | EURGBP | M5 | 1 | +0.0548 | +25.53 | +25.16 | 494353 | 1.00 | 4/4 | 0.000 |
| boll_z | EURGBP | M5 | 1 | +0.0550 | +25.03 | +26.06 | 494347 | 1.00 | 4/4 | 0.000 |
| boll_z | EURGBP | M5 | 1 | +0.0462 | +24.72 | +25.54 | 494317 | 1.00 | 4/4 | 0.000 |
| atr_band_z | EURGBP | M5 | 1 | +0.0419 | +24.31 | +25.03 | 494317 | 1.00 | 4/4 | 0.000 |
| ret_zscore | EURGBP | M5 | 1 | +0.0495 | +24.36 | +23.89 | 494335 | 1.00 | 4/4 | 0.000 |
| donchian_pos | EURGBP | M5 | 1 | -0.0379 | -23.68 | -25.48 | 494319 | 1.00 | 4/4 | 0.000 |
| atr_band_z | GBPUSD | M5 | 1 | +0.0261 | +22.84 | +24.93 | 494258 | 1.00 | 4/4 | 0.000 |
| range_expansion | EURGBP | M5 | 1 | -0.0415 | -22.70 | -23.18 | 494353 | 1.00 | 4/4 | 0.000 |
| ibs | BTCUSD | M15 | 1 | +0.0681 | +24.59 | +22.51 | 265888 | 1.00 | 4/4 | 0.000 |
| atr_band_z | GBPJPY | M5 | 1 | +0.0300 | +22.42 | +22.83 | 494239 | 1.00 | 4/4 | 0.000 |
| rsi_dev | GBPUSD | M5 | 1 | +0.0303 | +22.33 | +22.45 | 494294 | 1.00 | 4/4 | 0.000 |
| range_expansion | EURGBP | M5 | 1 | -0.0485 | -25.23 | -22.25 | 494353 | 1.00 | 4/4 | 0.000 |
| tsmom | EURGBP | M5 | 1 | -0.0403 | -21.99 | -23.92 | 494353 | 1.00 | 4/4 | 0.000 |
| donchian_pos | GBPJPY | M5 | 1 | -0.0351 | -22.42 | -21.46 | 494265 | 1.00 | 4/4 | 0.000 |
| ibs | EURGBP | M15 | 1 | +0.0703 | +21.54 | +21.39 | 214586 | 1.00 | 4/4 | 0.000 |
| range_expansion | GBPUSD | M15 | 1 | -0.0283 | -21.20 | -22.18 | 214605 | 1.00 | 4/4 | 0.000 |
| atr_band_z | EURJPY | M5 | 1 | +0.0321 | +22.36 | +21.14 | 494292 | 1.00 | 4/4 | 0.000 |
| boll_z | GBPUSD | M5 | 1 | +0.0341 | +22.03 | +21.05 | 494288 | 1.00 | 4/4 | 0.000 |
| rsi_dev | EURGBP | M5 | 1 | +0.0595 | +23.30 | +21.04 | 494353 | 1.00 | 4/4 | 0.000 |
| range_expansion | EURJPY | M5 | 3 | -0.0371 | -20.96 | -22.51 | 164775 | 1.00 | 4/4 | 0.000 |
| atr_band_z | GBPJPY | M5 | 1 | +0.0394 | +22.61 | +20.92 | 494269 | 1.00 | 4/4 | 0.000 |
| range_expansion | EURGBP | M15 | 1 | -0.0502 | -20.85 | -22.77 | 214608 | 1.00 | 4/4 | 0.000 |
| donchian_pos | BTCUSD | M15 | 1 | -0.0524 | -23.44 | -20.80 | 265916 | 1.00 | 4/4 | 0.000 |

## Le bord attendu, rapporte au peage

Arithmetique pure sur des quantites deja mesurees, pas un backtest : `bord attendu = |IC| x sigma(R_{t+k})`, `peage` = plancher de spread NON NUL en heures liquides + commission Razor + 1 pip de slippage par cote (la methode de `swinglab/costs.py`, deja validee ici). Un spread median naif vaut ZERO sur les majeures -- le flux imprime 0 point sur la moitie des barres EURUSD -- et ce zero envoie le rapport a l'infini ; d'ou le plancher non nul. La colonne **sans slippage** est donnee a part parce que sur EURUSD le slippage pese 20 des 33 points du peage : c'est une hypothese, pas une mesure.


| UT | cellules sous la porte | bord attendu median (bps) | peage median (bps) | bord/peage median | dont >= 1 | bord/peage sans slippage |
|---|--:|--:|--:|--:|--:|--:|
| M5 | 1067 | 0.399 | 3.203 | 0.108 | 9 | 0.239 |
| M15 | 750 | 0.813 | 3.203 | 0.172 | 34 | 0.366 |
| H1 | 469 | 1.318 | 3.093 | 0.370 | 86 | 0.861 |
| H4 | 181 | 3.191 | 2.243 | 1.229 | 106 | 2.221 |

**235 des 2467 cellules sous la porte ont un bord attendu superieur au peage** (9.5 %) ; **412** (16.7 %) si l'on retire l'hypothese de slippage et qu'on ne compte que spread + commission.


La colonne mediane est monotone en UT : **0,11 en M5, 0,17 en M15, 0,37 en H1, 1,23 en H4**. La porte du mandat, elle, ne l'est pas -- elle laisse passer 1 067 cellules en M5 contre 181 en H4. **L'IC ne dit donc pas ou est le bord exploitable : il dit ou est le signal, et le signal est le plus fort la ou le peage est le plus cher relativement.** C'est le meme resultat que ce depot a mesure six fois par le P&L, obtenu ici sans backtest.


### Le rebond bid-ask, nomme

L'autocorrelation a une barre des rendements est negative sur toute la grille. Un signal de reversion courte qui ressort a |IC| eleve sur k = 1 mesure ce rebond entre bid et ask : reel, ecrasant statistiquement, et non exploitable puisque c'est le spread lui-meme.

| UT | autocorr(1) mediane | cellules sous la porte | dont k=1 | dont k=1 en reversion |
|---|--:|--:|--:|--:|
| M5 | -0.0224 | 1067 | 190 | 106 |
| M15 | -0.0140 | 750 | 211 | 119 |
| H1 | -0.0135 | 469 | 153 | 88 |
| H4 | -0.0197 | 181 | 76 | 46 |

### Le resultat central de la phase

**Spearman( |t| , bord/peage ) = -0.608** sur les 2467 cellules sous la porte.


Ce seul nombre resume la phase. **Plus une cellule est significative, moins elle est exploitable** -- et l'anticorrelation est forte, pas marginale. La porte du mandat classe donc les hypotheses a peu pres a l'ENVERS de leur viabilite economique : ses meilleurs scores (|t| jusqu'a 26) sont des reversions a k = 1 en M5, c'est-a-dire le rebond bid-ask, et ses cellules limites (|t| ~ 2,5, H4, k = 24) sont les seules dont le bord attendu depasse le peage. A l'inverse, Spearman( k , bord/peage ) = +0.358 : **l'horizon, lui, classe dans le bon sens.**


### Ce qui reste quand on retire le rebond

Meme porte, mais **k >= 5 seulement** (au-dela de la memoire du carnet) **et bord/peage >= 1** :


**173 cellules** sur 2467.


| signal | famille | actif | UT | k | IC | t | bord/peage | sous-per. |
|---|---|---|---|--:|--:|--:|--:|--:|
| rsi_dev | REV | BTCUSD | H1 | 5 | +0.0408 | +8.9 | 1.13 | 4/4 |
| vwap_z | REV | GBPJPY | H1 | 5 | +0.0792 | +7.7 | 1.10 | 4/4 |
| orb_break | MOM | BTCUSD | M15 | 12 | -0.0628 | -6.5 | 1.30 | 4/4 |
| boll_z | REV | UK100 | H1 | 5 | +0.0389 | +5.7 | 1.11 | 4/4 |
| vwap_z | REV | BTCUSD | H1 | 5 | +0.0611 | +6.1 | 1.68 | 4/4 |
| rv_ratio | VOL | UK100 | M15 | 24 | -0.0462 | -5.6 | 1.46 | 4/4 |
| boll_z | REV | UK100 | H1 | 5 | +0.0399 | +5.6 | 1.13 | 4/4 |
| session_move | MOM | US100 | M5 | 12 | +0.0447 | +5.8 | 1.44 | 4/4 |
| orb_break | MOM | GBPJPY | H1 | 5 | -0.0761 | -5.4 | 1.06 | 4/4 |
| orb_break | MOM | BTCUSD | H1 | 5 | -0.0756 | -5.6 | 2.08 | 4/4 |
| orb_break | MOM | BTCUSD | M15 | 12 | -0.0510 | -5.2 | 1.06 | 4/4 |
| atr_ratio | VOL | UK100 | M15 | 24 | -0.0491 | -5.2 | 1.55 | 4/4 |
| session_move | MOM | US100 | M15 | 5 | +0.0413 | +5.2 | 1.42 | 4/4 |
| atr_band_z | REV | UK100 | H1 | 5 | +0.0381 | +5.1 | 1.08 | 4/4 |
| session_move | MOM | US100 | M5 | 24 | +0.0568 | +5.4 | 2.57 | 4/4 |
| rsi_dev | REV | UK100 | H1 | 5 | +0.0369 | +5.0 | 1.05 | 4/4 |
| rsi_dev | REV | UK100 | H1 | 5 | +0.0376 | +4.9 | 1.07 | 4/4 |
| session_move | MOM | US100 | M15 | 12 | +0.0555 | +4.9 | 2.93 | 4/4 |
| atr_ratio | VOL | UK100 | M15 | 24 | -0.0444 | -5.1 | 1.40 | 4/4 |
| orb_break | MOM | BTCUSD | M15 | 24 | -0.0520 | -4.6 | 1.50 | 4/4 |

## Ce que le critere de stabilite attrape, et ce qu'il laisse passer

Le mandat demande un SIGNE constant sur >= 3 sous-periodes. Un signe constant n'est pas une amplitude constante : un IC qui passe de 0,086 a 0,004 garde son signe et franchit le critere. Le tableau ci-dessous mesure l'ampleur reelle de cette faille.


| \|IC\| du dernier quart / du premier | part des cellules sous la porte |
|---|--:|
| mediane | 0.87 |
| sous 50% | 15.5 % |
| sous 25% | 5.6 % |
| sous 10% | 1.7 % |
| plus fort a la fin qu'au debut | 37.5 % |

La faille existe mais elle est **etroite** : 5.6 % des cellules ont un dernier quart sous le quart du premier, et 38 % sont au contraire plus fortes a la fin. Le critere de signe n'est donc pas le maillon faible de cette porte -- le peage l'est.


## Signe pre-enregistre

Chaque famille annonce le SENS de son mecanisme avant la mesure. Une cellule qui ressort au signe oppose n'a pas trouve le contraire : elle a refute son mecanisme. La porte du mandat portant sur `|IC|`, elle ne fait pas la difference — d'ou ce tableau.

| famille | cellules | signe conforme | \|IC\| median si conforme | si oppose |
|---|--:|--:|--:|--:|
| cross_asset_lead_lag | 5800 | 64 % | 0.0138 | 0.0096 |
| intraday_momentum_breakout | 7100 | 20 % | 0.0077 | 0.0159 |
| mean_reversion_extreme | 7200 | 84 % | 0.0175 | 0.0069 |
| microstructure_session_seasonality | 3800 | 50 % | 0.0081 | 0.0070 |
| volatility_skew_dynamics | 4400 | 54 % | 0.0068 | 0.0057 |
