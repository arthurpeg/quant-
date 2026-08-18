---
type: experiment
id: exp-011
updated: 2026-08-12
status: done
verdict: no-edge
horizon: intraday strict (aucune position ne survit à la séance)
universe: NAS100, US500, US30, GER40, FRA40, XAUUSD, EURUSD, GBPUSD, USDJPY (+ 5 paires)
code: [gridlab/families2.py, gridlab/pairs.py, gridlab/run_phase2.py, gridlab/validate2.py, gridlab/control2.py, live_execution.py]
---

# exp-011 — Phase 2 : microstructure de volume, stat-arb intraday, squeeze multi-UT

**Hypothèse.** Les trois familles d'[[exp-010-intraday-grid-search-3-families]] ont
échoué parce qu'elles sont des règles OHLCV sur horloge temporelle. En changeant de
**structure de données** (barres de volume / dollar volume), de **dimension** (spread
coïntégré à deux jambes) ou de **régime** (compression de volatilité multi-UT), une
famille contient une cellule à espérance nette positive qui survit hors échantillon.

**Setup.** Même socle qu'exp-010 — M1 Pepperstone, M5/M15/H1 rééchantillonnées,
contrainte intraday structurelle par horizon, coût = spread de la barre + 0,5 pip de
slippage par côté, IS 70 % / OOS 30 %, gel puis Benjamini-Hochberg q ≤ 0,10.
**1 293 732 combinaisons, 603 jeux d'entrées, 497 s** sur 5 processus.
Rapport : [`rapport_quant_phase2_pepperstone.md`](../../rapport_quant_phase2_pepperstone.md).

Trois familles : **VOL** (7 horloges dont 4 d'activité × spike de volume/vitesse et
déséquilibre de volume signé, suivi et contre), **PAIR** (5 paires × 3 UT × 3 fenêtres
de z, entrée en fade, stop en z, sortie au retour à la moyenne), **SQZ** (Donchian
M15/H1 filtré par ATR(M15)/ATR(H1) dans les killzones Londres et NY).

**Résultat.**

* **Zéro survivant.** 742 cellules gelées (VOL 450, SQZ 292, **PAIR 0**), 60 % positives
  en OOS, **q minimum = 0,46** (p brute min 0,0017 contre un seuil BH de 1,35e-4).
  Le test **poolé** (90 006 configurations tradées sur ≥ 6 actifs) ne survit pas non
  plus : q min 0,44.
