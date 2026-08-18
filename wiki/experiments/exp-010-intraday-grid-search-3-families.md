---
type: experiment
id: exp-010
updated: 2026-08-12
status: done
verdict: no-edge
horizon: intraday strict (aucune position ne survit à la séance)
universe: NAS100, US500, US30, GER40, FRA40, XAUUSD, EURUSD, GBPUSD, USDJPY, EURJPY, USDCAD
code: [gridlab/data.py, gridlab/engine.py, gridlab/families.py, gridlab/run_grid.py, gridlab/validate.py, gridlab/control.py, gridlab/winner.py, gridlab/report.py, gridlab/test_engine.py, gridlab/fetch_mt5.py]
---

# exp-010 — Grid search intraday exhaustif : ORB, retour à la moyenne, momentum

**Hypothèse.** Une des trois familles intraday canoniques (Opening Range Breakout,
retour à la moyenne intraday, momentum intra-séance), poussée sur *toute* sa matrice
de paramètres et sur *tous* les actifs prop, contient une cellule à espérance nette
positive qui survit hors échantillon.

**Setup.** M1 Pepperstone tirée en direct de MT5 ([`gridlab/fetch_mt5.py`](../../gridlab/fetch_mt5.py)),
M5/M15/H1 rééchantillonnées de la M1 pour partager horloge et trous. **3 227 640
combinaisons énumérées, 2 512 026 évaluées, 2 088 jeux d'entrées** simulés à la
résolution M1, IS 70 % / OOS 30 %. Deux échelles de stop : ATR de l'unité de temps
(passe 1) et **ATR journalier de la veille** (passe 2, ajoutée pour falsifier le
réflexe « élargir le stop »). Coût = spread de la barre d'entrée (planchers Razor) +
0,5 pip de slippage par côté, déduit trade par trade.
Rapport complet : [`rapport_grid_search_quant_pepperstone.md`](../../rapport_grid_search_quant_pepperstone.md).

**Résultat.**

* **Zéro survivant.** Sur 1 622 cellules gelées en IS (50 par famille × actif, ≤ 6 par
  signal), aucune ne passe Benjamini-Hochberg à q ≤ 0,10 ; **q minimum = 0,287**.
* **Spearman(E[R] IS, E[R] OOS) = −0,056** et 47,4 % de cellules positives en OOS. Le
  classement in-sample ne contient aucune information sur l'avenir.
* **Pas de bord brut.** Le coût est récupérable algébriquement (`net = brut − coût`,
  exact, vérifié à 1,6·10⁻⁷ près) : à coût nul, l'espérance médiane reste négative aux
  quatre UT et pour les trois familles (ORB H1 −0,0019 R, le moins mauvais).
* **Invariance d'échelle du stop, mesurée.** Neuf variantes couvrant un facteur 23 de
  largeur (coût 0,028 → 0,648 R) laissent le rapport brut/coût entre **−0,08 et −0,21**.
  En M1, l'échelle journalière divise le coût par 15 **et** le brut par 10.
* **Placebo :** entrées aléatoires dans le même moteur, 44 couples (actif, UT),
  espérance brute **−0,0034 R**, taux de gain **0,4980** — ni fuite, ni fill optimiste.
* **Le meilleur candidat est du bêta de tendance.** MOM USDJPY M5 (canal 10,
  0,25×ATR(D1), TP 3R, 08:30 UTC, tendance H1, long) : OOS n=282, E[R] +0,319, PF 1,66,
  t journalier 3,62 — mais **q = 0,287**, réplication 6/11 actifs à médiane +0,045 R,
  et ses 7 années OOS positives sont exactement les 7 ans de dépréciation du yen alors
  que 7 de ses 15 années IS sont négatives.

**Verdict.** ❌ **no-edge.** Les trois familles, prises comme règles autonomes sur
OHLCV, sont des impasses sur cet univers chez ce courtier. Le problème n'est pas le
réglage, c'est le bord — une grille plus fine ne peut rien produire.

**Ce que l'échec apprend (et qui vaut plus que le verdict).**

1. Le **retour à la moyenne intraday existe sur le forex et pas sur les indices** :
   brut H1 +0,0078 R (GBPUSD), +0,0057 (USDCAD) contre −0,0259 (NAS100), −0,0240
   (XAUUSD). Réel, mesuré sur 219 870 cellules, et **neuf fois trop petit** pour le
   péage Pepperstone. Nuance à opposer à « la réversion est morte partout ».
2. **Trois zones seulement passent le brut au positif dans toute l'étude**, et elles
   désignent la même chose : momentum à 09:00 UTC (+0,0069 R) et 13-14:00 UTC (+0,0006
   / +0,0033), ORB sur range de Londres ≥ 15 min (+0,0009 à +0,0094). **La première
   heure après une ouverture majeure.** Toutes manquent leur péage d'un facteur 3 à 10.
