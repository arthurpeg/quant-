---
type: experiment
id: exp-023
updated: 2026-08-18
status: done
verdict: no-edge
horizon: H1, k = 12 et 24
universe: vwap_z GER40 H1 k=24 et orb_break US100 H1 k=12
code: [research/scripts/07_exit_optimization.py]
---

# exp-023 — Optimiser la sortie des deux configurations robustes

**Hypothesis.** Mandat utilisateur, suite d'[[exp-022-geometrie-de-sortie]] :
sur les deux seules configurations qui tenaient tous les controles, tester deux
optimisations de sortie — **Chandelier retarde** (trailing arme seulement apres
un gain latent de +1,0R, stop initial 2,0 x ATR14) et **fenetre d'extreme
elargie** (10 / 15 / 20 barres au lieu de 5).

**Setup.** [`research/scripts/07_exit_optimization.py`](../../research/scripts/07_exit_optimization.py).
**Partie A** : les 2 configurations x 8 variantes x 3 seuils. **Partie B, le
controle** : les memes 8 variantes sur les **173 cellules**, au seul seuil
pre-enregistre — parce que les deux configurations sont le sommet d'une grille
de 2 595 et qu'optimiser leur sortie sur elles-memes est de l'in-sample sur de
l'in-sample. Rapport :
[`rapport_optimisation_sortie.md`](../../research/rapport_optimisation_sortie.md).

**Result.**

⭐⭐⭐ **LES DEUX PARTIES SE CONTREDISENT, ET C'EST LE RESULTAT.** Sur les 173
cellules, le Chandelier a fenetre elargie est **la meilleure** variante
(E[R] median −0,034 contre −0,075 pour le stop dur, **+0,041**, 80 % de cellules
ameliorees). Sur les deux cellules effectivement RENTABLES, il est **la pire**
(`vwap_z` GER40 passe de +0,128 a +0,019). La mediane d'une grille
majoritairement perdante recompense ce qui coupe les pertes, pas ce qui capture
un bord.

⭐⭐⭐ **LE GAIN DE LA PARTIE B EST DE LA TRONCATURE, ET LA CORRELATION LE PROUVE.**
Le gain d'une variante est d'autant plus grand que la cellule etait mauvaise :

| variante | Spearman(E[R] de depart, gain) | cellules negatives | cellules positives | positives restees positives |
|---|--:|--:|--:|--:|
| Chandelier 5 barres | −0,838 | +0,030 | **−0,077** | 7/27 |
| Chandelier 10 barres | −0,897 | +0,048 | **−0,061** | 6/27 |
| Chandelier 15 barres | −0,915 | +0,052 | **−0,060** | 5/27 |
| **Chandelier 20 barres** | **−0,921** | **+0,054** | **−0,060** | **5/27** |
| **Chandelier 5 b. retarde +1R** | **−0,387** | −0,002 | **−0,022** | **13/27** |

Le Chandelier elargi **comprime tout vers zero** : il sauve les perdantes et
detruit les gagnantes (5 sur 27 survivent). Le Chandelier **retarde** est deux
fois moins destructeur (13 sur 27) — sans rien apporter non plus.

⭐⭐⭐ **ELARGIR LA FENETRE D'EXTREME RESSERRE LE TRAILING — c'est de l'algebre,
pas un resultat d'echantillon.** Le maximum sur 20 barres est **toujours** >= le
maximum sur 5, donc `max(H, 20) − m x ATR` est un stop **plus haut**, donc plus
proche du prix pour un achat. Une fenetre large ne lisse pas le trailing : elle
le fait **cliqueter plus haut et plus vite**. Taux de sortie au stop sur les 173
cellules : **91 % a 5 barres, 97 % a 10, 98 % a 15, 99 % a 20**. La premisse du
mandat (« fenetre elargie = trailing moins reactif ») est donc inversee, et le
levier qui relache reellement un trailing est la fenetre **courte** ou un
multiple d'ATR plus grand.

⭐⭐ **AUCUNE DES DEUX OPTIMISATIONS N'AMELIORE LES DEUX CONFIGURATIONS.** Le
meilleur E[R] reste celui du **stop dur a 2,0 x ATR14 sans trailing** :

| configuration | sortie | E[R] net | taux de stop | PF | N |
|---|---|--:|--:|--:|--:|
| `vwap_z` GER40 H1 k=24 | **dur 2,0x** | **+0,128** | 47,1 % | 1,247 | 1 043 |
| | Chandelier retarde +1R | +0,115 | 80,3 % | **1,262** | 1 147 |
| | Chandelier 20 barres | +0,019 | 97,1 % | 1,075 | 1 441 |
| `orb_break` US100 H1 k=12 | **dur 2,0x** | **+0,115** | 35,5 % | **1,276** | 908 |
| | Chandelier retarde +1R | +0,103 | 52,0 % | 1,261 | 943 |
| | Chandelier 20 barres | +0,071 | 71,5 % | 1,203 | 1 009 |

⭐ **Le seul apport reel du Chandelier retarde est le Profit Factor de `vwap_z`**
(1,262 contre 1,247) : il divise par pres de deux le recours au stop initial et
coute 0,013 R d'esperance. C'est un arbitrage, pas un gain.

⭐ Auto-tests **5/5**, dont la parite exacte avec le moteur d'[[exp-022-geometrie-de-sortie]]
quand le retard est desactive, et le cas « la barre touche +1,5R **puis** le
stop » qui doit rendre −1R plein (supposer l'inverse offrirait gratuitement le
meilleur des deux ordres possibles).

**Verdict.** ❌ **no-edge.** Les deux optimisations demandees sont refutees :
l'une par le controle de generalisation (troncature, pas alpha), l'autre par
l'algebre (elle fait le contraire de ce qu'on attendait d'elle). La meilleure
sortie connue pour ces deux configurations reste la plus simple :
**stop dur 2,0 x ATR14 + barriere de temps**, a +0,128 R et +0,115 R — toujours
sous la porte de 0,18 R.

**Why it matters / next.** Acquis reutilisable : **la mediane d'une grille
majoritairement perdante ne mesure pas la qualite d'une regle de sortie.** Toute
comparaison de sorties doit se lire separement sur les cellules gagnantes et
perdantes, sinon elle recompense la troncature. Le fil `vwap_z` GER40 /
`orb_break` US100 reste ouvert mais aucune geometrie testee (5 largeurs, 2
mecaniques, 3 fenetres, armement retarde) ne le porte a 0,18 R.

**Links.** [[exp-022-geometrie-de-sortie]], [[exp-021-backtest-r-multiples]],
[[exp-020-porte-ic-moisson-automatisee]], [[triple-barrier]], [[ledger]].