* ⭐ **Le classement in-sample porte enfin de l'information — et elle ne vaut rien.**
  Spearman(E[R] IS, E[R] OOS) **résidualisé** (moyenne du bloc actif × horloge × stop
  retirée, car le péage corrèle les deux moitiés sans qu'aucun signal ne soit en jeu)
  = **+0,297** contre **−0,056** en Phase 1. Mais le **meilleur décile in-sample rend
  +0,0027 R par trade en OOS**. La sélection marche ; elle sélectionne zéro.
* ⭐ **Il y a un bord brut, cette fois — 10× trop petit.** À coût nul (grille entière
  relancée) : E[R] brut médian **+0,005 R** (VOL) et **+0,010 R** (SQZ), moyennes
  +0,009 / +0,020, contre un coût médian de **0,068 / 0,074 R**. C'est la différence
  avec exp-010, où le brut était négatif. Mais **56-59 % de cellules positives à coût
  nul** = à peine mieux que pile ou face : supprimer les frais ne créerait pas de
  stratégie, il rendrait le bruit symétrique.
* ⭐ **PAIR est morte par arithmétique, pas par statistique.** σ résiduel du spread
  US500/US30 en M5 ≈ 1,1 bp → R (stop à 3,5σ) ≈ 1,9 bp, contre ~11 bp d'aller-retour
  sur **deux** jambes : **le coût vaut 6 R**. Péage médian par horloge : **1,03 R en
  M5, 0,43 R en M15, 0,20 R en H1**. Réduire l'horizon réduit σ **sans** réduire le
  spread — aucune grille ne contourne ça.
* **Ce qui « marche » est du bêta.** Cellules gelées `long` : E[R] OOS moyen **+0,060 R** ;
  `short` **−0,007** ; `both` **−0,012**. 11 des 12 meilleurs candidats sont long-only.
  Contrôle dédié ([`control2.py`](../../gridlab/control2.py)) : **acheter à une minute
  au hasard** dans la même killzone rend **+0,000 à +0,014 R** en OOS (contre −0,014 à
  −0,032 en IS) — une bonne part de « l'edge » OOS long est la fenêtre elle-même.
* **Le filtre de compression du mandat ne filtre presque rien.** ATR(M15)/ATR(H1) a une
  médiane de 0,45-0,49 (moyenne 0,47-0,49) : le seuil « < 0,5 » laisse passer **54-63 %**
  des barres. Les seuils contraignants (< 0,3 : 0,4-5 % des barres) ne laissent plus
  assez de trades.

**Verdict.** ❌ **no-edge.** Changer de structure de données ne suffit pas : le
mécanisme manque, pas la représentation.

**Les deux acquis réutilisables.**

1. ⭐ **Les barres de dollar volume coûtent 25-40 % moins cher par R** que les barres de
   temps à durée cible égale (0,051 R en B60 contre 0,055 en H1 ; 0,076 en B15 contre
   0,087 en M15). Mécanisme : à volume constant la barre se ferme quand le marché est
   actif, donc l'ATR à l'entrée est plus grand relativement au spread. **Applicable aux
   briques existantes du [[system]], indépendamment de tout signal nouveau.**
2. **Le seul fil non mort :** `vimb_follow` long (déséquilibre de volume signé) en
   killzone Londres/NY sur horloge d'activité — positif OOS sur **7 actifs sur 9**,
   E[R] OOS médian +0,067 R (moyenne +0,068), t poolé 2,0, q 0,44, soit ~5× le contrôle
   « achat aléatoire ». Sous le seuil. La suite logique n'est pas de raffiner la grille
   (du data mining sur du data mining) mais un **forward-test papier** de la
   configuration poolée figée, avec le contrôle aléatoire en benchmark parallèle.

**Test de brique pour le book AGRESSIF (fait après coup, question utilisateur).** La
barre FDR répond à « est-ce une découverte » ; AGRESSIF est un problème de **barrière**
(+15 % avant −10 %), où une sleeve médiocre mais décorrélée peut être rationnelle. Les
4 meilleurs archétypes ont donc été testés en sleeve équipondérée sur les 9 actifs
contre le book en place (b1+b2+b4@1R, b3@0,5R, HMASTO@0,5R, TLF@0,5R) :

* **3 rejetés nettement** (`vimb` M5, `spike` H1, `sqz` M15) : à 0,5R ils font tous
  baisser P(valider) (90,7 % → 87,1 / 88,9 / 79,3 %).
* **1 candidat passe**, `vimb_follow` long B60/Londres à **0,5R** : R/an 54,4 → **58,8**,
  maxDD 18,1 → **15,4 R**, RoMaD 3,01 → **3,82**, Sharpe 2,05 → 2,13, délai médian du
  challenge 2,60 → **2,37 mois**, P(valider) inchangé (90,7 → 90,8 %, bruit MC).
  Autonome : +8,9 R/an, maxDD 27,6 R, **t journalier 1,45**, corr ≤ 0,06 aux 4 briques.
* ⭐ **Et il bat son propre placebo**, ce qui est le premier résultat positif de deux
  phases de grid search. Sa corrélation la plus forte est **−0,142 à TLF** (short-only),
  donc l'hypothèse nulle était « n'importe quelle sleeve longue patche TLF ». Testée :
  3 tirages de **longs aléatoires** dans la même killzone obtiennent bien la même
  corrélation (−0,14 à −0,19) mais **dégradent** le book (P(valider) 85,4-87,2 %,
  R/an 50,7-53,0, autonome **−7 R/an**). L'écart candidat/placebo ≈ **+15 R/an** est
  du signal au-dessus du bêta, mesuré au niveau du book.
* ⚠️ **Ce qui l'empêche d'être une brique : l'amélioration du maxDD tient à UNE année.**
  Par année, le drawdown intra-annuel du book s'améliore de −6,3 R en 2025 et
  **empire** en 2018 (+3,9), 2022 (+3,4) et 2019 (+1,7). Le nouveau maxDD (15,4 R)
  est l'épisode de 2019, que le candidat a aggravé. Plus : 6/9 années positives,
  6/9 actifs positifs (USDJPY +41 R contre EURUSD −27 R), t 1,45.
  **Verdict : candidat de forward-test, pas une 5e brique.** Code :
  `scratchpad/_p2_brick_test.py`, `_p2_brick_control.py`, `_p2_brick_years.py`.

* ⭐ **« Et si on ne garde que les meilleurs actifs ? » — NON, ça l'empire, et le
  placebo dit pourquoi.** Trois règles de sélection testées sur le candidat ET sur le
  placebo. (i) **Naïve** (classement sur tout l'historique) : superbe — t 1,45 → **2,90**
  au top-5 — mais le placebo passe de −6,9 à **+3,9 R/an** sous le même traitement.
  L'écart candidat−placebo **rétrécit** monotonement quand on concentre :
  **+15,8 R/an (9 actifs) → +9,0 (top 5) → +4,8 (top 4) → +2,6 (top 3)**. Le
  cherry-picking mange exactement ce qui rendait le candidat intéressant. (ii) **Honnête**
  (choix sur l'IS, mesure sur l'OOS) : t monte à 2,48 au top-4 mais le R/an **baisse**
  (5,3 contre 6,0 à 9 actifs). (iii) **Walk-forward** (reclassement chaque 1er janvier,
  la seule version implémentable) : **8,9 R/an à 9 actifs contre 3,5 / 0,7 / 3,7 au
  top-3/4/5**, et P(valider) 90,8 % contre 90,6 / 89,6 / 90,1 % — sous le book nu.
  Mécanisme : le classement par actif **ne persiste pas**, donc on perd √breadth sans
  gagner d'IC — [[breadth]] et [[exp-004-xsection-breadth-poc]] à nouveau.
  **L'équipondération sur les 9 actifs EST la sleeve ; il n'y a rien à concentrer.**
* **Idem côté PAIR** : restreindre aux paires les moins chères ne sauve rien. NAS100/US30
  seule (péage 0,099 R en H1, le plus faible de l'étude) a une espérance IS **médiane
  −0,224 R** et **4 cellules sur 1 923** à espérance positive, aucune gelable (la
  meilleure a 57 trades IS).

**Limites.** (i) Les masques stricts héritent de l'amincissement du signal lâche (un
seuil 3,0× ne voit pas toujours l'entrée qu'il aurait prise seul — biais vers **moins**
de trades, jamais vers de meilleurs). (ii) Les meilleures cellules ont 42 à 199 trades
OOS : les espérances à +0,2/+0,4 R sont des intervalles de confiance, pas des
prévisions. (iii) US500 et GER40 n'ont qu'~18 mois de hors-échantillon (limite de flux
M1 Pepperstone déjà notée en exp-010).

**Liens.** [[exp-010-intraday-grid-search-3-families]] (Phase 1, mêmes protocole et
socle) · [[lessons]] · [[Failed Ideas/ledger]]