3. **Limite de flux Pepperstone à retenir pour toute étude future** : la M1 réelle ne
   commence qu'en **2017** (NAS100, US30, XAUUSD, FRA40) et **2020** (US500, GER40) ;
   avant, le serveur répond une barre par jour. Le forex, lui, remonte à **2005**
   (7,9 M barres). Le filtre de densité de [`gridlab/data.py`](../../gridlab/data.py)
   tronque automatiquement — même piège que le 2026-08-12 sur HMASTO.
4. **L'aplat de séance bat toutes les cibles fixes** (−0,107 contre −0,127 à −0,144 R),
   et la cible mobile « retour à la VWAP » est la pire de toutes. Mais l'étalement des
   gestions de sortie vaut 0,04 R quand le coût en vaut 0,20 à 1,00 : optimiser la
   sortie d'une entrée sans bord est une perte de temps, désormais chiffrée.

**Contrôle supplémentaire — la recherche GROUPÉE cross-actifs (2026-08-12, après coup).**
Le classement initial était *par actif*, ce qui ne peut pas trouver une brique de book :
une brique, ici, c'est une configuration qui tient sur **plusieurs actifs à la fois**
([[breadth]], [[exp-004-xsection-breadth-poc]]). J'ai donc regroupé les 2,5 M de cellules
par **configuration seule** ([`gridlab/pooled.py`](../../gridlab/pooled.py)) : 261 726
configurations distinctes, 236 970 tradées sur ≥ 6 actifs.

Cela fait apparaître un objet que la recherche par actif ne voyait pas : **momentum M15,
cassure de canal, aplat de séance, fenêtre 13:30 UTC (ouverture NY), aligné H1, LONG
seulement** — et les **quatre** longueurs de canal (10/20/50/100) sont positives en OOS
ensemble, sur 7 à 9 actifs sur 11. C'est un plateau, pas une pointe.

**Mais le t par trade y est massivement gonflé** : la configuration se déclenche le même
jour sur NAS100, US500, US30, GER40 et FRA40, corrélés à ~0,9 — cinq trades qui valent
un pari. Test honnête ([`gridlab/pooled_daily.py`](../../gridlab/pooled_daily.py)) : R
sommés **par jour, tous actifs confondus**, 703 jours OOS.

| | in-sample | out-of-sample |
|---|---:|---:|
| trades / jours | 2 185 / 1 484 | 1 108 / 703 |
| total R | +117,3 (+5,9 R/an) | +85,2 (**+13,4 R/an**) |
| E[R] par trade | +0,054 | +0,077 |
| max drawdown | 78,1 R | **44,0 R** |
| t par trade (gonflé) | 1,18 | 1,24 |
| **t par JOUR (honnête)** | **1,00** (p 0,16) | **1,06** (p 0,14) |

**Rejeté, et pour quatre raisons cumulatives :** (1) t journalier OOS **1,06** contre une
barre de projet à 2 ; (2) **le in-sample n'est pas significatif non plus** (t 1,00) — il
n'y avait rien à découvrir, la sélection groupée a remonté une dérive plate ; (3)
RoMaD 1,9 (85,2 R pour 44,0 R de drawdown) contre 2,4-2,6 pour le book gelé
d'[[exp-008-crypto-breakout-3rd-brick]] ; (4) **concentration** — USDJPY +46,8, NAS100
+38,6 et GER40 +25,4 (sur 35 trades seulement) portent tout, pendant que GBPUSD −30,2 et
USDCAD −30,4 perdent 60 R à eux deux. Le « 9/11 actifs positifs » cache une asymétrie de
magnitude massive. Et mécaniquement c'est **long-only à l'ouverture de New York** : la
même famille que la brique 1, donc probablement pas un diversifiant (corrélation non
mesurée ici — à vérifier si l'idée revenait).

Ordre de grandeur pour situer : à +0,12 R par jour de bourse et à la variance observée,
atteindre t = 2 demanderait ~2 500 jours de hors-échantillon, soit **une dizaine
d'années**. Ce n'est pas « presque » significatif, c'est une dérive faible.

**Pourquoi ça compte / suite.** Ferme définitivement ORB, réversion intraday et
momentum de canal comme sources de brique. Ce qui reste ouvert et n'est **pas** dans
cette grille : la géométrie d'entrée « ouverture ± k×ATR(D1) » (= [[exp-005-mt5-intraday-vol-breakout]],
déjà validée sur ticks), la coupe transversale, et tout ce qui apporte une information
hors OHLCV.

**Livrables.** [`rapport_grid_search_quant_pepperstone.md`](../../rapport_grid_search_quant_pepperstone.md),
[`gridlab/`](../../gridlab), [`mql5/IntradayMomentum_Grid.mq5`](../../mql5/IntradayMomentum_Grid.mq5)
(meilleur candidat, avertissement q=0,287 en tête de fichier),
[`mql5/IntradayORB_Grid.mq5`](../../mql5/IntradayORB_Grid.mq5) (référence famille A).

**Links.** [[ledger]], [[exp-005-mt5-intraday-vol-breakout]], [[walk-forward-embargo]],
[[prop-firm-universe]], [[lessons]].
