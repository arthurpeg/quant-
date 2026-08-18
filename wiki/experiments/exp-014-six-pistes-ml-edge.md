---
type: experiment
id: exp-014
updated: 2026-08-13
status: done
verdict: partial
horizon: multi — M15/H1/D1, et le book existant
universe: NAS100, US500, US30, GER40, XAUUSD, EURUSD, GBPUSD, USDJPY, USDCAD, BTCUSD, ETHUSD + les sleeves du book
code: [tbmlab/cost_screen.py, tbmlab/factorized.py, metalab/bricks.py, metalab/context.py, metalab/gate.py, metalab/breadth.py]
---

# exp-014 — Les six pistes « comment obtenir un vrai bord ML », toutes exécutées

**Hypothèse.** Après [[exp-013-triple-barrier-ml-dedie]], question utilisateur :
*« quelles seraient tes recommandations pour créer un ML qui a un vrai edge ? »*,
puis *« fais tout »*. Six pistes proposées, six pistes mesurées — aucune laissée à
l'état d'argument. Rapport :
[`rapport_recommandations_ml_edge.md`](../../rapport_recommandations_ml_edge.md).

**Résultat.**

* ⭐ **LE FILTRE DE COÛT RE-DÉRIVE LE BOOK, ET IL EST À UNE LIGNE.**
  `1R / coût aller-retour` ([`tbmlab/cost_screen.py`](../../tbmlab/cost_screen.py)) :
  **M15 = 15 instruments sur 15 sans espoir** (3,4-9,5), **H1 = zéro exploitable**,
  **D1 = 7 sur 15** (44-122). Les seuils lisibles dans l'historique du dépôt :
  ≥ 50 exploitable, ~10 il faut un bord que personne n'a trouvé, ≤ 6 sans espoir.
  **Test rétrospectif : b4 IBS D1 = 122, b2 turn-of-month D1 = 110, b3 crypto
  D1 = 61-67, b1 = le seul intraday et sur l'instrument le moins cher (NAS100).**
  Le filtre aurait éliminé le mandat d'exp-013 avant le premier des 3 888
  ajustements.
* ⭐ **ÉLARGIR LE STOP NE PEUT PAS RÉPARER : LE RAPPORT BORD-BRUT/PÉAGE EST UN
  INVARIANT DE L'INSTRUMENT.** Sur les 135 396 cellules d'exp-013 : 0,435 (stop
  1,0×ATR) → 0,453 (1,5×ATR) → 0,479 (0,5×ATR(D1)), pour un stop **4,7× plus
  large**. Élargir R multiplie le bord ET le péage par le même facteur. Le rapport
  varie par ACTIF (XAUUSD 0,90, GER40 0,80, NAS100 0,72 … US30 0,055) et par
  HORIZON (H1 0,51 contre M15 0,33), jamais par bracket. **Il faut franchir 1,00 ;
  personne n'y est.** ⚠️ Ceci **corrige la lecture facile** de l'acquis « le stop est
  un levier de coût » (exp-012, exp-013) : ce n'est pas « le même bord pour moins
  cher », c'est une mise à l'échelle.
* ❌ **META-LABELING SUR LES BRIQUES QUI MARCHENT : L'INFORMATION EXISTE, ELLE NE SE
  CONVERTIT PAS.** Trois sleeves (b1, KAER, b4) comme modèles primaires, le ML
  n'ayant qu'à REFUSER des trades — la prescription réelle d'AFML, jamais appliquée
  ici. **AUC 0,53-0,58** sur « ce trade était-il gagnant », dans les deux moitiés,
  sur les trois sleeves. Mais contre le seul juge admissible — **retirer le même
  NOMBRE de trades au hasard, 400 tirages** — **0/75 cellules battent leur placebo
  dans les DEUX moitiés** (0,6 attendue sous bruit ; 6 passent en IS, 7 en OOS,
  jamais les mêmes).
* ⭐ **MAIS L'ÉTIQUETTE BINAIRE OPTIMISAIT LA MAUVAISE QUANTITÉ, ET C'EST
  RÉPARABLE.** Écart au placebo moyen : lgbm binaire −0,016/−0,021, logit binaire
  −0,000/+0,000, lgbm pondéré |R| −0,015/+0,011, **logit pondéré |R| +0,009/+0,026**,
  **ridge sur R +0,012/+0,015**. **Le classement suit exactement l'information de
  MAGNITUDE dont chaque modèle dispose.** Refuser un trade à 40 % de probabilité qui
  aurait payé +2 R coûte plus que le −1 R évité. **Règle : ne jamais meta-labelliser
  sur `R > 0`.**
