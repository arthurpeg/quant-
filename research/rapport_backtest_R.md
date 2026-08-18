# Phase 2 -- backtest vectorise en R-multiples

_Genere le 2026-08-18 01:05 -- 1R = 1.5 x ATR14, peage Pepperstone mesure, une position a la fois._


## Ce qui a ete teste

- **173** cellules heritees de la phase 1 (k >= 5 ET bord/peage >= 1,0).
- x 3 seuils d'entree x 3 regles de sortie = **1557** configurations effectivement mesurees.
- Porte : `E[R] >= 0.18` ET `N >= 100` ET `PF >= 1.25`.


## Le compte

| etape | configurations restantes |
|---|--:|
| mesurees | 1557 |
| porte E[R] / N / PF | **0** |
| + survivantes BH-FDR (q <= 0.1) | 0 |
| − dont les DEUX sens gagnent (geometrie, pas bord) | −0 |
| moins dont E[R] negatif dans une moitie de l'histoire | -0 |
| **retenues** | **0** |

## Ce que le stop dur fait au bord

La phase 1 mesurait un IC **sans stop**. Ici chaque trade porte un stop a 1.5 x ATR14. La comparaison brut / net et le temoin de sens disent ce qu'il en reste.


| sortie | configs | E[R] brut median | E[R] net median | peage median (R) | passent la porte |
|---|--:|--:|--:|--:|--:|
| time | 519 | -0.0667 | -0.1128 | 0.0455 | 0 |
| tp2 | 519 | -0.0484 | -0.0943 | 0.0456 | 0 |
| tp3 | 519 | -0.0607 | -0.1069 | 0.0456 | 0 |

| UT | configs | E[R] net median | peage median (R) | passent |
|---|--:|--:|--:|--:|
| M5 | 81 | -0.0833 | 0.0383 | 0 |
| M15 | 297 | -0.1641 | 0.0645 | 0 |
| H1 | 648 | -0.1159 | 0.0473 | 0 |
| H4 | 531 | -0.0727 | 0.0239 | 0 |

## Le resultat central : le stop dur annule le bord

Chaque entree a ete resolue **dans les deux sens**, peage et geometrie constants. La difference des deux est ce que le SENS apporte ; leur moyenne est ce que le bracket coute, sans aucune information directionnelle dedans.


- Bord **directionnel** median : **+0.0024 R** -- positif dans **52.0 %** des configurations, c'est-a-dire un pile ou face.
- Derive **geometrie + peage** mediane : **-0.1106 R**.
- E[R] **brut** median : **-0.0591 R** -- donc la geometrie perd deja avant le premier centime de frais.

La phase 1 avait mesure un IC **sans stop** sur ces memes cellules. Avec un stop a 1,5 x ATR14 et une barriere de temps, **il n'en reste rien en moyenne**. C'est la mesure d'exp-017 reproduite sur une famille entierement differente : le stop obligatoire ne reduit pas le bord, il l'annule.


## L'effet de selection du seuil, nomme

Le seuil **q = 0.90 etait le seul PRE-ENREGISTRE** ; (0.8, 0.95) sont des controles de robustesse. Le maximum global vient du seuil le plus serre -- donc du plus permissif en degres de liberte.


| seuil q | pre-enregistre | configs | E[R] max | E[R] median | % positives |
|--:|---|--:|--:|--:|--:|
| 0.80 | non | 519 | **+0.1081** | -0.1205 | 12.5 % |
| 0.90 | **oui** | 519 | **+0.1211** | -0.1031 | 13.5 % |
| 0.95 | non | 519 | **+0.1780** | -0.0914 | 17.7 % |

**Au seuil pre-enregistre le meilleur E[R] vaut 0.1211 R**, soit 67 % de la porte. Le 0.1780 R du classement general n'est atteint qu'en s'autorisant un seuil qui n'avait pas ete annonce.


### Ce qui monte quand meme avec la selectivite

