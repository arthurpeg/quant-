# Etape 6 -- la geometrie de sortie, balayee

_Genere le 2026-08-18 01:29 -- memes 173 cellules, memes entrees, memes seuils, meme peage. **Seule la sortie change.**_


## Le tableau demande

`1R = m x ATR14`, donc **elargir le stop agrandit l'unite de compte** : le peage en R et le gain brut en R diminuent TOUS DEUX mecaniquement. C'est pourquoi le tableau porte aussi le **taux de declenchement du stop** et le **bord directionnel**, que la largeur ne renormalise pas.


| mecanique | m (x ATR14) | configs | taux de stop | E[R] net median | E[R] net max | % positives | E[R] brut median | peage median (R) | bord directionnel median |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| phase 2 : dur | 1.5 | 519 | nan | **-0.1128** | +0.1570 | 10.0 % | -0.0667 | 0.0455 | +0.0151 |
| dur | 2.0 | 519 | 0.401 | **-0.0755** | +0.1394 | 15.6 % | -0.0416 | 0.0342 | +0.0107 |
| dur | 3.0 | 519 | 0.224 | **-0.0310** | +0.1468 | 23.5 % | -0.0091 | 0.0230 | +0.0105 |
| dur | 4.0 | 519 | 0.119 | **-0.0126** | +0.1280 | 31.2 % | +0.0025 | 0.0173 | +0.0111 |
| Chandelier | 2.0 | 519 | 0.910 | **-0.0614** | +0.0976 | 5.0 % | -0.0233 | 0.0336 | +0.0307 |
| Chandelier | 3.0 | 519 | 0.720 | **-0.0464** | +0.0911 | 9.8 % | -0.0235 | 0.0226 | +0.0156 |

## Ce que la largeur change vraiment

Le **taux de declenchement du stop** chute comme prevu quand m augmente : **40 %** a 2x, **22 %** a 3x, **12 %** a 4x. Le moteur de la phase 2 n'enregistrait pas le motif de sortie, donc la ligne 1,5x n'a pas de taux -- c'est ce manque qui a motive le champ `stop_rate` ici, et il n'est pas comble apres coup.

Le **bord directionnel**, lui, est la grandeur qui repond a la question posee : *le stop tronquait-il un bord, ou n'y avait-il rien a tronquer ?*


| m (x ATR14) | bord directionnel median (R) | % de configs a bord > 0 |
|--:|--:|--:|
| 2.0 | +0.0107 | 58.0 % |
| 3.0 | +0.0105 | 64.9 % |
| 4.0 | +0.0111 | 72.8 % |
| _1,5 (phase 2)_ | _+0.0151_ | _62.4 %_ |

## Le meme bord, dans une unite qui ne bouge pas

Tout ce qui precede est libelle en R, et **R change de taille a chaque ligne du tableau** (`1R = m x ATR14`). Un E[R] median qui passe de -0,104 a -0,013 quand le stop s'elargit n'a donc rien prouve : il a surtout change d'unite. On relit ci-dessous les memes configurations en **bps de prix**, ou l'unite est fixe.


| geometrie | 1R (bps) | bord directionnel (bps) | % configs a bord > 0 | peage AR (bps) | **bord / peage** | facteur manquant |
|---|--:|--:|--:|--:|--:|--:|
| phase 2 : dur 1.5x | 36.5 | **+0.629** | 62 % | 1.62 | **0.379** | 2.6x |
| dur 2.0x | 48.8 | **+0.611** | 58 % | 1.62 | **0.354** | 2.8x |
| dur 3.0x | 73.1 | **+0.887** | 65 % | 1.62 | **0.545** | 1.8x |
| dur 4.0x | 97.4 | **+1.279** | 73 % | 1.62 | **0.704** | 1.4x |
| Chandelier 2.0x | 48.8 | **+1.860** | 90 % | 1.62 | **1.029** | 1.0x |
| Chandelier 3.0x | 73.7 | **+1.074** | 83 % | 1.62 | **0.599** | 1.7x |

**C'est le tableau qui repond a la question.** Le stop TRONQUAIT bien un bord : en unite fixe, le bord directionnel **double** entre 1,5x et 4,0x (0,63 -> 1,28 bps) et la part des configurations a bord positif monte de 62 % a 73 %. Il y avait donc quelque chose a tronquer, et 1,5 x ATR14 le coupait.


Et le **Chandelier a 2 x ATR14 est la meilleure capture de direction de toute l'etude** : **+1,86 bps**, positif dans **90 %** des configurations, soit un rapport bord/peage de **1,03** -- la premiere fois que le bord directionnel EGALE le peage dans le travail intraday de ce depot. Et l'esperance nette reste negative, parce que la part NON directionnelle du bracket (troncature, gaps, sorties sur bruit : le trailing sort sur 91 % des trades) coute plus que ce que la direction rapporte.


## La porte

`E[R] >= 0.18` ET `N >= 100` ET `PF >= 1.25` : **0 configurations sur 2595**.

- dont survivantes BH-FDR (q <= 0.1) : **0**
- dont les DEUX sens gagnent (a rejeter) : **0**
- dont positives dans les deux moities : **0**

Au seuil **pre-enregistre q = 0.90**, le meilleur E[R] vaut **+0.1281 R** (tous seuils confondus : +0.1468 R).


## Les 25 meilleures par esperance nette

