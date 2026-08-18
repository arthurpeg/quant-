---
type: experiment
id: exp-017
updated: 2026-08-16
status: done
verdict: no-edge
horizon: intraday (30 min d'évaluation, détention 2-8 h, aplat avant rollover)
universe: les 28 paires forex G8 sur Pepperstone, 2016-01 → 2026-07
code: [crosslab/, live_cross_execution.py, check_live_parity_cross.py]
---

# exp-017 — Momentum cross-sectionnel intraday (Currency Strength Matrix G8)

**Hypothèse.** La direction d'une paire isolée n'est pas prédictible ici
([[exp-001-v1-single-tf-direction]], [[exp-002-v3-mt5-four-angles]]), mais le
**classement relatif** des huit devises majeures pourrait l'être : acheter la
devise la plus forte de la séance contre la plus faible annule le bêta de marché
entre les deux jambes et ne laisse que la dispersion relative. Version intraday et
« currency strength » de [[exp-003-xsection-fx]] (5 jours, ~11 noms) et de
[[exp-006-xsection-index-momentum]] (indices).

**Setup.** `crosslab/`, 120,3 M barres M1 des 28 paires tirées du terminal
Pepperstone. Panel synchronisé par **intersection** des seaux (jamais l'union —
c'est le bug d'alignement qui avait donné un faux Sharpe 0,70 à exp-006). Forces
`S = W' x / 7` sur l'incidence signée, 4 modes de score × 16 lookbacks/ancres ×
2 sens × 2 profondeurs × 2 ATR × 3 stops × 4 sorties × 3 durées × 2 règles de
sortie × 4 seuils de dispersion × 3 fenêtres = **331 776 cellules**, M5/M15/H1.
Coût **additif** et plus sévère que les phases 1-5 (la commission Razor sort du
`max()`), mesuré sur le flux : **2,32 bp aller-retour en médiane**. IS 70 % /
OOS 30 % par le temps (1 961 / 841 jours). Ne pas restituer les paramètres ici —
voir `crosslab/config.py`.

**Résultat — et le principal n'est pas statistique.**

⭐⭐⭐ **La matrice des forces ne prédit rien : elle sélectionne. C'est une identité
algébrique.** Les log-rendements étant additifs le long d'un triangle de devises,
`r(i/k) − r(j/k) = r(i/j)` pour tout `k`, donc en sommant sur les huit devises

```
S_i − S_j = (8/7) × r(i/j)        exactement
```

Pour l'architecture demandée — acheter la croisée **directe** de la plus forte
contre la plus faible — il s'ensuit que le sens désigné **est** le signe du
rendement propre de cette croisée (mesuré : **100,00 %** des 59 707 ordres, à tous
les lookbacks), que le « spread de dispersion » **est** ce rendement (à 8/7 près),
et donc que le filtre `ΔS > 1,5σ` signifie mot pour mot « cette croisée a beaucoup
bougé ». Ce que la décomposition apporte réellement est une **sélection** : elle
désigne la plus mobile des 28 paires dans **95,3 à 98,8 %** des cas. Écart résiduel
à l'identité = l'incohérence triangulaire du flux, 0,3-1,2 % du mouvement typique,
et il ne change jamais le signe. `python -m crosslab.identity`.
**Le mandat décrit donc une réversion mono-actif sur la paire la plus mobile du
moment, habillée en cross-sectionnel.**

⭐⭐ **La variante « panier neutre au marché » y échappe — et meurt d'arithmétique.**
14 jambes = **35,7 bp** de péage aller-retour contre 2,32 bp pour la croisée
directe, pour capter le même écart de force. Même mécanisme qu'[[exp-011-phase2-vol-pair-squeeze]]
(paires intraday mortes par arithmétique) et [[exp-015-phase4-killzones-statarb]].

⭐⭐ **Le bord brut existe, il est reproductible, et son signe est l'inverse du
mandat.** Le rendement signé de la croisée désignée est **négatif** (= réversion)
dans 85,5 % des mesures IS et 70,1 % des mesures OOS, et le **signe tient d'une
moitié à l'autre dans 60,3 %** des 768 mesures appariées (pile ou face = 50 %). Il
survit à un saut d'un seau, donc ce n'est pas du rebond bid-ask.

⭐⭐ **Il est 21× trop petit.** Rapport |bord brut| / péage = **0,048** en médiane,
**0,164** en haute dispersion, maximum OOS avec saut **1,045** (t = −1,74, non
significatif). Seules 3,3 % des 1 536 mesures atteignent 1.

⭐ **Le filtre de dispersion du mandat fonctionne vraiment, d'un facteur 3,4** —
sur les trois unités de temps ET dans les deux moitiés. C'est le résultat positif
de la phase. Il en faudrait 6 fois plus.

⭐⭐ **Le SL obligatoire retourne le signe du bord, et c'est mécanique.** Le
rendement brut dit réversion ; le R brut de la grille, à stop dur, dit momentum.
Sous stop dur une stratégie de retour à la moyenne est tronquée exactement du
mauvais côté : elle a raison en moyenne mais paie l'excursion qui précède le
retour. **Le stop du contrat prop n'est pas neutre vis-à-vis du signal : il exclut
précisément la famille que ce mandat vient de trouver.** Miroir d'exp-006
(« momentum + stops = whipsaw »), pris par l'autre bout.

**FDR : 0 survivant, q_min 0,908.** Seules **0,02 %** des 331 776 cellules sont
nettes-positives en IS (cohorte gelée de 21) ; à **coût nul**, 46,9 % le sont —
pile ou face. Test poolé 0/5. Spearman IS→OOS **+0,902** sur le net contre
**+0,045** sur le brut : 4ᵉ confirmation que le classement de grille classe le
péage et non le bord.

⭐⭐⭐ **MAIS une 2ᵉ cohorte gelée sur le BRUT in-sample donne 8 survivants FDR sur
le brut OOS** (q_min 0,0007, t journalier jusqu'à **4,07** sur 15 261 trades OOS).
C'est une première dans ce dépôt : le numérateur n'est plus seulement « présent »
(exp-016 : 78,7 % de cellules positives, aucune significative), il est
**statistiquement établi**. Toutes en réversion, M5, lookback court, stop serré,
**sans** filtre de dispersion — le filtre améliore le rapport bord/péage mais coupe
le nombre de trades, et c'est le nombre qui fait la significativité. **Facteur
manquant : 11,2× au mieux, 15,9× en médiane** (0,038 R de bord contre 0,66 R de
péage). Complémentaire d'exp-016, qui manquait 4,2× sans jamais établir le bord.

⭐⭐ **Le témoin de direction apparié chiffre exactement ce que vaut le classement.**
En OOS sur la cohorte gelée : stratégie −0,045 R, témoin sans direction −0,079 R,
donc **bord directionnel pur +0,058 R** (positif dans 81 % des cellules) contre
0,101 R de péage. **Le classement ne récupère que 58 % du péage qu'il doit payer
pour l'exploiter.** Coût et géométrie du bracket sont tenus rigoureusement
constants entre la stratégie et son témoin : l'écart ne peut venir que de
l'information de sens.

**Outillage acquis, réutilisable.**
- ⭐ **Témoin de direction apparié** : résoudre chaque entrée dans les DEUX sens sur
  les mêmes barres, même stop, même péage. La moyenne est ce que rend la géométrie
  du bracket **sans aucune information directionnelle**. Contrôle exact et gratuit ;
  remplace avantageusement les tirages de placebo des phases précédentes.
- ⭐ **Deux défauts de parité live trouvés par un test, pas par un incident** :
  (a) grille d'évaluation ancrée sur l'index du panel → la *phase* des instants
  dépendait de la date de début ; (b) vol et z de dispersion en EWMA → état non
  reproductible depuis une fenêtre live bornée (6 % d'écart résiduel après 2 000
  barres). Corrigés par `utc_tod % 30` et des fenêtres finies de 1 000 barres.
  Parité ensuite **exacte** : 3 902 instants communs, 100,000 % de paires et de sens
  identiques, écart max sur les forces 4,4e-14, sur le z **0,0**.
- Moteur vérifié contre une boucle naïve : 43 200 valeurs de R, écart max 3,8e-07.

**Verdict.** ❌ **No edge — et pour une raison de structure, pas de mesure.** Dans
l'architecture « croisée directe », il n'existe pas de famille cross-sectionnelle
distincte du mono-actif : c'est de l'algèbre, pas un résultat d'échantillon. La
réversion qu'on y trouve est réelle, reproductible, 21× trop petite, et le SL
obligatoire l'exclut.

**Pourquoi ça compte / suite.** Le corollaire économise du travail futur : **toute
variante de « currency strength » qui se résout par une croisée directe est déjà
couverte par ce rapport, quelle que soit la formule de force employée** — la
formule ne peut pas créer d'information directionnelle que les prix des 28 paires
ne contiennent pas déjà sous forme du rendement de la croisée. Seules les variantes
multi-jambes y échappent, et elles paient 14 péages. Ligne ajoutée au [[ledger]].

**Links.** [[cross-sectional-vs-directional]], [[breadth]],
[[information-coefficient-and-ir]], [[exp-003-xsection-fx]],
[[exp-006-xsection-index-momentum]], [[exp-011-phase2-vol-pair-squeeze]],
[[exp-015-phase4-killzones-statarb]], [[exp-016-phase5-crypto-crosses]],
[[codebase-map]]. Rapport complet :
`rapport_quant_cross_sectional_pepperstone.md`.
