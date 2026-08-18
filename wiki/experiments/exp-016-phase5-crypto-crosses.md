---
type: experiment
id: exp-016
updated: 2026-08-14
status: done
verdict: no-edge
horizon: intraday M5 / M15, barrière verticale 6-16 bougies, mise à plat avant le rollover serveur
universe: BTCUSD, ETHUSD, GBPAUD, GBPNZD, EURAUD
code: [cryptolab/config.py, cryptolab/setups.py, cryptolab/labeling.py, cryptolab/run.py, cryptolab/validate.py, cryptolab/report.py, cryptolab/export_model.py, cryptolab/fetch.py, cryptolab/test_p5.py, live_ml_execution_phase5.py, check_live_parity_phase5.py]
---

# exp-016 — Phase 5 : crypto & croisées forex volatiles

**Hypothèse.** Les quatre phases précédentes ont buté sur le même mur : le bord brut
intraday vaut 3 à 50 fois moins que le péage du courtier. La Phase 5 ne cherche pas
un bord plus **grand**, elle cherche un actif dont l'**amplitude** rend le péage
petit — crypto et croisées volatiles. C'est une hypothèse sur le **dénominateur**.

**Setup.** 1 584 000 cellules, 600 modèles (2 400 ajustements), 5 actifs × 2 UT ×
5 déclencheurs (breakout 20/50, anomalie de volume, z-score 20/50) × 2 sens
(`follow`/`fade`), à partir de **23,4 M de barres M1** Pepperstone tirées pour
l'occasion (BTCUSD depuis 2016, ETHUSD depuis 2018, croisées depuis 2015/2007).
Étiquetage triple barrière relu **dans** le moteur de brackets, barrière verticale =
`min(6/12/16 bougies, mise à plat du jour)`, K-fold purgé + embargo 1 j + bande de
purge 5 j, sélection sur l'IS 70 % seul, lecture unique de l'OOS, BH-FDR q ≤ 0,10.
Grille rejouée intégralement **à coût nul**. Détails et code :
[`rapport_quant_phase5_pepperstone.md`](../../rapport_quant_phase5_pepperstone.md).

**Result. ZÉRO survivant FDR** sur 112 cellules gelées, **q_min 0,753** — mais 50 des
112 ont une espérance OOS positive, et **le contrôle à coût nul dit quelque chose de
neuf** :

| | % E[R] OOS brut > 0 | Médiane E[R] OOS brut | Péage médian | **Bord brut / péage** |
|---|---|---|---|---|
| Phase 4, killzones | 51,9 % (pile ou face) | +0,002 R | 0,076-0,093 R | 0,002-0,026 |
| **Phase 5, tous déclencheurs** | **78,7 %** | **+0,018 à +0,088 R** | **0,23 à 2,12 R** | **0,009-0,240** |

**Verdict.** ❌ Pas de bord déployable, et il manque **un facteur 4,2** dans le
meilleur cas de toute l'étude (GBPNZD M15). Mais la phase échoue pour une raison
neuve, et c'est le résultat.

1. ⭐⭐ **Le numérateur existe enfin — c'est la première fois.** À coût nul, 78,7 % des
   cellules sont OOS-positives (contre 51,9 % en Phase 4, soit du bruit), le
   classement IS→OOS est **meilleur en brut qu'en net** (+0,656 contre +0,591), et le
   top-décile du modèle bat son **témoin apparié** de **+0,052 R dans 84 % des
   cellules** (n = 108 000). Le signal est petit, réel et reproductible. Ceci
   **renverse** le diagnostic de [[exp-015-phase4-killzones-statarb]], où le Spearman
   net +0,776 tombait à −0,056 en brut : là le classement ne classait que le coût,
   ici il classe du bord.