| # | signal | actif | UT | k | mecanique | m | q | E[R] net | E[R] brut | taux stop | N | PF | maxDD R | moitie 1 | moitie 2 | sens inverse |
|--:|---|---|---|--:|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | skew | BTCUSD | H4 | 24 | hard | 3.0 | 0.95 | **+0.147** | +0.169 | 35 % | 150 | 1.35 | -7.8 | +0.176 | +0.118 | -0.335 |
| 2 | skew | BTCUSD | H4 | 24 | hard | 2.0 | 0.95 | **+0.139** | +0.173 | 57 % | 183 | 1.23 | -13.0 | +0.163 | +0.116 | -0.446 |
| 3 | vwap_z | GER40 | H1 | 24 | hard | 2.0 | 0.90 | **+0.128** | +0.140 | 47 % | 1043 | 1.25 | -23.5 | +0.138 | +0.118 | -0.173 |
| 4 | skew | BTCUSD | H4 | 24 | hard | 4.0 | 0.95 | **+0.128** | +0.145 | 21 % | 136 | 1.41 | -5.8 | +0.125 | +0.131 | -0.277 |
| 5 | orb_break | US100 | H1 | 12 | hard | 2.0 | 0.95 | **+0.124** | +0.146 | 33 % | 510 | 1.31 | -12.7 | +0.129 | +0.119 | -0.168 |
| 6 | vwap_z | GER40 | H1 | 24 | hard | 3.0 | 0.90 | **+0.121** | +0.129 | 28 % | 980 | 1.33 | -14.0 | +0.112 | +0.130 | -0.139 |
| 7 | orb_break | US100 | H1 | 12 | hard | 2.0 | 0.90 | **+0.115** | +0.138 | 35 % | 908 | 1.28 | -14.3 | +0.128 | +0.103 | -0.136 |
| 8 | fix_window | US100 | M15 | 24 | hard | 2.0 | 0.95 | **+0.110** | +0.136 | 52 % | 1048 | 1.20 | -28.8 | +0.176 | +0.044 | -0.139 |
| 9 | vwap_z | GER40 | H1 | 24 | hard | 2.0 | 0.95 | **+0.109** | +0.121 | 48 % | 651 | 1.20 | -24.5 | +0.084 | +0.133 | -0.144 |
| 10 | skew | US30 | H4 | 12 | hard | 4.0 | 0.95 | **+0.102** | +0.108 | 11 % | 208 | 1.52 | -4.1 | +0.134 | +0.070 | -0.164 |
| 11 | skew | US30 | H4 | 12 | hard | 3.0 | 0.95 | **+0.101** | +0.109 | 19 % | 221 | 1.36 | -6.0 | +0.178 | +0.026 | -0.256 |
| 12 | fix_window | US100 | M15 | 24 | hard | 3.0 | 0.95 | **+0.100** | +0.118 | 36 % | 1017 | 1.24 | -17.0 | +0.145 | +0.054 | -0.112 |
| 13 | orb_break | US100 | H1 | 12 | hard | 3.0 | 0.95 | **+0.098** | +0.113 | 17 % | 500 | 1.36 | -6.6 | +0.100 | +0.097 | -0.127 |
| 14 | orb_break | US100 | H1 | 12 | chandelier | 2.0 | 0.95 | **+0.098** | +0.120 | 68 % | 548 | 1.30 | -11.5 | +0.056 | +0.139 | -0.077 |
| 15 | fix_window | US500 | M15 | 24 | hard | 2.0 | 0.95 | **+0.097** | +0.144 | 53 % | 755 | 1.17 | -22.7 | +0.100 | +0.094 | -0.168 |
| 16 | vwap_z | GER40 | H1 | 24 | hard | 3.0 | 0.95 | **+0.096** | +0.104 | 28 % | 630 | 1.26 | -16.2 | +0.074 | +0.119 | -0.122 |
| 17 | orb_break | US100 | H1 | 12 | chandelier | 3.0 | 0.95 | **+0.091** | +0.106 | 34 % | 509 | 1.35 | -7.6 | +0.094 | +0.088 | -0.048 |
| 18 | fix_window | US500 | M15 | 12 | hard | 2.0 | 0.95 | **+0.088** | +0.135 | 41 % | 755 | 1.19 | -22.4 | +0.066 | +0.109 | -0.204 |
| 19 | skew | US30 | H4 | 12 | hard | 3.0 | 0.90 | **+0.084** | +0.092 | 20 % | 403 | 1.29 | -6.8 | +0.096 | +0.073 | -0.199 |
| 20 | session_move | US100 | M15 | 24 | hard | 3.0 | 0.80 | **+0.084** | +0.103 | 33 % | 2448 | 1.21 | -22.5 | +0.082 | +0.085 | -0.197 |
| 21 | orb_break | US100 | H1 | 12 | hard | 3.0 | 0.90 | **+0.083** | +0.098 | 19 % | 886 | 1.28 | -8.9 | +0.093 | +0.072 | -0.098 |
| 22 | skew | US30 | H4 | 12 | hard | 4.0 | 0.90 | **+0.082** | +0.088 | 11 % | 383 | 1.39 | -4.9 | +0.097 | +0.068 | -0.130 |
| 23 | fix_window | US100 | M15 | 24 | hard | 3.0 | 0.90 | **+0.081** | +0.099 | 36 % | 1714 | 1.19 | -19.2 | +0.090 | +0.073 | -0.111 |
| 24 | fix_window | US500 | M15 | 24 | hard | 3.0 | 0.95 | **+0.079** | +0.111 | 36 % | 735 | 1.18 | -17.0 | +0.086 | +0.072 | -0.112 |
| 25 | session_move | US100 | M15 | 24 | hard | 3.0 | 0.90 | **+0.079** | +0.097 | 29 % | 1374 | 1.21 | -20.7 | +0.127 | +0.031 | -0.151 |
