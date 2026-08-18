---
type: experiment
id: exp-021
updated: 2026-08-18
status: done
verdict: no-edge
horizon: M5 / M15 / H1 / H4, sortie a k barres (k = 5 a 24)
universe: 13 actifs portant les 173 cellules retenues en phase 1
code: [research/scripts/05_vectorized_backtester.py]
---

# exp-021 — Phase 2 : les 173 cellules de la porte IC passees au stop dur

**Hypothesis.** Mandat utilisateur : transformer les 173 cellules validees en
phase 1 (k >= 5 ET bord/peage >= 1,0) en strategies concretes en R-multiples,
et mesurer leur esperance nette. 1R = 1,5 x ATR14, sortie a k barres ou au stop,
variantes de cible a +2R / +3R, peage Pepperstone complet. Porte :
`E[R] >= 0,18` ET `N >= 100` ET `PF >= 1,25`.

**Setup.** [`research/scripts/05_vectorized_backtester.py`](../../research/scripts/05_vectorized_backtester.py),
**1 557 configurations** = 173 cellules x 3 seuils d'entree x 3 regles de sortie.
Le seuil d'entree **n'existait pas en phase 1** (la porte IC portait sur un
signal continu) : il est cree ici comme rang causal de S_t sur ses 1 000
dernieres occurrences, **pre-enregistre a q = 0,90**, avec 0,80 et 0,95 en
robustesse. Une position a la fois, gaps honores, stop prioritaire sur la cible.
Rapport : [`rapport_backtest_R.md`](../../research/rapport_backtest_R.md).

**Result.**

⭐⭐⭐ **ZERO strategie validee sur 1 557, et la contrainte qui mord est
l'ESPERANCE seule.** `N >= 100` passe **1 557 / 1 557**, `PF >= 1,25` passe
**12 / 1 557**, `E[R] >= 0,18` passe **0**. Le maximum global vaut **0,1780 R**
— 99 % de la porte, manquee de 0,002 R.

⭐⭐⭐ **LE STOP DUR N'AFFAIBLIT PAS LE BORD, IL L'ANNULE.** Chaque entree a ete
resolue **dans les deux sens**, peage et geometrie constants. Le bord
**directionnel** median vaut **+0,0024 R**, positif dans **52,0 %** des
configurations — un pile ou face. La derive geometrie + peage vaut **−0,1106 R**.
La phase 1 mesurait un IC **sans stop** sur ces memes cellules ; avec un stop a
1,5 x ATR14 il n'en reste **rien en moyenne**. C'est [[exp-017-xsection-fx-intraday]]
reproduit sur une famille entierement differente.

⭐⭐⭐ **LA GEOMETRIE PERD AVANT LE PREMIER CENTIME DE FRAIS** : E[R] **brut**
median **−0,0591 R** pour un peage median de **0,0456 R**. Ce n'est donc PAS
l'histoire de la phase 1 (« le bord existe mais le peage le mange ») : ici le
bracket lui-meme est perdant, parce que les gaps font payer **pire que −1R** et
que la barriere de temps coupe sans compensation.

⭐⭐ **L'EFFET DE SELECTION DU SEUIL, CHIFFRE.** Le maximum de 0,1780 R vient de
**q = 0,95, qui n'etait pas pre-enregistre**. **Au seuil pre-enregistre q = 0,90
le meilleur E[R] tombe a 0,1211 R, soit 67 % de la porte.** L'ecart entre les
deux (+47 %) est exactement le prix d'un degre de liberte qu'on s'autorise apres
coup.

⭐⭐ **LE SEUL INDICE POSITIF : quatre cellules ordonnent leur E[R] de facon
MONOTONE avec la selectivite de l'entree**, sur un axe qui n'a servi a rien
d'autre, **et sont positives dans les deux moities chronologiques** :

| cellule (sortie temps) | q=0,80 | q=0,90 | q=0,95 | moitie 1 | moitie 2 | N |
|---|--:|--:|--:|--:|--:|--:|
| `orb_break` US100 H1 k=12 | +0,056 | +0,118 | +0,157 | +0,188 | +0,126 | 519 |
| `fix_window` US500 M15 k=24 | +0,031 | +0,065 | +0,138 | +0,181 | +0,095 | 782 |
| `vwap_z` GER40 H1 k=24 | +0,080 | +0,117 | +0,109 | +0,086 | +0,133 | 674 |
| `fix_window` US100 M15 k=24 | +0,034 | +0,070 | +0,112 | +0,143 | +0,081 | 1 094 |

Du bruit ne s'ordonne pas ainsi. Aucune ne franchit la porte, et **172 / 1 557
configurations seulement** sont positives dans les deux moities (28 cellules
distinctes) — mais ces quatre-la cumulent monotonie, deux moities positives et
un temoin de sens franchement negatif.

⭐⭐ **UN DEFAUT DE MOTEUR ATTRAPE PAR LES AUTO-TESTS, ET IL AURAIT SUPPRIME 39 %
DE LA GRILLE EN SILENCE.** Le rang d'entree glissait sur 1 000 **BARRES** avec
500 minimum ; un signal de SESSION n'est defini que sur ~25 % des barres, donc
aucune fenetre n'atteignait jamais 500 valeurs et le rang sortait **entierement
NaN** — ces cellules rendaient zero configuration sans lever d'erreur. La fenetre
compte desormais les **occurrences** du signal. Les familles de session pesent
**603 configurations sur 1 557**. Un 8ᵉ auto-test verrouille le cas.

⭐ Les auto-tests du moteur (8/8) couvrent : stop touche = −1R exact, **gap sous
le stop = pire que −1R**, cible atteinte, **stop prioritaire quand les deux sont
touches dans la meme barre**, symetrie long/court sur serie miroir, regle
d'occupation, causalite du seuil, et le cas des signaux epars.

**Verdict.** ❌ **no-edge.**
[`research/validated_strategies.json`](../../research/validated_strategies.json)
porte une liste **vide**, et c'est le resultat. Les 173 cellules avaient un IC
reel et un rapport bord/peage superieur a 1 ; elles ne survivent pas au stop
obligatoire.

**Why it matters / next.** Le chainage phase 1 → phase 2 a fonctionne comme
mesure : il a **isole ou meurt le bord**. Ce n'est ni la significativite (elle
etait la), ni le peage (0,046 R contre un brut de −0,059 R) — c'est la
**geometrie du bracket a stop dur**. La suite utile n'est donc pas une autre
grille de signaux mais une autre **geometrie de sortie** : le meme jeu de 173
cellules avec une sortie qui ne tronque pas (barriere de temps seule, sans stop,
ou stop bien plus large), pour voir si le +0,0024 R directionnel remonte. Et
`orb_break` US100 H1 reste le seul fil a tirer.

**Links.** [[exp-020-porte-ic-moisson-automatisee]], [[exp-017-xsection-fx-intraday]],
[[exp-019-propresearch-ic-gate]], [[triple-barrier]],
[[information-coefficient-and-ir]], [[ledger]].
