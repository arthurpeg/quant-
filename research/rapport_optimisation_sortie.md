# Etape 7 -- optimiser la sortie des deux configurations robustes

_Genere le 2026-08-18 01:45 -- stop initial et largeur de trailing a 2.0 x ATR14, seuil pre-enregistre q = 0.9._


> **Ce que ce rapport ne peut pas prouver.** Les deux configurations testees sont le sommet d'une grille de 2 595 ([[exp-022]]). Optimiser leur sortie sur elles-memes est de l'in-sample sur de l'in-sample : un gain y est attendu meme si la regle ne vaut rien. **La partie B est donc le seul chiffre qui decide**, et elle applique les memes variantes aux 173 cellules.


## A. Les deux configurations


### `vwap_z` GER40 H1 k=24

| variante | origine | E[R] net | E[R] brut | taux de sortie au stop | PF | N | maxDD R | moitie 1 | moitie 2 | sens inverse |
|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| dur 2,0x (reference) | reference | **+0.1281** | +0.1404 | 47.1 % | 1.247 | 1043 | -23.5 | +0.138 | +0.118 | -0.173 |
| Chandelier 5 barres | reference | **+0.0477** | +0.0599 | 95.4 % | 1.142 | 1227 | -20.5 | +0.056 | +0.040 | -0.013 |
| Chandelier 5 b. retarde +1R | mandat 1 | **+0.1153** | +0.1276 | 80.3 % | 1.262 | 1147 | -19.9 | +0.158 | +0.073 | -0.117 |
| Chandelier 10 barres | mandat 2 | **+0.0313** | +0.0435 | 96.1 % | 1.104 | 1305 | -19.7 | +0.040 | +0.022 | -0.005 |
| Chandelier 15 barres | mandat 2 | **+0.0203** | +0.0325 | 96.9 % | 1.077 | 1408 | -22.9 | +0.024 | +0.017 | -0.003 |
| Chandelier 20 barres | mandat 2 | **+0.0191** | +0.0313 | 97.1 % | 1.075 | 1441 | -21.9 | +0.016 | +0.022 | -0.003 |
| Chandelier 10 b. retarde +1R | combinaison | **+0.1153** | +0.1276 | 80.3 % | 1.262 | 1147 | -19.8 | +0.157 | +0.074 | -0.117 |
| Chandelier 20 b. retarde +1R | combinaison | **+0.1123** | +0.1246 | 80.3 % | 1.256 | 1150 | -21.9 | +0.148 | +0.076 | -0.117 |

### `orb_break` US100 H1 k=12

| variante | origine | E[R] net | E[R] brut | taux de sortie au stop | PF | N | maxDD R | moitie 1 | moitie 2 | sens inverse |
|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| dur 2,0x (reference) | reference | **+0.1153** | +0.1381 | 35.5 % | 1.276 | 908 | -14.3 | +0.128 | +0.103 | -0.136 |
| Chandelier 5 barres | reference | **+0.0689** | +0.0919 | 70.6 % | 1.195 | 1005 | -15.7 | +0.072 | +0.065 | -0.063 |
| Chandelier 5 b. retarde +1R | mandat 1 | **+0.1032** | +0.1259 | 52.0 % | 1.261 | 943 | -15.5 | +0.094 | +0.112 | -0.146 |
| Chandelier 10 barres | mandat 2 | **+0.0695** | +0.0925 | 71.1 % | 1.196 | 1005 | -15.6 | +0.073 | +0.066 | -0.059 |
| Chandelier 15 barres | mandat 2 | **+0.0696** | +0.0926 | 71.1 % | 1.197 | 1005 | -15.6 | +0.073 | +0.066 | -0.058 |
| Chandelier 20 barres | mandat 2 | **+0.0707** | +0.0937 | 71.5 % | 1.203 | 1009 | -14.7 | +0.072 | +0.069 | -0.058 |
| Chandelier 10 b. retarde +1R | combinaison | **+0.1034** | +0.1262 | 52.1 % | 1.261 | 943 | -15.5 | +0.094 | +0.112 | -0.142 |
| Chandelier 20 b. retarde +1R | combinaison | **+0.1037** | +0.1264 | 52.1 % | 1.263 | 944 | -15.5 | +0.093 | +0.115 | -0.135 |