* ⭐ **LA LARGEUR, CHIFFRÉE : 9 ACTIFS = 2,17 PARIS.** `N_eff = k/(1+(k−1)ρ̄)` sur
  le R quotidien ([`metalab/breadth.py`](../../metalab/breadth.py)). Univers du
  mandat : |ρ| moyen 0,394 → **2,17 sur 9**. **Bloc des 4 indices : ρ 0,789 →
  1,19 — quatre indices sont UN pari.** `IR ≈ IC·√N` : le gain racine tombe de 3,0
  à 1,47, **la moitié de l'IR atteignable perdue avant le premier modèle**. Et la
  mesure confirme le soupçon du [[ledger]] : **b1 ↔ KAER corrélés à +0,371**, KAER
  est une redérivation de la brique 1 ; b4 décorrélée (−0,03) ; N_eff 2,50 sur 3.
* ⭐⭐ **FACTORISER L'ÉTIQUETTE EST LA PISTE LA PLUS FORTE DE TOUTE L'ÉTUDE.**
  `P(TP premier) = P(une barrière touchée) × P(TP | touchée)`. Le conditionnement
  est légitime **par un argument de martingale** : pour une marche sans dérive,
  `P(toucher +a avant −b) = b/(a+b)`, **indépendant de la volatilité** — ce qui
  survit au conditionnement est directionnel ou n'est rien. AUC OOS, H1, 324
  configurations : mélangée sur toutes les barres **0,663**, mélangée sur les barres
  touchées **0,554**, modèle conditionnel sur les touchées **0,548**.
  **Enseignement négatif : entraîner directement sur le problème conditionnel
  n'améliore PAS l'AUC** — le résidu directionnel vaut ~0,55 quelle que soit la
  façon de l'apprendre. **Enseignement positif, en R : le top 5 % du score
  conditionnel rend −0,017 R contre un placebo à −0,082 R, soit +0,064 R d'apport
  (contre +0,020 R pour le modèle non factorisé — un facteur 3), et 30/162
  configurations battent leur placebo DANS LES DEUX MOITIÉS = 18,5 %, contre 0,25 %
  sous bruit, soit 74× le hasard.** C'est de très loin le signal le plus net jamais
  mesuré ici. **Et ça perd quand même** : le modèle comble 78 % du trou, le dernier
  quart est du péage.

**Verdict.** ⭐ **LA CONTRAINTE « AUCUNE POSITION OVERNIGHT » EST ELLE-MÊME LE
PROBLÈME.** Les six mesures convergent : le péage vaut ~2,3× le bord brut à toutes
les échelles intraday, le seul horizon où le rapport bascule est **D1**, le modèle
factorisé comble déjà 78 % du trou, et la largeur disponible est de 2,17 paris.
Il ne manque pas un meilleur modèle — **il manque un facteur ~4 sur le péage, et ce
facteur existe à D1.** Or, mesuré : **b2, b3 et b4 tiennent overnight** (b4 IBS :
**99,0 % des trades, médiane 2 jours**), seule b1 ne le fait pas. La contrainte
n'est donc pas une règle du book, c'était une règle du mandat d'exp-013 — et c'est
elle qui a placé toute l'étude dans la zone morte du filtre de coût.

**Suite proposée, une seule expérience falsifiable.** Le modèle factorisé **à D1**,
sur les 7 instruments que le filtre déclare exploitables (NAS100, XAUUSD, US30,
GER40, ETHUSD, BTCUSD, GBPUSD) : barrières en multiples d'ATR(D1), horizon en jours,
étiquette **conditionnelle**, pondération |R|, placebo apparié dans les deux moitiés
comme unique juge. **Espérance annoncée AVANT de regarder : base ~+0,03 R au lieu de
−0,082, plus ~+0,06 R de sélection.** Si la base à D1 n'est pas positive, la thèse
tombe et il faut conclure que l'univers prop, à 2,17 paris effectifs, ne porte pas
de bord ML — ce qui serait aussi une réponse. **Note : cela demande un moteur qui
autorise le multi-jours ; `gridlab/engine.py` est intraday par construction.**

**Un défaut attrapé par un garde-fou, à garder.** `metalab/context.verify_clock`
re-dérive le prix d'entrée de chaque sleeve depuis le cache M1 à la même minute UTC
et exige l'accord (830/830 pour b1, écart 5e-08). Il a d'abord échoué à 0/830 —
non pas un décalage de fuseau mais **un bug d'unité pandas** (`datetime64[us]` traité
comme des nanosecondes). Et un second défaut, dans l'autre sens : la brique 4 plaçait
la décision **22 h trop tôt**, privant le modèle de toute la séance de décision ;
corrigé, le verdict n'a pas bougé.

**Links.** [[exp-013-triple-barrier-ml-dedie]], [[exp-012-phase3-sweep-tbm-abrk]],
[[exp-004-xsection-breadth-poc]], [[breadth]], [[information-coefficient-and-ir]],
[[triple-barrier]], [[lopez-de-prado-afml]], [[system]], [[ledger]], [[lessons]].
