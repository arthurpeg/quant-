---
type: experiment
id: exp-012
updated: 2026-08-13
status: done
verdict: partial
horizon: intraday strict M15/H1 (aucune position ne survit à la séance)
universe: NAS100, US500, US30, GER40, XAUUSD, EURUSD, GBPUSD, USDJPY, GBPAUD, AUDJPY
code: [gridlab/families3.py, gridlab/ml_tbm.py, gridlab/run_phase3.py, gridlab/validate3.py, gridlab/control3.py, gridlab/pooled_daily3.py, gridlab/tbm_gross.py, gridlab/test_phase3.py, live_execution_phase3.py]
---

# exp-012 — Phase 3 : liquidity sweeps, triple barrière ML, breakout conditionné par la nuit

**Hypothèse.** Les Phases 1 ([[exp-010-intraday-grid-search-3-families]]) et 2
([[exp-011-phase2-vol-pair-squeeze]]) ont échoué parce qu'elles testaient des signaux
**inconditionnels**. Un bord intraday existe peut-être, mais seulement **sous
condition** — un balayage de liquidité identifié, un état de marché reconnu par un
modèle, ou un régime nocturne particulier. On abandonne M1/M5 (le péage y domine) pour
M15/H1, et on grille le **contexte** plutôt que le signal.

**Setup.** Socle des phases précédentes : M1 Pepperstone (53,5 M de barres, 10 actifs),
M15/H1 rééchantillonnées, contrainte intraday **structurelle** par horizon
([`gridlab/engine.py`](../../gridlab/engine.py)), coût = spread de la barre + 0,5 pip
de slippage par côté, IS 70 % / OOS 30 % chronologique, gel puis Benjamini-Hochberg
q ≤ 0,10. **552 000 combinaisons, 539 jeux d'entrées, 960 modèles entraînés.**
Rapport complet : [`rapport_quant_phase3_pepperstone.md`](../../rapport_quant_phase3_pepperstone.md).

Deux nouveautés de protocole par rapport à la Phase 2, toutes deux décisives :

* **Le test poolé est agrégé par JOUR, pas par symbole.** Un t pris à travers 4 indices
  corrélés à 0,9 donne des valeurs absurdes (mesuré : **t = 36**). Sommer le R de tous
  les actifs à l'intérieur d'une journée puis tester la série quotidienne met la
  corrélation dans la variance. Voir [`gridlab/pooled_daily3.py`](../../gridlab/pooled_daily3.py).
* **Un placebo par famille**, dans l'esprit du contrôle de la Phase 2 : mêmes journées,
  même fenêtre, même stop, même cible, **entrée à une minute tirée au hasard**.

**Résultat.**

* **Zéro survivant FDR**, comme en Phases 1 et 2 — mais **q minimum 0,196** contre 0,287
  (P1) et 0,46 (P2). p brute minimale 3,5e-4 contre un seuil BH de 9,7e-5 : il manque
  un facteur **3,6**. Le test poolé ne survit pas non plus (q min 0,76).
* ⭐ **LE FILTRE DE NUIT DU MANDAT FONCTIONNE, ET C'EST VISIBLE IN-SAMPLE.** Cassure de
  l'ouverture de Londres (10:00 serveur = 08:00 Londres toute l'année), H1, SL =
  0,5 × ATR(D1), sur les 4 indices : **sans filtre E[R] IS = +0,004 R** (rien), **avec
  « nuit asiatique ≤ 25e centile » E[R] IS = +0,105 R**, OOS +0,129. L'échelle est
  monotone (p100 → p60 → p40 → p25). C'est le premier edge **conditionnel** mesuré du
  projet : la condition porte l'information, pas le signal.
* ⭐ **ET CE N'EST PAS LA FENÊTRE : LE CANDIDAT BAT SON PLACEBO DANS LES DEUX MOITIÉS**,
  de **+0,102 R (IS)** et **+0,105 R (OOS)** par trade. Sans le filtre de nuit, la
  cassure ne vaut plus que +0,02 à +0,03 R au-dessus du hasard, soit moins que le
  péage. **C'est la conjonction qui produit les 0,14 R**, pas l'un des deux ingrédients.