### Robustesse au seuil d'entree

Le seuil q = 0,90 est le seul pre-enregistre. Les deux autres sont rendus pour que le choix ne se fasse pas en silence.


| configuration | variante | q=0,80 | q=0,90 | q=0,95 |
|---|---|--:|--:|--:|
| vwap_z GER40 | dur 2,0x (reference) | +0.0732 | +0.1281 | +0.1085 |
| vwap_z GER40 | Chandelier 5 barres | +0.0228 | +0.0477 | +0.0518 |
| vwap_z GER40 | Chandelier 5 b. retarde +1R | +0.0576 | +0.1153 | +0.1003 |
| vwap_z GER40 | Chandelier 10 barres | +0.0020 | +0.0313 | +0.0374 |
| vwap_z GER40 | Chandelier 15 barres | -0.0019 | +0.0203 | +0.0318 |
| vwap_z GER40 | Chandelier 20 barres | -0.0033 | +0.0191 | +0.0350 |
| vwap_z GER40 | Chandelier 10 b. retarde +1R | +0.0571 | +0.1153 | +0.1010 |
| vwap_z GER40 | Chandelier 20 b. retarde +1R | +0.0550 | +0.1123 | +0.0977 |
| orb_break US100 | dur 2,0x (reference) | +0.0628 | +0.1153 | +0.1242 |
| orb_break US100 | Chandelier 5 barres | +0.0257 | +0.0689 | +0.0976 |
| orb_break US100 | Chandelier 5 b. retarde +1R | +0.0530 | +0.1032 | +0.1047 |
| orb_break US100 | Chandelier 10 barres | +0.0267 | +0.0695 | +0.0984 |
| orb_break US100 | Chandelier 15 barres | +0.0248 | +0.0696 | +0.0984 |
| orb_break US100 | Chandelier 20 barres | +0.0265 | +0.0707 | +0.0970 |
| orb_break US100 | Chandelier 10 b. retarde +1R | +0.0533 | +0.1034 | +0.1050 |
| orb_break US100 | Chandelier 20 b. retarde +1R | +0.0537 | +0.1037 | +0.1050 |

## B. Le controle qui decide : les memes sorties sur les 173 cellules

Si le Chandelier retarde ameliore l'esperance **sur les 173 cellules**, c'est une propriete de la regle de sortie et elle se transportera. S'il n'ameliore que les deux cellules deja selectionnees, c'est de l'ajustement.


| variante | origine | cellules | E[R] net median | ecart vs stop dur | % cellules ameliorees | taux de stop median | PF median |
|---|---|--:|--:|--:|--:|--:|--:|
| dur 2,0x (reference) | reference | 173 | **-0.0749** | +0.0000 | 22.5 % | 40.3 % | 0.822 |
| Chandelier 5 barres | reference | 173 | **-0.0572** | +0.0177 | 73.3 % | 91.0 % | 0.752 |
| Chandelier 5 b. retarde +1R | mandat 1 | 173 | **-0.0897** | -0.0148 | 39.7 % | 53.4 % | 0.798 |
| Chandelier 10 barres | mandat 2 | 173 | **-0.0390** | +0.0359 | 78.1 % | 97.2 % | 0.779 |
| Chandelier 15 barres | mandat 2 | 173 | **-0.0355** | +0.0394 | 80.0 % | 98.5 % | 0.787 |
| Chandelier 20 barres | mandat 2 | 173 | **-0.0337** | +0.0412 | 80.0 % | 98.9 % | 0.796 |
| Chandelier 10 b. retarde +1R | combinaison | 173 | **-0.0870** | -0.0121 | 41.6 % | 55.5 % | 0.801 |
| Chandelier 20 b. retarde +1R | combinaison | 173 | **-0.0892** | -0.0143 | 43.2 % | 60.4 % | 0.798 |

