---
type: experiment
id: exp-015
updated: 2026-08-13
status: done
verdict: no-edge
horizon: intraday M5 / M15, expiration = fin exacte d'une fenêtre de 30-60 min
universe: NAS100, US500, US30, GER40, XAUUSD, EURUSD, GBPUSD, USDJPY, GBPAUD (+ FRA40 en 2ᵉ jambe)
code: [kzlab/config.py, kzlab/killzone.py, kzlab/statarb.py, kzlab/labeling.py, kzlab/run.py, kzlab/validate.py, kzlab/report.py, kzlab/export_model.py, kzlab/test_kz.py, live_ml_execution_phase4.py, check_live_parity_phase4.py]
---

# exp-015 — Phase 4 : micro-killzones temporelles & arbitrage statistique intraday

**Hypothèse.** (1) Le flux d'ordres institutionnel se concentre dans des fenêtres de
30 à 60 minutes (ouverture US, chevauchement Londres/NY, fixing de Londres), et
l'expansion de volatilité qu'il produit y **compense le spread**. (2) La réversion à
la moyenne d'un spread cointégré entre deux actifs corrélés est plus prévisible que
la direction d'un actif isolé.

**Setup.** 224 532 cellules, 738 modèles (2 952 ajustements), 9 actifs × 2 UT × 3
killzones + 5 paires × 2 UT × 3 fenêtres de z, 44,1 M de barres M1 Pepperstone.
Étiquetage triple barrière relu **dans** le moteur de brackets, barrière verticale =
fin exacte de la killzone, K-fold purgé + embargo 1 j + bande de purge 5 j, sélection
sur l'IS 70 % seul, lecture unique de l'OOS, BH-FDR q ≤ 0,10. Grille rejouée
intégralement **à coût nul** (449 064 cellules au total). Détails et code :
[`rapport_quant_phase4_pepperstone.md`](../../rapport_quant_phase4_pepperstone.md).

**Result. ZÉRO survivant FDR** sur 217 cellules gelées, **q_min 0,9992** — la plus
mauvaise marge des quatre phases. Test poolé sur les 4 indices : 0 survivant,
q_pool 0,982, t journalier max 0,83. Meilleur candidat isolé (NAS100 M15 `us_open`
short, +32,9 R OOS, PF 2,53) : **39 trades sur 2,6 ans**, p brute 0,034 → q 0,999.

Le contrôle à coût nul est ce qui donne sa valeur à la phase :

| | % E[R] OOS > 0 | Médiane E[R] OOS | Péage médian | **Bord brut / péage** |
|---|---|---|---|---|
| Killzones, brut | **51,9 %** | **+0,0021 R** | 0,076-0,093 R | **0,002-0,026** |
| Arbitrage, brut | 65,6 % | **+0,0682 R** | 0,46-1,23 R | 0,007-**0,313** |

**Verdict.** ❌ Pas de bord. **Mais les deux familles meurent de causes
différentes, et c'est le résultat.**

1. ⭐⭐ **Les killzones n'ont pas de bord directionnel, MÊME GRATUITES.** 51,9 % de
   cellules positives à coût nul = pile ou face. La prémisse du mandat est fausse
   dans son *premier* terme : l'expansion de volatilité est bien là (l'ATR propre de
   la fenêtre vaut 3 à 5 × l'ATR moyen) mais elle n'apporte **aucune direction**. Une
   fenêtre où le prix bouge beaucoup n'est pas une fenêtre où l'on sait dans quel
   sens. Confirmé par le découpage de régime : `expand` −0,134 vs `quiet` −0,131 R,
   soit **0,003 R d'écart**.
2. ⭐⭐ **L'arbitrage intraday, lui, A un vrai bord brut — il manque un facteur 7,5
   MÊME SANS AUCUN SLIPPAGE.** Au bracket du mandat : **+0,097 R en moyenne par
   trade** (médiane par trade **−0,95 R** — 41 % de réversions à ~+2R contre 59 % de
   stops, donc le trade médian *est* un stop et seule la moyenne décrit le P&L ;
   +0,068 R en médiane par *cellule* de grille), AUC 0,57 (max 0,656). Sur 17 223
   cellules, **7** (0,04 %) ont une espérance IS positive nette, **aucune** ne passe
   les critères de gel. ⭐ **Re-tarifé sous 3 modèles de coût** (`kzlab/cost_audit.py`)
   après contestation du barème : la convention « 0,5 pip » du mandat est bel et bien
   incohérente entre indices (1,28 bp sur US500 contre 0,185 bp sur US30, facteur 7,
   et le slippage pèse 33-71 % du total) — mais au **plancher absolu** (spread +
   commission, **zéro slippage**) le péage vaut encore 0,72 R contre 0,097 R de bord,
   soit un facteur **7,5**, et **0 couple sur 10** devient tradable sous l'un
   quelconque des trois modèles. Ceci **complète** [[exp-011-phase2-vol-pair-squeeze]]
   (qui avait le coût mais pas le numérateur) et ferme la famille.