2. ⭐⭐ **La crypto n'est pas une classe d'actifs, du point de vue du coût.** BTCUSD
   M15 paie **0,39 R** avec le stop du mandat — moins que n'importe quelle croisée.
   ETHUSD M5 en paie **3,60**, neuf fois plus. Arithmétique : le spread d'ETH vaut
   15,3 bp contre 5,6 bp pour BTC, presque 3×, sans que son ATR relatif suive.
   **Toute conclusion « la crypto est chère » ou « la crypto est bon marché » est
   fausse : il faut nommer l'actif ET l'UT.**
   > ⚠️ **Corrigé par la Phase 5b (voir plus bas).** La formule « BTCUSD M15 est le
   > moins cher de tout ce que ce projet a mesuré » ne valait que dans l'univers à
   > 5 actifs du mandat. Sur 9 actifs à mesure identique, l'or et les indices EU/US
   > sont **2 à 3× moins chers** : XAUUSD 0,129 · GER40 0,156 · NAS100 0,185 ·
   > BTCUSD 0,382.
3. ⭐⭐ **L'ATR local de la fenêtre améliore le RAPPORT, pas seulement le péage — ce
   qui corrige [[exp-014-six-pistes-ml-edge]].** exp-014 avait conclu que bord/péage
   est un **invariant de l'actif** (0,435 → 0,479 pour un stop 4,7× plus large). Ici
   il ne l'est pas : élargir R d'un facteur ~7 (ATR de la bougie → ATR du bloc de
   4 h) divise le péage par **7,2** et le bord par **3,7** seulement. Le rapport
   **double**, 0,076 → 0,149. Mécanisme : un stop large est touché moins souvent,
   donc plus de trades sortent à la barrière verticale avec un |R| petit — le bord se
   dilue moins vite que le coût. Il faudrait quand même ×6,7 de plus.
4. ⭐⭐ **Le mécanisme d'échec est maintenant LU dans le modèle, pas déduit.** Le
   `cost_atr` (péage / ATR) a été donné aux modèles exprès. Il ressort **dans 4 des 5
   meilleures cellules et premier dans 2** ; `blk_atr_ratio` et `session_left` sont
   dans les 5 ; les colonnes de **prix** (log-returns, z-score, VWAP, RSI, forme de
   bougie) sont **absentes du top-5 partout sauf une**. Le modèle a appris à chasser
   les barres bon marché, ne trouve du bord que dans les régimes agités, et un régime
   agité est précisément ce qui coûte cher. C'est [[exp-013-triple-barrier-ml-dedie]]
   confirmé **par l'importance des variables** au lieu de l'arithmétique.
5. ⭐⭐ **Quatrième confirmation, désormais quasi universelle : le modèle prédit la
   volatilité, pas la direction.** L'AUC « *une* barrière touchée » dépasse l'AUC
   « *laquelle* » dans **99,3 %** des 600 modèles, écart médian **+0,087** (Phase 4 :
   69,3 % et +0,052). À traiter comme un fait de la structure du problème.
6. ⭐ **La sélection in-sample a redécouvert le dénominateur toute seule.** Triée sur
   le seul t in-sample, la cohorte gelée est à **107/112 en M15**, **84/112 en
   `batr1.0`**, **63/112 en régime `expand`** — exactement les trois leviers que le
   contrôle à coût nul identifie comme réducteurs de péage. Elle n'a pas trouvé de
   bord : elle a trouvé le dénominateur, sans aide.
7. ⭐ **Deux acquis de marché, gratuits parce que mesurés sur les mêmes barres.**
   (a) Les croisées **suivent** (`follow` bat `fade` de 0,06 à 0,25 R sur les trois),
   ce qui contredit « les croisées volatiles sont mean-reverting » ; ETH est le seul
   actif où contrer est meilleur. (b) Le **week-end crypto est pire de 0,05 à
   0,08 R** et ce **n'est pas le spread** — le péage y est identique (BTC) ou plus
   faible (ETH). Le week-end porte moins de bord, il ne coûte pas plus cher.
8. ⭐ **Le choix du signal ne décide de rien, le choix de l'UT décide de tout.**
   Écart meilleur/pire déclencheur en M15 : 0,035 R. Écart M5→M15 pour un même
   déclencheur : 0,17 R, soit **5×**. C'est le filtre de coût d'exp-014 retrouvé sur
   un univers disjoint sans l'y chercher.