* ⭐ **AUC 0,63 HORS ÉCHANTILLON SUR LA TRIPLE BARRIÈRE — ET PAS UN R.** 100 % des 120
  AUC OOS dépassent 0,52 (moyenne 0,630), très loin des ~0,52 de la direction. La
  décomposition par quintile du score explique tout : du Q1 au Q5, le taux de **TP
  long ×5** *et* le taux de **TP short ×3,5** montent ensemble, la probabilité qu'une
  barrière quelconque soit touchée passe de **0,30 à 0,96**, et l'espérance nette ne
  bouge pas. **Le modèle prédit la VOLATILITÉ, pas la direction** — il sait qu'une
  barrière sera touchée, pas laquelle. Confirme et précise [[exp-002-v3-mt5-four-angles]].
* **Le modèle classe quand même un peu, et huit fois trop peu.** À coût nul,
  l'espérance brute monte monotonement du top 30 % (+0,009 R) au top 5 % (+0,021 R) du
  score. L'information vaut +0,012 R contre 0,10 R de péage.
* **Les seuils absolus du mandat sont inatteignables par construction.** Avec TP à
  1,5 R et SL à 1 R le taux de base est ~0,30 : **P > 0,65 ne se déclenche jamais** et
  P > 0,60 ne produit que **90 cellules sur 45 015**. D'où l'échelle de quantiles
  (coupure lue sur l'IS seul).
* ❌ **Les liquidity sweeps sont négatifs AVANT tout frais** : 41,6 % de cellules
  positives à coût nul, sur les 3 sources de niveau × 5 profondeurs × 4 seuils de
  volume. **Le high/low de la veille — le niveau exact du mandat — est le pire des
  trois** (−0,037 R brut contre −0,012 pour la matinée de Londres).
* ⭐ **LE STOP EST UN LEVIER DE COÛT PLUS PUISSANT QUE LE SIGNAL.** Sur ABRK, le stop
  « à l'opposé du range d'ouverture » (celui du mandat) coûte **0,129 R** et perd dans
  les deux moitiés ; le stop 0,5 × ATR(D1) coûte **0,021 R** et gagne dans les deux.
  Même bord brut, six fois moins de péage. Applicable aux briques du [[system]].
* **Le classement IS → OOS porte enfin beaucoup d'information** : Spearman **+0,60**
  toutes familles (ABRK +0,67, SWEEP +0,56, TBM +0,55), contre +0,30 en P2 et −0,06
  en P1. Attention : non résidualisé, donc une part mesure le péage (cf. P2).

**Verdict.** **Rien de déployable, un candidat de forward-test.** La configuration
figée — `ABRK · H1 · 10:00 serveur · range 1 bougie · SL 0,5×ATR(D1) · TP 2R · nuit
≤ p25 · aligné H1 · 4 indices` — donne en OOS +35,4 R sur 251 trades (+12,8 R/an),
E[R] +0,141 R, maxDD 9,0 R, WR 54,2 %, **t quotidien 1,98 (p 0,025)**, 4/4 années
positives, et 4 actifs sur 4 positifs. Mais : **q 0,196 au FDR**, **l'or est négatif**
(−0,037 R, PF 0,90), **l'univers complet du mandat rend exactement zéro** (+0,0003 R,
t 0,01), et l'OOS des indices ne fait que 2-3 ans. Quatre indices corrélés à 0,9 sont
**une** idée, pas quatre.

**Test au niveau du book (question utilisateur, même jour).** Le candidat a été mesuré
en sleeve du [[system|book AGRESSIF]] à 0,5R, chacun contre **son propre placebo** —
scripts [`_p3_brick_test.py`](../../scratchpad/_p3_brick_test.py),
[`_p3_brick_oos.py`](../../scratchpad/_p3_brick_oos.py),
[`_p3_brick_usdjpy.py`](../../scratchpad/_p3_brick_usdjpy.py).