3. ⭐⭐ **AUC OOS 0,69 (max 0,816, 98,8 % des modèles > 0,60) et zéro R.** Dans
   **69,3 % des 648 modèles**, l'AUC « une barrière est touchée » dépasse l'AUC
   « laquelle » de **+0,052** en médiane (jusqu'à 0,809 vs 0,689 sur `overlap` M5).
   **Troisième confirmation consécutive** après [[exp-012-phase3-sweep-tbm-abrk]] et
   [[exp-013-triple-barrier-ml-dedie]] : à traiter comme un fait établi, plus comme
   une hypothèse.
4. ⭐⭐ **Le Spearman IS→OOS net est un piège, désormais démontré deux fois.**
   +0,776 net → **+0,104 brut**, et **−0,056** pour la famille killzone seule, soit
   au millième près la valeur de la Phase 1. Le meilleur décile IS est **moins bon**
   OOS que le neuvième : la monotonie décrit le péage et se brise au seul endroit où
   l'on voudrait s'en servir.
5. ❌ **Le ML n'ajoute rien.** À coût nul, le témoin `model = none` (tous les trades
   de la fenêtre) fait aussi bien ou mieux : M15 médiane **+0,0031 R sans modèle**
   contre **−0,0003 R avec**.
6. ⭐ **Le « −1R » de la famille 2 n'en est pas un** — trouvé en écrivant une
   assertion de test qui s'est révélée fausse. La barrière est un z lu sur des
   clôtures M1, la sortie est à l'open **suivant**, et R vaut `(z_stop − z) × σ` avec
   un σ **gelé** de 30 à 120 bougies : quand la fenêtre était calme, une minute de
   marché vaut plusieurs R. Le stop médian est correctement centré (−1,01 à −1,25 R)
   mais **40 à 51 % des trades le dépassent**, 1ᵉʳ centile −1,7 à −4,0 R, pire cas
   **−27,5 R**. Le dépassement se resserre de façon monotone quand la fenêtre de z
   s'allonge, ce qui confirme le mécanisme. Les espérances du point 2 sont donc
   **sous-estimées**, et c'est une 3ᵉ raison indépendante de ne pas armer la famille.

**Why it matters / next.**

* ⭐ **Un outil réutilisable : dimensionner R sur l'ATR LOCAL DE LA FENÊTRE.** La
  moyenne de Wilder des amplitudes passées de la killzone elle-même divise le péage
  par **3 à 5** par rapport à l'ATR14 de l'UT, et le rend **quasi indépendant de
  l'unité de temps** (0,107 R en M5 comme en M15 sur EURUSD). Prolonge le résultat
  d'[[exp-012-phase3-sweep-tbm-abrk]] : le choix du stop est un levier de coût plus
  puissant que le choix du signal.
* **Renforce la synthèse d'[[exp-014-six-pistes-ml-edge]] :** péage médian d'une
  cellule killzone 0,08-0,14 R contre 0,002 R de bord brut médian — un rapport de 1 à
  50. Le levier n'est pas dans le réglage, il est dans l'**horizon** (les 3 briques du
  book vivent en D1) ou dans la **largeur**.
* **Live livré et prouvé, mais désarmé.** [`live_ml_execution_phase4.py`](../../live_ml_execution_phase4.py)
  (deux exécuteurs `mt5.order_send`) + [`check_live_parity_phase4.py`](../../check_live_parity_phase4.py).
  Parité killzone **OK** sur 464 jours convergés. Deux découvertes d'ingénierie :
  (a) la récursion la plus lente n'est pas l'ATR(100) de l'UT mais **l'ATR de Wilder
  JOURNALIER** — à 200 k barres M1 la parité échoue, `LOOKBACK_M1` est passé à 600 k ;
  (b) plafonner **une seule jambe** d'un spread transforme la couverture en pari
  directionnel — les deux jambes sont désormais mises à l'échelle par un facteur
  commun. Parité arbitrage **ÉCHOUE** (0,9 % des points) : `gridlab.pairs._roll_stats`
  est mal conditionné sous un ancrage différent ; non corrigé, la famille étant morte.

**Links.** [[exp-010-intraday-grid-search-3-families]], [[exp-011-phase2-vol-pair-squeeze]],
[[exp-012-phase3-sweep-tbm-abrk]], [[exp-013-triple-barrier-ml-dedie]],
[[exp-014-six-pistes-ml-edge]], [[triple-barrier]], [[walk-forward-embargo]],
[[leakage]], [[prop-firm-universe]], [[ledger]].