Les meilleures cellules ordonnent leur E[R] **de facon monotone** avec le seuil d'entree, sur un axe qui n'a servi a rien d'autre. Du bruit ne s'ordonne pas ainsi : c'est le seul indice positif de la phase.


| cellule (sortie temps) | q=0,80 | q=0,90 pre-enr. | q=0,95 | moitie 1 | moitie 2 | N |
|---|--:|--:|--:|--:|--:|--:|
| orb_break US100 H1 k=12 | +0.056 | +0.118 | +0.157 | +0.188 | +0.126 | 519 |
| fix_window US500 M15 k=24 | +0.031 | +0.065 | +0.138 | +0.181 | +0.095 | 782 |
| vwap_z GER40 H1 k=24 | +0.080 | +0.117 | +0.109 | +0.086 | +0.133 | 674 |
| fix_window US100 M15 k=24 | +0.034 | +0.070 | +0.112 | +0.143 | +0.081 | 1094 |

## Les 25 meilleures par esperance nette

| # | signal | actif | UT | k | sortie | q | E[R] net | E[R] brut | N | gain % | PF | maxDD R | moitie 1 | moitie 2 | sens inverse | temoin |
|--:|---|---|---|--:|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | fix_window | US500 | M15 | 24 | tp3 | 0.95 | **+0.178** | +0.240 | 836 | 38.4 | 1.28 | -18.2 | +0.194 | +0.162 | -0.277 | -0.091 |
| 2 | orb_break | US100 | H1 | 12 | tp2 | 0.95 | **+0.169** | +0.198 | 553 | 47.2 | 1.35 | -16.8 | +0.209 | +0.128 | -0.223 | -0.036 |
| 3 | orb_break | US100 | H1 | 12 | tp3 | 0.95 | **+0.168** | +0.198 | 525 | 45.1 | 1.34 | -16.6 | +0.175 | +0.161 | -0.235 | -0.036 |
| 4 | fix_window | US500 | M15 | 24 | tp2 | 0.95 | **+0.164** | +0.226 | 897 | 43.6 | 1.28 | -22.6 | +0.215 | +0.113 | -0.256 | -0.087 |
| 5 | resid_rev | XAUUSD | H1 | 24 | tp3 | 0.95 | **+0.162** | +0.182 | 1170 | 36.3 | 1.26 | -25.1 | +0.102 | +0.221 | -0.217 | +0.007 |
| 6 | orb_break | US100 | H1 | 12 | time | 0.95 | **+0.157** | +0.187 | 519 | 44.5 | 1.31 | -16.6 | +0.188 | +0.126 | -0.207 | -0.019 |
| 7 | skew | BTCUSD | H4 | 24 | tp3 | 0.95 | **+0.145** | +0.193 | 277 | 36.8 | 1.22 | -20.7 | +0.137 | +0.153 | -0.354 | +0.004 |
| 8 | fix_window | US500 | M15 | 24 | time | 0.95 | **+0.138** | +0.201 | 782 | 35.9 | 1.21 | -17.2 | +0.181 | +0.095 | -0.234 | -0.041 |
| 9 | fix_window | US500 | M15 | 12 | tp2 | 0.95 | **+0.135** | +0.197 | 897 | 45.6 | 1.25 | -24.8 | +0.154 | +0.116 | -0.268 | -0.083 |
| 10 | resid_rev | XAUUSD | H1 | 24 | tp2 | 0.95 | **+0.134** | +0.154 | 1403 | 41.1 | 1.23 | -29.1 | +0.067 | +0.201 | -0.190 | -0.015 |
| 11 | resid_rev | XAUUSD | H4 | 5 | tp2 | 0.95 | **+0.133** | +0.144 | 717 | 50.6 | 1.39 | -12.1 | +0.144 | +0.122 | -0.176 | -0.012 |
| 12 | fix_window | US100 | M15 | 24 | tp3 | 0.95 | **+0.133** | +0.168 | 1175 | 36.0 | 1.21 | -26.4 | +0.155 | +0.111 | -0.179 | -0.039 |
| 13 | fix_window | US500 | M15 | 12 | tp3 | 0.95 | **+0.125** | +0.187 | 836 | 42.9 | 1.22 | -24.9 | +0.124 | +0.125 | -0.272 | -0.076 |
| 14 | resid_rev | XAUUSD | H1 | 24 | tp3 | 0.95 | **+0.125** | +0.145 | 1157 | 35.4 | 1.20 | -27.6 | +0.078 | +0.171 | -0.214 | +0.001 |
| 15 | orb_break | US100 | H1 | 12 | tp2 | 0.90 | **+0.121** | +0.151 | 1034 | 45.7 | 1.24 | -22.3 | +0.156 | +0.086 | -0.213 | -0.035 |
| 16 | vwap_z | US100 | M15 | 12 | tp2 | 0.95 | **+0.121** | +0.154 | 1937 | 46.6 | 1.26 | -21.2 | +0.140 | +0.101 | -0.220 | -0.048 |
| 17 | vwap_z | GER40 | H1 | 24 | tp3 | 0.90 | **+0.119** | +0.135 | 1157 | 37.6 | 1.19 | -34.1 | +0.115 | +0.122 | -0.127 | +0.017 |
| 18 | orb_break | US100 | H1 | 12 | tp3 | 0.90 | **+0.119** | +0.149 | 973 | 43.7 | 1.23 | -21.9 | +0.130 | +0.108 | -0.210 | -0.035 |
| 19 | vwap_z | GER40 | H1 | 24 | tp2 | 0.90 | **+0.118** | +0.135 | 1225 | 40.9 | 1.20 | -29.5 | +0.084 | +0.153 | -0.129 | +0.002 |
| 20 | orb_break | US100 | H1 | 12 | time | 0.90 | **+0.118** | +0.148 | 953 | 43.1 | 1.22 | -23.1 | +0.164 | +0.071 | -0.176 | -0.013 |
| 21 | vwap_z | GER40 | H1 | 24 | time | 0.90 | **+0.117** | +0.134 | 1102 | 36.6 | 1.18 | -38.1 | +0.118 | +0.117 | -0.161 | +0.023 |
| 22 | skew | US30 | H4 | 12 | tp2 | 0.95 | **+0.117** | +0.133 | 361 | 42.9 | 1.22 | -14.0 | +0.204 | +0.030 | -0.300 | -0.016 |
| 23 | fix_window | US100 | M15 | 24 | time | 0.95 | **+0.112** | +0.148 | 1094 | 34.1 | 1.17 | -34.0 | +0.143 | +0.081 | -0.149 | -0.015 |
| 24 | resid_rev | XAUUSD | H1 | 24 | tp2 | 0.95 | **+0.112** | +0.132 | 1391 | 40.3 | 1.19 | -25.2 | +0.059 | +0.165 | -0.188 | -0.017 |
| 25 | vwap_z | US100 | M15 | 12 | tp2 | 0.90 | **+0.111** | +0.145 | 3461 | 46.0 | 1.23 | -21.8 | +0.134 | +0.088 | -0.213 | -0.048 |

## Temoins

**Temoin de sens** : les memes entrees resolues dans l'autre sens, peage et geometrie constants. Si les deux sens gagnent, l'apport n'est pas directionnel -- c'est de la derive ou la geometrie du bracket.


- Configurations ou les deux sens gagnent : **0 / 1557** (0.0 %).
- Parmi celles qui passent la porte : **0 / 0**.

**Temoin d'entree aleatoire** : meme effectif, meme geometrie, entrees tirees au hasard, sens tire a pile ou face.


- E[R] median du temoin : **-0.0556 R** (reel : -0.1042 R).
- Configurations battues par plus de 10 % de leurs temoins : **1301 / 1557**.
