---
type: experiment
id: exp-018
updated: 2026-08-17
status: done
verdict: no-edge
horizon: swing D1 / W1, 10 a 60 jours ouvres
universe: 19 actifs Pepperstone (NAS100, US500, US30, GER40, FRA40, XAUUSD, 7 majeures FX, 6 croisees)
code: [swinglab/config.py, swinglab/costs.py, swinglab/data.py, swinglab/engine.py, swinglab/families.py, swinglab/xsection.py, swinglab/ml.py, swinglab/run.py, swinglab/validate.py, swinglab/driftcontrol.py, swinglab/report.py, swinglab/test_engine.py, live_swing_execution.py, check_live_parity_swing.py]
---

# exp-018 — Swing D1 / W1 : l'horizon qui devait ecraser le peage

**Hypothese.** Les phases 1 a 5 ont mesure cinq fois qu'un bord intraday existe mais
vaut 4 a 15 fois moins que sa friction. Le mandat propose d'attaquer le
DENOMINATEUR : a 100-400 pips d'amplitude, le meme spread ne pese plus rien. Quatre
familles swing (trend-following, cross-sectionnel hebdomadaire, reversion extreme,
triple barriere ML) sur D1/W1, en R nets, frais et **swaps** Pepperstone compris.

**Setup.** `swinglab/`. 19 actifs, D1 (signal) + H1 (resolution des barrieres),
historique MT5 PepperstoneUK-Demo 2008-08-07 → 2026-08-14, frontiere IS/OOS
**2021-03-18** posee sur l'intersection des historiques. Peage ADDITIF mesure sur le
flux (`swinglab/costs.py`) : mediane des spreads non nuls en heures liquides +
commission Razor convertie en points + **1,0 pip de slippage PAR COTE** + le
**swap**, lu sur le terminal dans les deux modes qu'il declare (points pour le FX et
l'or, interet annuel en % pour les CFD d'indices) avec le jour de triple rollover.
Le moteur (`swinglab/engine.py`) resout le bracket de TOUTE barre, dans les deux
sens, sous 120 geometries — donc les 4 familles partagent exactement la meme
arithmetique de sortie et aucune ne peut gagner par une sortie plus indulgente.
Regle d'occupation (une position a la fois), purge exacte a la frontiere, gel sur
l'IS seul puis BH-FDR sur l'OOS. **7 preuves du moteur** dans
`swinglab/test_engine.py` (cible, stop, gap paye a l'ouverture, barriere verticale,
symetrie long/court, alignement D1↔H1 sur les 19 actifs reels, degenerescence).

**Result.** **156 188 cellules, 8 modeles LightGBM, cohorte gelee de 120 :
q_min 0,0199, 1 survivant FDR — et il tombe sur les controles qui suivent.**

⭐⭐⭐ **LA PREMISSE DU MANDAT EST VRAIE, ET ELLE NE SUFFIT PAS.** Le rapport
bord-brut/peage passe **au-dessus de 1 pour la premiere fois du projet** : 2,5 a 3,6
dans le decile superieur du brut IS, contre un maximum de **0,33** sur tout
l'intraday (exp-015). L'obstacle arithmetique de cinq phases est leve. Et pourtant :
**rejouee a cout nul, la grille n'a que 37,8 % de cellules OOS positives** (mediane
−0,017 R, moyenne −0,034 R) — moins qu'un pile ou face. **L'intraday echouait sur le
denominateur ; le swing echoue sur le numerateur.** C'est un mode d'echec NEUF, et
il retire de la valeur a toute piste future du type « trouver un vehicule moins
cher » : le vehicule le moins cher a ete trouve, il ne contient rien.

⭐⭐⭐ **LE PEAGE NE DISPARAIT PAS, IL CHANGE DE NATURE — ET IL RE-CLASSE L'UNIVERS.**
Le spread est plat a **0,0297 R** quelle que soit la duree (3 % de R contre 40-100 %
en M5/M15), mais le swap croit avec elle : a 20 jours et a l'achat il vaut **72 % du
peage total**, a 60 jours **75 %**. Il est **asymetrique** (0,020 R a la vente contre
0,075 R a l'achat : financer un CFD long et porter une devise a taux bas se paient
dans le meme sens). Surtout, il **inverse le classement des actifs** : l'or, l'actif
au spread le moins cher du depot (1R/spread = 133), paie **0,68 R de portage par
trade long de 20 jours** et tombe a **1R/peage = 1,46** ; les indices tombent a 7-14 ;
les paires a portage positif (USDCAD 159, USDCHF 127, AUDJPY 61, USDJPY 60) montent.
**La liste des actifs exploitables en swing n'est pas celle des actifs exploitables
en intraday** — table complete au §3.3 du rapport.