### Le gain de la partie B est-il de l'alpha, ou de la troncature ?

Une regle de sortie qui **coupe plus tot** ameliore mecaniquement une cellule perdante -- elle lui retire de la perte -- sans rien apporter. Le test qui separe les deux tient en une correlation : si le gain d'une variante est d'autant plus grand que la cellule etait MAUVAISE, ce n'est pas de l'alpha, c'est de la troncature.


| variante | Spearman(E[R] de reference, gain) | gain median sur les cellules NEGATIVES | sur les cellules POSITIVES | cellules positives restees positives |
|---|--:|--:|--:|--:|
| Chandelier 5 barres | **-0.838** | +0.0301 | **-0.0767** | 7/27 |
| Chandelier 5 b. retarde +1R | **-0.387** | -0.0017 | **-0.0222** | 13/27 |
| Chandelier 10 barres | **-0.897** | +0.0480 | **-0.0610** | 6/27 |
| Chandelier 15 barres | **-0.915** | +0.0517 | **-0.0600** | 5/27 |
| Chandelier 20 barres | **-0.921** | +0.0542 | **-0.0599** | 5/27 |
| Chandelier 10 b. retarde +1R | **-0.469** | -0.0009 | **-0.0222** | 13/27 |
| Chandelier 20 b. retarde +1R | **-0.467** | -0.0006 | **-0.0222** | 12/27 |

**Lecture.** Le Chandelier a fenetre elargie affiche la meilleure mediane de la partie B, et c'est un artefact : sa correlation gain / qualite de depart vaut **-0,92**, il gagne **+0,054 R sur les cellules perdantes** et **perd -0,060 R sur les gagnantes**, dont **5 sur 27 seulement restent positives**. Il comprime tout vers zero : il sauve les perdantes et detruit les gagnantes. Le Chandelier **retarde**, lui, est bien moins destructeur (13 gagnantes sur 27 survivent) sans rien apporter non plus.


### Pourquoi elargir la fenetre RESSERRE le trailing

C'est de l'algebre, pas un resultat d'echantillon : le maximum sur 20 barres est **toujours** superieur ou egal au maximum sur 5, donc `max(H, 20) - m x ATR` est un stop **plus haut**, donc **plus proche du prix** pour un achat. Elargir la fenetre ne lisse pas le trailing -- elle le fait cliqueter plus haut et plus vite. Le taux de sortie au stop le confirme : **91 %** a 5 barres, **99 %** a 20 barres sur les 173 cellules. Le levier qui rend un trailing MOINS reactif est donc la fenetre COURTE, ou un multiple d'ATR plus grand -- pas l'inverse.


## Verdict

- **Aucune des deux optimisations n'ameliore les deux configurations.** Le meilleur E[R] reste celui du **stop dur a 2.0 x ATR14 sans trailing** (+0.1281 R).
- Le **Chandelier retarde a +1R** coute environ 0,01 R d'esperance sur les deux configurations, mais **ameliore le Profit Factor** sur `vwap_z` GER40 (1,262 contre 1,247) en divisant par pres de deux le recours au stop initial.
- La **fenetre elargie degrade franchement** les deux configurations (-0,06 a -0,11 R) : elle resserre le trailing au lieu de le relacher.
- Aucune variante ne porte l'esperance a 0.18 R. Le maximum des deux configurations vaut **+0.1281 R**.

**La partie B contredit la partie A, et c'est le resultat.** Sur les 173 cellules le Chandelier elargi semble le meilleur ; sur les deux cellules effectivement rentables il est le pire. La mediane d'une grille majoritairement perdante recompense ce qui coupe les pertes, pas ce qui capture un bord.
