---
type: experiment
id: exp-013
updated: 2026-08-13
status: done
verdict: no-edge
horizon: intraday strict M15/H1 (aucune position ne survit a la seance)
universe: NAS100, US500, US30, GER40, XAUUSD, EURUSD, GBPUSD, USDJPY, USDCAD
code: [tbmlab/config.py, tbmlab/features.py, tbmlab/labeling.py, tbmlab/run.py, tbmlab/validate.py, tbmlab/rank_value.py, tbmlab/report.py, tbmlab/export_model.py, tbmlab/test_tbm.py, live_ml_execution.py, check_live_parity.py]
---

# exp-013 — Triple barriere ML dediee : la grille d'etiquettes elargie, et le mecanisme d'echec chiffre

**Hypothese.** Reprise du mandat « triple barriere » de [[exp-012-phase3-sweep-tbm-abrk]]
sur une grille d'etiquettes **quatre fois et demie plus large** (TP 1,5 / 2,0 / 3,0 R
x barriere temporelle 8 / 12 / 16 bougies, contre 2 jeux en P3), l'univers exact du
mandat — dont **USDCAD, jamais teste ici** — et un **tampon IS/OOS explicite** au lieu
d'un tampon implicite. Question : la conclusion « le modele predit la volatilite »
tient-elle sur toute la grille, et *de combien* manque-t-on ?

**Setup.** Cache M1 Pepperstone **rafraichi en direct du terminal le jour meme**
(9 actifs, jusqu'au 2026-08-13 15:34 UTC ; USDJPY re-tire annee par annee apres un
echec de l'appel plein). M15/H1 reechantillonnees depuis ce M1, resolution des fills
en M1. Moteur de brackets = [`gridlab/engine.py`](../../gridlab/engine.py), **deja
verifie**, aucun moteur neuf. Nouveaute de protocole : `gridlab.data.bars_from_df`
extrait, de sorte que le cache de recherche et le flux live passent par **un seul
constructeur de barres**. **972 modeles, 3 888 ajustements, 279 936 cellules,
3 491 s d'horloge sur 5 processus.** Rapport :
[`rapport_quant_triple_barrier_pepperstone.md`](../../rapport_quant_triple_barrier_pepperstone.md).

**Resultat.**

* **ZERO survivant FDR**, q_min **0,455** (contre 0,196 en P3 — la selection porte ici
  sur des cellules individuelles a petit n, pas sur une config conditionnelle).
* ⭐ **LA CONCLUSION DE P3 TIENT, ET ELLE A MAINTENANT UNE PREUVE ARITHMETIQUE.**
  AUC OOS moyenne **0,654** sur l'etiquette « TP en premier », **0,840** sur « une
  barriere quelconque est touchee ». Du Q1 au Q5 : TP du sens entraine **x4,0**, TP du
  sens **oppose x3,7**, ensemble. **Et le decisif : long et short sont brut-positifs
  EN MEME TEMPS** (+0,074 et +0,042 R). Aucun signal directionnel ne peut faire cela ;
  une selection de volatilite sous barriere **asymetrique** (TP > SL) le fait par
  construction — une barre assez agitee touche le TP lointain de quelque cote qu'on
  la prenne. Le diagnostic n'est plus une interpretation, c'est une identite.
* ⭐ **L'AUC MONTE QUAND LA CIBLE S'ELOIGNE** : 0,63 a 1,5 R, 0,66 a 2 R, **0,69 a 3 R**
  (taux de base 0,31 / 0,23 / 0,13). Plus la cible est lointaine, plus la question
  devient purement une question de volatilite — **la signature se lit dans le SENS DE
  VARIATION**, pas dans le niveau. Nouveau, et c'est le test le plus rapide pour
  reconnaitre le piege sur une future etiquette.
* ⭐ **CE QUE VAUT LE CLASSEMENT, ISOLE DE TOUT** ([`tbmlab/rank_value.py`](../../tbmlab/rank_value.py),
  2 916 mesures) : `E[R | top q %] − E[R | chaque barre]`, sans recherche de seuil ni
  killzone, dans les deux moities. **+0,051 R/trade brut OOS au top 5 %**, monotone
  (top 30 % +0,027 → top 10 % +0,042 → top 5 % +0,051), **positif dans les DEUX
  moities pour 59,1 % des modeles**. Le modele voit quelque chose de reel.
* ⭐ **ET IL EN REND 61 % EN SPREAD.** Apport brut +0,0509 R, apport **net** +0,0196 R.
  L'ecart (0,031 R) est le surcout des barres choisies : **le modele trouve les barres
  agitees, et les barres agitees sont les plus cheres**. C'est le mecanisme precis de
  l'echec, chiffre pour la premiere fois.
* **La base engloutit le reste** : E[R] net de « prendre chaque barre » = **−0,064 R**
  en H1, **−0,179 R** en M15. L'apport comble **53 %** du trou en H1 et **3 %** en M15.
  Flux du top 5 % : −0,030 R (H1), −0,174 R (M15).
* **Presque aucune persistance par configuration** : 4,8 % des 972 configurations ont
  un flux net-positif dans les deux moities (1,8x le hasard, coherent avec l'apport
  reel — et **95,2 % echouent**).
* **LES SEUILS ABSOLUS DU MANDAT, MESURES** : sur 135 396 cellules retenues,
  `P > 0,70` en produit **0**, `P > 0,65` **12** (0,009 %), `P > 0,60` **336**.
  Les quatre seuils reunis couvrent **1,9 %** de la grille. Confirme P3 et le chiffre.
* ⭐ **LE SPEARMAN IS→OOS EST UN ARTEFACT DE PEAGE, ET ON PEUT ENFIN LE MONTRER.**
  +0,613 en net, **+0,187 en brut**. Demonstration : trie par decile d'esperance IS,
  **le decile le PIRE a le MEILLEUR brut OOS** (+0,115 R contre +0,073 pour le
  meilleur decile). Le classement IS trie les cellules par leur COUT. Ceci resout
  l'avertissement laisse ouvert en P2 et P3 (« non residualise, une part mesure le
  peage ») : la part est l'essentiel.