⭐⭐⭐ **RIEN N'EST MUTUALISABLE SUR L'UNIVERS — le test le plus severe de la phase, et
il a ete ajoute apres coup en reponse a la question « y a-t-il vraiment RIEN pour le
book ? ».** Le gate FDR juge des cellules mono-actif ; pour un book, la preuve forte
est une CONFIGURATION qui marche sur beaucoup d'actifs a la fois. Chaque configuration
(meme signal, meme bracket) mutualisee a travers >= 15 actifs, en exigeant esperance
poolee positive **dans les deux moities** ET majorite d'actifs positifs :
**0 configuration sur 6 417**, quand le hasard seul en donnerait **25 %**. Observer
0 a 6 % selon le panier ne dit donc pas « aucune information » mais **biais
systematiquement negatif** : le peage et le stop dur tirent la mediane sous zero dans
les deux moities a la fois. La cohorte gelee legitimement (10 meilleures configurations
par t poole IN-SAMPLE) rend un **t OOS maximal de −0,35 et 0 % de configurations
positives**. L'effondrement est spectaculaire et instructif : `f3_z thr=2,0` en
reversion inversee a **89,5 % des 19 actifs positifs et t poole IS 4,34 sur 5 085
trades** → **t OOS −0,93** ; `f3_rsi(2)` a 73,7 % d'actifs et t IS 4,86 → **t OOS
−0,48**. ⭐⭐ **Et l'hypothese que ce rapport avait lui-meme produite echoue aussi** :
restreindre aux 5 actifs a portage favorable (1R/peage 42-159) monte la part de
0,00 % a 1,12 %, soit encore **vingt fois sous le hasard**, cohorte gelee plafonnant a
t OOS 0,69. Les cellules a t OOS 2,3-2,8 du panier d'indices ont un t IS de 0,13-0,27 :
**on ne pouvait les trouver qu'en regardant la reponse.** Artefacts :
`swinglab/_out/pooled_screen.csv`, §5bis du rapport.

⭐ **LA SEULE PISTE NEUVE, ET POURQUOI ELLE N'EST PAS CONSTRUITE.** En traitant le swap
comme un COUT, la grille est passee a cote du fait qu'il est aussi un REVENU du bon
cote : long USDCHF encaisse +0,045 R sur 20 jours, USDCAD +0,028, AUDJPY +0,028, soit
**+1,0 a 1,5 R/an par actif de portage pur, sans pari directionnel** — le carry trade
classique, jamais teste dans ce depot. Trois raisons de s'arreter la : **(a)
inbacktestable avec cette source** — MT5 ne sert que le taux COURANT, et un carry trade
est *entierement* fait de taux, donc le rejouer sur 18 ans au taux de 2026 ne mesure
rien (limite de nature, pas de precision) ; **(b) le stop dur transforme son risque en
−1R recurrents** (le portage paie ~1,2 R/an et se denoue en quelques jours de −5 a
−10 % : yen 1998, 2008, aout 2024) ; **(c) ce ne serait pas une brique decorrelee** —
les 4-5 noms porteurs sont la meme position (short JPY/CHF finance en USD), un pari
macro unique. A rouvrir seulement avec une source portant l'HISTORIQUE des taux de
swap.

⭐⭐ **LE SEUL SURVIVANT FDR EST UN ARTEFACT DE REGIME, ET LES CONTROLES LE DISENT.**
XAUUSD W1 Donchian-50 en momentum, stop 1,0 × ATR14(D1), cible +2R, maintien 10 j :
OOS n = 27, **E[R] +1,071 R, t = 4,13, q = 0,0199**, PF 4,78, decorrele des 4 briques
du book (|ρ| ≤ 0,04), plateau 100 %, insensible au swap (×0 : +1,139 ; ×2 : +1,004),
au-dessus de son temoin de direction apparie (+0,193) et de son temoin « chaque
barre » (+0,124). Il echoue ensuite sur **quatre** controles : **73 % du P&L OOS dans
la seule annee 2025** (sans 2025 : n = 13, t = 1,44) ; **25 trades longs sur 27** ;
**12 actifs sur 19 negatifs** sur la configuration EXACTE (mediane −0,074 R, moyenne
+0,003 R — regle de test-universe) ; et ses **120 brackets freres perdent en IS**
(mediane −0,129 R) pour gagner en OOS (+0,796 R). Ses trades tiennent **3,4 jours** :
ce n'est pas un swing, c'est « en 2025 l'or parcourait deux ATR journaliers avant
d'en reprendre un ». **Lecon a garder : le FDR contient le risque de fausse decouverte
STATISTIQUE, pas le risque de REGIME. Les deux temoins de derive l'ont laisse passer
parce qu'ils comparent des moyennes, pas des concentrations ; c'est la concentration
annuelle et la replication multi-actifs qui l'attrapent.**