**Deux défauts d'outillage trouvés par la rigueur, pas par la chance.** Ils
concernent tout le dépôt, pas seulement cette phase :

* `gridlab.data.roll_mean_std` calculait la variance glissante par `E[x²] − E[x²]`
  sur des sommes cumulées de **prix bruts** — annulation catastrophique. Sur EURAUD
  M5, `bb_z` portait jusqu'à **0,6 %** d'erreur, et l'erreur **dépendait de la
  longueur de la fenêtre**, donc le live et le backtest ne calculaient pas la même
  feature. Corrigé par recentrage par blocs : erreur relative **6,4e-3 → 8e-8**.
  Toutes les phases en bénéficient.
* `session_left` se lisait sur `flat_idx`, qui sur la journée **en cours** pointe la
  barre la plus récente : en direct la feature aurait toujours valu ~0 alors qu'à
  l'entraînement elle valait les heures restantes. Corrigé pour se lire sur
  l'horloge. **Trouvé par `check_live_parity_phase5.py`, pas par un test unitaire.**

**Parité live prouvée deux fois.** (1) Colonne par colonne : zone convergée de
**9 857 points / 164 jours** sur le cas le plus dur (EURAUD M5). (2) **Parité de
DÉCISION** : 6 vraies minutes d'entrée rejouées à travers `Phase5Executor.score()`
lui-même → probabilité, sens et distance de stop **identiques au bit près**
(|Δ| = 0,0e+00). C'est le chemin de code qui envoie l'ordre qui est vérifié, pas une
reconstruction qui lui ressemble.

**Why it matters / next.** La phase **ferme** le triptyque « déclencheur intraday +
triple barrière + seuil de probabilité » sur M5/M15 : cinq phases, > 3 M de cellules,
zéro survivant FDR. Le M5 est **arithmétiquement clos** (péage 2,3× celui du M15 pour
le même bord). Mais ses propres chiffres pointent une direction unique et monotone :
le rapport bord/péage **s'améliore avec l'horizon**, à chaque échelle de stop et dans
chaque tableau. Rien ne dit que la courbe s'arrête à M15 — et
[[exp-014-six-pistes-ml-edge]] avait déjà noté que **3 des 4 briques déployées vivent
en D1**. La suite honnête n'est pas un sixième déclencheur intraday : c'est **H4/D1**,
où le même bord de +0,05 R se paie 0,02 R au lieu de 0,50.

**Links.** [[triple-barrier]], [[walk-forward-embargo]], [[leakage]],
[[prop-firm-universe]], [[exp-015-phase4-killzones-statarb]],
[[exp-013-triple-barrier-ml-dedie]], [[exp-014-six-pistes-ml-edge]],
[[exp-012-phase3-sweep-tbm-abrk]], [[ledger]].


---

## Suite — Phase 5b : le creusage du M15 (2026-08-14)

**Demande.** *« creuse m15 »*, après que la Phase 5 eut identifié deux axes qui
faisaient monter le rapport bord/péage et que le mandat plafonnait : l'horizon
(16 bougies max) et la largeur du stop (ATR de bloc 4 h).