* **80,1 % des cellules sont brut-positives OOS, 21,4 % net-positives, et 51,2 %
  brut-positives dans les deux moities** — un pile ou face.
* **Le stop, encore.** Peage 0,208 R (atr1.0, le stop du mandat) contre 0,045 R
  (0,5xATR(D1)) — 4,6x. **Nuance nouvelle et importante** : un stop plus large agrandit
  le R donc retrecit AUSSI le bord brut (0,090 → 0,021 R) ; le rapport bord/peage ne
  bouge presque pas (0,43 → 0,47). Ce n'est **pas** « le meme bord pour moins cher »,
  c'est une mise a l'echelle. Ce qui reste vrai : en valeur absolue le choix du stop
  deplace le net de **0,094 R** quand le modele n'en deplace que **0,020** — **5x**.
* **M15 est domine par H1 sans condition** : peage 1,9x pour un brut equivalent.
* **USDJPY** porte le plus gros apport de l'univers (+0,107 R brut OOS) et **reste
  net-negatif dans les deux sens** (−0,021 long, −0,141 short). L'avertissement du
  [[ledger]] tient.

**Verdict.** **Aucune brique, aucune candidate, rien a mettre en forward-test.** La
famille est fermee sous cette forme. Ce qui manque n'est pas un reglage : l'apport du
modele est mesure (+0,051 R brut) et le peage sur les barres qu'il choisit vaut
0,106 R. Le manque est un facteur ~3, et les 61 % rendus en spread disent qu'il est
**structurel** — on ne peut pas selectionner de la volatilite sans selectionner du
spread.

**Controles.** [`tbmlab/test_tbm.py`](../../tbmlab/test_tbm.py), **9/9 PASS**. Le seul
qui donne un sens aux AUC : **etiquettes permutees → AUC 0,496 contre 0,658**. Plus
un rejeu barre par barre de 6 000 trades par un code ne partageant rien avec le moteur
vectoriel (6 000/6 000 identiques), la causalite des features par troncature du futur
(ecart 0,0), et le tampon IS/OOS (152 entrees SUPPRIMEES, ecart 10 jours).

**Live.** [`live_ml_execution.py`](../../live_ml_execution.py) est complet et
**DESARME**. La parite est **structurelle** : le live tire les M1 du terminal, les
passe a `gridlab.data.bars_from_df` — le meme constructeur que le cache — puis appelle
`tbmlab.features.build`, la fonction meme de l'entrainement. Il n'existe qu'une
implementation de chaque feature. [`check_live_parity.py`](../../check_live_parity.py)
mesure **9,9e-06 sur 2 288 barres H1**, et **mesure** ou s'arrete le rodage (989 barres,
la convergence de l'ATR(100)) au lieu de le supposer — d'ou une fenetre live de
200 000 barres M1. Sizing verifie sur le compte : un stop touche coute **0,249 %**
pour une cible de 0,250 %.

**Pourquoi ca compte / suite.** Trois regles transferables sortent d'ici et valent
au-dela de la triple barriere : **(1)** le test long/short simultane est le diagnostic
de volatilite le moins cher qui existe — deux lignes, verdict immediat ; **(2)** un
Spearman IS→OOS doit etre **recalcule en brut** avant d'etre presente comme une
reproductibilite ; **(3)** un seuil de probabilite absolu n'a de sens que rapporte au
taux de base de l'etiquette. La seule direction restee ouverte — faire porter la
selection de volatilite par un instrument **dont le paiement est la volatilite** — est
fermee par la contrainte prop-firm (CFD, pas d'options).

**Links.** [[exp-012-phase3-sweep-tbm-abrk]], [[exp-002-v3-mt5-four-angles]],
[[exp-001-v1-single-tf-direction]], [[triple-barrier]], [[walk-forward-embargo]],
[[leakage]], [[prop-firm-universe]], [[ledger]], [[lessons]], [[system]].
