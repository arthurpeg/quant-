---
type: experiment
id: exp-022
updated: 2026-08-18
status: done
verdict: partial
horizon: M5 / M15 / H1 / H4, sortie a k barres (k = 5 a 24)
universe: 13 actifs portant les 173 cellules de la porte IC
code: [research/scripts/06_stop_geometry.py]
---

# exp-022 — La géométrie de sortie balayée : le stop tronquait bien un bord

**Hypothesis.** [[exp-021-backtest-r-multiples]] laissait une question ouverte
que son chiffre ne tranchait pas : avec un stop a 1,5 x ATR14 le bord
directionnel valait +0,0024 R (52 % de configurations positives) — **le stop
TRONQUAIT-il un bord reel, ou n'y avait-il rien a tronquer ?** Mandat
utilisateur : rejouer les 173 cellules en ne changeant QUE la sortie — stop dur
a 2 / 3 / 4 x ATR14, et Chandelier Exit a 2 / 3 x ATR14 sur l'extreme des 5
dernieres barres.

**Setup.** [`research/scripts/06_stop_geometry.py`](../../research/scripts/06_stop_geometry.py),
**2 595 configurations** = 173 cellules x 3 seuils x (3 stops durs + 2
Chandelier). Memes signaux, memes entrees, meme peage, meme regle d'occupation,
memes temoins qu'en phase 2. Rapport :
[`rapport_geometrie_sortie.md`](../../research/rapport_geometrie_sortie.md).

**Result.**

⭐⭐⭐ **LE STOP TRONQUAIT BIEN UN BORD, ET LA REPONSE EXIGEAIT DE CHANGER
D'UNITE POUR ETRE LUE.** `1R = m x ATR14` : elargir le stop **agrandit l'unite
de compte**, donc tout ce qui est libelle en R retrecit mecaniquement. L'E[R]
median qui remonte de −0,113 (1,5x) a −0,013 (4,0x) ne prouve donc rien — c'est
un changement d'unite, exactement le piege d'[[exp-016-phase5-crypto-crosses]]
(« la barriere verticale n'est PAS un levier de cout »). Relu en **bps de
prix**, ou l'unite est fixe :

| geometrie | 1R (bps) | bord directionnel (bps) | % configs > 0 | bord/peage |
|---|--:|--:|--:|--:|
| dur 1,5x (phase 2) | 36,5 | +0,629 | 62 % | 0,379 |
| dur 2,0x | 48,8 | +0,611 | 58 % | 0,354 |
| dur 3,0x | 73,1 | +0,887 | 65 % | 0,545 |
| dur 4,0x | 97,4 | **+1,279** | **73 %** | 0,704 |
| **Chandelier 2,0x** | 48,8 | **+1,860** | **90 %** | **1,029** |
| Chandelier 3,0x | 73,7 | +1,074 | 83 % | 0,599 |

Le bord directionnel **double** entre 1,5x et 4,0x et la part de configurations
a bord positif monte de 62 % a 73 %. Il y avait donc quelque chose a tronquer.

⭐⭐⭐ **LE CHANDELIER A 2 x ATR14 EST LA MEILLEURE CAPTURE DE DIRECTION DE TOUT
LE PROJET : +1,86 bps, positive dans 90 % des 519 configurations, rapport
bord/peage = 1,03.** C'est la **premiere fois que le bord directionnel EGALE le
peage** dans le travail intraday de ce depot (0,33 au mieux en
[[exp-016-phase5-crypto-crosses]], 0,38 en phase 2).

⭐⭐⭐ **ET L'ESPERANCE NETTE RESTE NEGATIVE PARTOUT : 0 survivante sur 2 595.**
Le Chandelier sort sur son trailing dans **91 %** des trades : il capture la
direction et la **rend en sorties sur bruit**. La part NON directionnelle du
bracket coute plus que ce que la direction rapporte. Le stop dur a 4,0x est la
seule geometrie dont l'E[R] **brut** median repasse positif (+0,0025 R), et son
net reste a −0,0126 R.

⭐⭐ **Le taux de declenchement du stop se comporte comme il doit** : 40 % a 2x,
22 % a 3x, 12 % a 4x pour le stop dur ; 91 % et 72 % pour le Chandelier. Le
moteur de la phase 2 n'enregistrait pas le motif de sortie — le champ manquant
a ete ajoute ici plutot que reconstitue apres coup.

⭐⭐ **Deux configurations tiennent tous les controles simultanement** — seuil
**pre-enregistre** q = 0,90, positives dans les deux moities chronologiques,
temoin de sens franchement negatif, N > 900, temoin aleatoire a ~0 :

| config | N | E[R] | PF | moities | sens inverse | taux stop |
|---|--:|--:|--:|--:|--:|--:|
| `vwap_z` GER40 H1 k=24, dur 2,0x | 1 043 | +0,128 | 1,25 | +0,138 / +0,118 | −0,173 | 47 % |
| `orb_break` US100 H1 k=12, dur 2,0x | 908 | +0,115 | 1,28 | +0,128 / +0,103 | −0,136 | 35 % |

Aucune n'atteint 0,18 R. `orb_break` US100 H1 confirme le fil deja repere en
phase 2 ; `vwap_z` GER40 H1 est neuf.

⭐ Auto-tests du moteur **7/7**, dont trois que la phase 2 n'avait pas : le
trailing ne se desserre jamais, **le niveau en vigueur pendant une barre est
calcule sur les barres precedentes** (sinon le stop serait pose avec le plus
haut de la barre qui va le toucher), et le taux de declenchement doit decroitre
avec la largeur. Un cas a d'abord ete pris pour un echec du moteur : un
trailing **traverse par un gap** rend −1,82 R la ou la sortie au niveau du stop
aurait rendu +7,28 R. C'est le comportement correct, et c'est ce qu'un backtest
qui suppose une sortie AU niveau du stop se cache a lui-meme.

**Verdict.** ⚠️ **partial.** Aucune strategie validee, donc rien a deployer —
mais la question d'exp-021 est tranchee et la reponse est **positive** : le bord
directionnel existe, il etait tronque, et il est desormais mesure a **1,03 fois
le peage** dans sa meilleure geometrie. Il manque un facteur ~1,0 la ou les six
phases precedentes en demandaient 3 a 15.

**Why it matters / next.** Le levier restant n'est plus le signal ni la largeur
du stop mais **la regle de sortie elle-meme** : le Chandelier trouve la
direction (90 % des configurations) et la rend en whipsaw (91 % de sorties sur
trailing). La suite utile est un trailing **moins reactif** — extreme sur 10-20
barres au lieu de 5, ou activation seulement apres +1R — teste sur les deux
configurations ci-dessus, qui sont les seules a tenir tous les controles au
seuil pre-enregistre.

**Links.** [[exp-021-backtest-r-multiples]], [[exp-020-porte-ic-moisson-automatisee]],
[[exp-016-phase5-crypto-crosses]], [[exp-017-xsection-fx-intraday]],
[[triple-barrier]], [[ledger]].