⭐⭐ **FAMILLE 4 — 5ᵉ CONFIRMATION CONSECUTIVE, ET LE MECANISME EST LU, PAS DEDUIT.**
Dans **6 modeles sur 8** l'AUC OOS de « une barriere quelconque est touchee » depasse
celle de « laquelle » (0,54-0,63 contre 0,50-0,58) : le modele apprend la volatilite,
pas la direction — apres 69 % en Phase 4 et 99,3 % en Phase 5. Et `cost_atr` /
`swap_atr` sont les **deux features dominantes des 8 modeles sur 8** : elles avaient
ete mises dans le jeu exactement pour rendre ce diagnostic LISIBLE. Le modele ne
cherche pas un sens, il cherche ou le bracket est bon marche. Transposition exacte au
D1 du mecanisme d'echec d'exp-016.

⭐ **FAMILLE 2 — 3ᵉ CONFIRMATION QUE CET UNIVERS N'A PAS DE CROSS-SECTION.** 13 440
cellules, **meilleur t IS = 0,875**, 3,9 % de cellules OOS positives (la plus basse
des quatre familles), rapport bord/peage **0,4** — le seul du rapport a rester sous 1,
parce qu'un panier long-K/short-K paie **2K peages pour un seul pari**. Meme
arithmetique qu'exp-011 (paires intraday) et qu'exp-017 (panier neutre), en plus
doux. Apres exp-003 (intraday FX) et exp-006 (indices), c'est le troisieme horizon
ou 19 noms correles par la jambe USD ne fournissent pas le √N de la loi fondamentale.

⭐ **TRANSFERT IS → OOS QUASI NUL.** Spearman(E[R] IS, E[R] OOS) = **+0,053** net et
**+0,044** brut sur 156 188 cellules. Meme ordre qu'en Phase 1 (−0,056), tres loin des
+0,66 de la Phase 5. Sur cet horizon, choisir la meilleure cellule in-sample revient
a tirer au sort — ce qui est exactement ce que la carriere du survivant illustre.

⭐ **CONTROLE DE DERIVE : LE BETA LONG DES INDICES EST DEJA MANGE PAR LE PORTAGE.**
Temoin « chaque barre » (1,5 × ATR / +2R / 20 j) sur 2008-2026 : les indices actions
rendent **+0,0 R/an en moyenne** net de financement, seul NAS100 reste positif
(+24,6 R/an) et l'or est **−110 R/an** a l'achat. Le risque de confondre un bord avec
du buy-and-hold est donc plus faible qu'attendu sur cet horizon — le stop dur et le
swap suffisent a effacer la derive — mais NAS100 reste a traiter comme suspect.

⭐ **PARITE LIVE EXACTE AVANT PRODUCTION.** `swinglab/data.asset_from_frames` est
l'unique constructeur d'`Asset` du depot : la recherche lit le cache parquet,
`live_swing_execution.py` tire ses barres de MT5, tous deux passent par la meme
fonction puis par le meme generateur de signaux. `check_live_parity_swing.py` rejoue
400 jours en tronquant les frames comme MT5 les aurait servies : **4 strategies sur
4, dates d'entree identiques et ecart 0,0e+00 sur l'unite de risque.**

**Verdict.** ❌ **no-edge.** Aucune brique proposee. La contribution de la phase n'est
pas un survivant, c'est un DIAGNOSTIC : l'obstacle arithmetique qui expliquait les
cinq echecs precedents a ete leve, et l'echec persiste. Le probleme n'etait donc pas
seulement la friction.

**Why it matters / next.**
1. **Ne plus chercher un vehicule moins cher.** Le rapport bord/peage est passe de
   0,33 a 3,6 et n'a rien libere. Les pistes « crypto pour ecraser le peage »
   (exp-016), « elargir le stop » (exp-014) et celle-ci epuisent cet axe.
2. **Toute recherche swing future commence par la table de portage** (§3.3 du
   rapport) : le meme bord brut est exploitable sur USDCAD et pas sur l'or, et
   l'ecart est d'un facteur 100. Le portage est le nouveau denominateur.
3. **Ajouter la concentration annuelle et la replication multi-actifs au gabarit de
   validation** — le FDR seul a laisse passer le survivant, ces deux controles l'ont
   arrete. Voir aussi [[test-universe-rule]].
4. Le stop dur reste structurant : avec un stop a 1-2 × ATR(D1), un signal
   HEBDOMADAIRE produit des trades de 3 jours. Un vrai swing demande de repenser ce
   que vaut 1R avant de rejouer la matrice SL/TP.

**Links.** [[exp-010-intraday-grid-search-3-families]], [[exp-014-six-pistes-ml-edge]],
[[exp-015-phase4-killzones-statarb]], [[exp-016-phase5-crypto-crosses]],
[[exp-017-xsection-fx-intraday]], [[exp-003-xsection-fx]],
[[exp-006-xsection-index-momentum]], [[triple-barrier]], [[walk-forward-embargo]],
[[breadth]], [[prop-firm-universe]], [[ledger]].
Rapport complet : `rapport_quant_swing_d1_pepperstone.md`.