**Setup.** Profil `p5b` (`CRYPTOLAB_PROFILE=p5b`, même code, Phase 5 gelée et
revérifiée bit-identique). M15 seul, **9 actifs** — les 5 du mandat plus NAS100,
US500, GER40, XAUUSD, comme l'impose la règle de test-universe. Horizons
6/12/16/24/32/**48** bougies (jusqu'à 12 h), stops `atr1.0` → `batr1.0` (4 h) →
`b8atr1.0` (8 h) → `d1atr1.0` (1 jour). **1 765 632 cellules, 540 modèles**, grille
rejouée à coût nul. Contrainte intraday inchangée. Rapport :
[`rapport_quant_phase5b_m15.md`](../../rapport_quant_phase5b_m15.md).

**Result. ZÉRO survivant FDR** sur 393 cellules gelées, **q_min 0,757** (216/393 ont
une espérance OOS positive). Surface bord brut / péage : **maximum 0,331**, contre
0,240 en Phase 5 — il manque toujours **un facteur 3,0**.

**Verdict.** ❌ L'axe est **épuisé**, et pour trois raisons distinctes, chacune
mesurée :

1. ⭐⭐ **La barrière verticale n'est PAS un levier de coût, et la Phase 5 se
   trompait de lecture.** Le péage par R est *rigoureusement* indépendant de
   l'horizon (six colonnes identiques) : il ne dépend que de ce qui définit R. Ce que
   la Phase 5 lisait comme « le rapport monte avec l'horizon » était l'effet
   **M5 → M15**, qui change l'ATR donc R. Le rapport monte quand même avec l'horizon,
   mais par le **numérateur** — et le point 3 dit de quoi ce numérateur est fait.
2. ⭐⭐ **La largeur du stop a un optimum INTÉRIEUR, et la Phase 5 était déjà
   dessus.** Le rapport culmine à `batr1.0` puis **redescend** : 0,331 → 0,313 →
   0,296. Le levier « ATR local de la fenêtre » est épuisé, pas sous-exploité —
   ce qui **complète** la correction d'[[exp-014-six-pistes-ml-edge]] du rapport
   principal : le rapport n'est ni invariant (exp-014) ni monotone (ma lecture de la
   Phase 5), il a un maximum.
3. ⭐⭐⭐ **Le meilleur point de la surface est du BÊTA, démontré par un contrôle
   dédié.** À `batr1.0` × 48 bougies, GER40 atteint un rapport de **0,996** avec une
   espérance nette médiane *positive* (+0,0104 R), XAUUSD 0,640, NAS100 0,550 — et
   `follow` était net-positif sur les 5 déclencheurs de GER40. En séparant par **sens
   réel du trade** : **0 actif sur 9** a ses deux sens rentables, et l'asymétrie
   `long − short` est corrélée à **+0,71** (p=0,031) au rendement d'une position
   longue permanente sur la même fenêtre OOS, **de signe concordant sur 9/9 actifs**.
   ETHUSD le prouve par l'exception : seul actif à dérive OOS négative, seul actif
   dont les shorts battent les longs. Sur un indice dont la séance fait ~36 bougies
   M15, « 48 bougies » veut dire « tenir jusqu'à la clôture ». `cryptolab/driftcontrol.py`.
4. ⭐⭐ **Le contrôle de dégénérescence retire ce qui restait.** Part des trades
   touchant encore une barrière horizontale : `atr1.0` 73→94 %, `batr1.0` 6,5→41,5 %,
   `b8atr1.0` 2,3→22,1 %, **`d1atr1.0` 0,7→5,1 %**. Aux stops larges ce n'est plus
   une triple barrière, c'est une position tenue N bougies.
   `cryptolab/degeneracy.py`.
5. ⭐ **Correction factuelle sur les coûts.** « BTCUSD M15 est le moins cher du
   projet » était un artefact de l'univers à 5 actifs. Sur les 9, à mesure identique :
   **XAUUSD 0,129 · GER40 0,156 · NAS100 0,185 · US500 0,352 · GBPNZD 0,366 ·
   BTCUSD 0,382 · GBPAUD 0,404 · EURAUD 0,468 · ETHUSD 1,298**. L'or et les indices
   EU/US sont 2 à 3× moins chers que le BTC.

**Ce que cela change pour la suite.** L'argument « passer en H4/D1 » de la Phase 5
reposait sur l'extrapolation de la courbe horizon — **cette étude montre que cette
courbe ne mesurait pas ce qu'on croyait**. L'argument tient toujours, mais pour une
raison différente et plus solide : ce n'est pas que l'horizon réduit le péage (il ne
le fait pas), c'est que le D1 **change l'unité de R**. Corollaire obligatoire : y
appliquer le contrôle de dérive du point 3, parce qu'un horizon plus long capte
encore plus de bêta.

**Acquis d'outillage.** `cryptolab/multihorizon.py` résout tous les horizons en UNE
passe (les courbes d'excursion sont monotones, donc l'indice du premier
franchissement ne dépend pas de l'horizon) : **×3,3**, équivalence algébrique
vérifiée sur de vraies barres (écart 1,9e-6, mêmes NaN).