* Sur la **fenêtre complète** il est excellent : book 90,7 → **92,3 %** de P(valider),
  maxDD 18,1 → 16,5 R, RoMaD 3,01 → 3,73, médiane 2,60 → 2,33 mois, corrélation max
  aux 6 sleeves **0,047** (KAER avait été refusée à 0,370), et **il améliore le
  drawdown de l'année qui porte le maxDD du book** (2025 : 18,09 → 16,54). Ses
  placebos font 86,4 à 90,3 %, dont 3 sur 4 **sous** le book nu.
* ⭐ **Mais sur la fenêtre honnête il rentre dans la dispersion de son placebo.**
  2021 et 2022 (in-sample) portent l'essentiel des +14,6 R/an autonomes ; en OOS la
  sleeve ne fait plus que **+4,8 R/an**. Sleeve active uniquement en OOS : candidat
  **91,2 %** contre placebos 90,1 / 90,5 / 90,7 / **91,4 %**. Restreint à la fenêtre
  OOS commune aux 4 indices : candidat **89,1 %** contre placebos 84,6 / 86,7 / 86,8
  / **89,0 %**. **L'écart par trade (+0,105 R) est réel ; il vaut +2,4 R/an sur un
  book qui en fait 54, soit moins que l'écart entre deux tirages de placebo.**
* **Les deux plus fortes cellules de la validation sont USDJPY long et le placebo les
  tue** : `ABRK USDJPY p100` (t 3,41) donne 91,7 % quand **ses quatre placebos font
  92,0 à 92,3 %** — du bêta de dépréciation du yen ; `TBM USDJPY top-5 %` donne
  91,9 % contre 91,2-91,6 % — dans le bruit.
* Le filtre de nuit se voit **aussi au niveau du book** : sans lui (p100) la sleeve
  tombe à +3,9 R/an, maxDD 57,6 R, et empire le drawdown de 4 années sur 9.

**Aucune brique, aucune sleeve à câbler.** Un seul fil en forward-test papier.

**Pourquoi ça compte / suite.** C'est la première fois qu'un mécanisme est
*mesuré* plutôt qu'espéré : le filtre de nuit change l'espérance d'un facteur 25,
la monotonie est visible in-sample, et le placebo est battu dans les deux moitiés.
Ce qui manque n'est pas une meilleure grille, c'est du **temps hors échantillon** —
raffiner ici serait du data mining sur du data mining. Suite proposée : forward-test
papier 3-6 mois de la configuration figée, **avec le placebo tournant en parallèle**
comme benchmark. `live_execution_phase3.py` est livré prêt, `enabled=False` partout.

**Livrables.** [`rapport_quant_phase3_pepperstone.md`](../../rapport_quant_phase3_pepperstone.md)
(3 930 lignes, code intégral inclus), [`gridlab/families3.py`](../../gridlab/families3.py),
[`gridlab/ml_tbm.py`](../../gridlab/ml_tbm.py), [`gridlab/run_phase3.py`](../../gridlab/run_phase3.py),
[`gridlab/validate3.py`](../../gridlab/validate3.py), [`gridlab/control3.py`](../../gridlab/control3.py),
[`gridlab/pooled_daily3.py`](../../gridlab/pooled_daily3.py), [`gridlab/tbm_gross.py`](../../gridlab/tbm_gross.py),
[`gridlab/test_phase3.py`](../../gridlab/test_phase3.py), [`gridlab/export_model3.py`](../../gridlab/export_model3.py),
[`live_execution_phase3.py`](../../live_execution_phase3.py),
[`check_live_parity_phase3.py`](../../check_live_parity_phase3.py). **Aucun code live touché.**

**Links.** [[exp-010-intraday-grid-search-3-families]], [[exp-011-phase2-vol-pair-squeeze]],
[[exp-002-v3-mt5-four-angles]], [[triple-barrier]], [[walk-forward-embargo]],
[[leakage]], [[prop-firm-universe]], [[ledger]], [[system]].
