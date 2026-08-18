---
type: experiment
id: exp-019
updated: 2026-08-17
status: done
verdict: no-edge
horizon: H1 / H4 / D1, IC a k = 1, 3, 5, 10 barres
universe: 18 symboles prop firm (4 indices, XAUUSD, 7 majeures, 6 croisees)
code: [propresearch/factor_engine.py, propresearch/prop_backtester.py, propresearch/validate.py, propresearch/xsection.py, live_prop_execution.py, check_live_parity_prop.py]
---

# exp-019 — Porte IC avant P&L : les 4 sources d'alpha institutionnelles

**Hypothesis.** Mandat utilisateur : chaine de recherche factorielle *hypothesis-driven*
en 5 etapes, ou l'**Information Coefficient est une PORTE** — un signal dont l'IC moyen
est sous 0,025 ou dont la t-stat est sous 2,0 ne recoit aucun backtest. Quatre mecanismes
pre-enregistres : time-series momentum, force relative cross-sectionnelle, flux de
rebalancement / asymetrie de vol, reversion sur extreme de liquidite.

**Setup.** 18 actifs x 3 UT x 4 horizons, **3 232 cellules d'IC**, puis bracket
pre-enregistre (1R = 2,0 x ATR14, cible +2R), peage complet incluant le **swap** lu dans
le mode declare par chaque symbole, split IS 70 / OOS 30 avec purge et embargo, temoin
d'entree aleatoire apparie, BH-FDR. Tout est dans [`propresearch/`](../../propresearch/) ;
le rapport complet est
[`rapport_quant_propfirm_institutionnel.md`](../../rapport_quant_propfirm_institutionnel.md).

**Result.**

⭐⭐⭐ **La porte IC separe les quatre mecanismes proprement, et c'est le premier resultat
de ce depot a le faire.** La meme grille rejouee 3 fois avec le lien signal→futur detruit
(rotation circulaire du rendement futur) donne le diviseur :

| Famille | PASSE reel | PASSE placebo | ratio | REFUTE reel | REFUTE placebo |
|---|--:|--:|--:|--:|--:|
| momentum TS | 20 | 11,7 | 1,71x | 20 | 35,3 |
| force relative XS | 1 | 5,7 | **0,18x** | 0 | 0,7 |
| flux / vol | 5 | 5,0 | **1,00x** | 13 | 4,0 |
| **reversion** | **39** | 18,0 | **2,17x** | **3** | 10,0 |

Seule la **reversion** est asymetrique dans les DEUX directions (passe 2,17x plus, se fait
refuter 3,3x moins) — signature d'un mecanisme, pas d'un artefact. Le momentum est
**symetrique** (20 contre 20) = bruit. Les flux sont **exactement** leur placebo.

⭐⭐⭐ **Aucun IC POOLE ne passe la porte, sur aucune famille.** Max par famille :
momentum −0,0172 (t −1,39, mauvais signe), XS +0,0354 (t 1,50), flux +0,0076 (t 0,66),
reversion +0,0183 (t 1,45). Le signal le plus **persistant** du depot est `ibs_rev` H1
poole : **IC +0,0132, t +12,95, signe correct 86,4 % de 110 trimestres** — reel, repete,
et **la moitie du seuil**.

⭐⭐⭐ **ZERO survivant FDR** en OOS, **q_min = 1,000** sur 30 cellules eligibles. Les 3
meilleures cellules OOS sont toutes **negatives in-sample** (E[R] IS −0,067 / −0,004 /
−0,045 contre +0,254 / +0,233 / +0,190 en OOS) : leur P&L vit entierement dans les 5
dernieres annees, sans support sur les 12 a 20 precedentes.

⭐⭐ **La contrainte prop firm qui mord est le DRAWDOWN TOTAL, pas la perte journaliere** :
22/30 cellules respectent les 3,5 R journaliers, **2/30 seulement** les 6,0 R globaux
(mediane **23,0 R**, soit 11,5 % du compte a 1R = 0,5 %).

⭐⭐ **Un IC significatif peut produire une sleeve significativement PERDANTE.** Le seul
survivant IC de la famille XS (`xs_ret_120d`, IC +0,0257, t 2,84) construit en L/S rend
**E[R] OOS −0,116, t −3,26, PF 0,82** sur 1 644 trades. Confirmation directe du mecanisme
d'exp-017 : **le stop dur obligatoire retourne le signe du bord**.

⭐ **Drift control favorable et pourtant insuffisant** : sur les 3 meilleures cellules la
jambe SHORT rend plus que la jambe LONG (+0,284 vs +0,205 ; +0,252 vs +0,131). Ce n'est
pas du beta deguise — et ca ne les sauve pas.

**Trois defauts d'outillage attrapes, tous corriges** (voir [[ledger]]) :
l'estimateur d'IC naif qui rend **−0,17 sur une marche aleatoire pure (20/20 tirages)** ;
**l'empilement de positions** qui transformait E[R] +0,190 en +0,500 et fabriquait un
faux survivant FDR (q 0,026 → 1,000 une fois la parite retablie) ; la **barre du jour en
formation** figee dans le cache, laissant 2,6 % d'erreur permanente sur 1R.

**Verdict.** ❌ **no-edge.** Rien n'est deploye ;
[`propresearch/live_config.json`](../../propresearch/live_config.json) porte une liste de
sleeves **vide**, et c'est le resultat. La chaine, elle, est en **parite exacte** avec la
production (`PARITE PROUVEE`, ecart 0,000e+00 sur 500 barres x 5 couples).

**Why it matters / next.** Le seul fil vivant est **`ibs_rev`** : il manque un facteur ~2
sur l'IC, et les deux leviers non tires ici sont la **largeur** (agreger les 18 actifs en
UN portefeuille de paris plutot que 18 sleeves — IR ≈ IC·√N, voir [[breadth]]) et
l'horizon **k = 1** ou son IC culmine. Ne pas re-tester la force relative XS sur cet
univers : c'est la 4e mesure convergente ([[exp-003-xsection-fx]],
[[exp-006-xsection-index-momentum]], [[exp-017-xsection-fx-intraday]], ici).

**Links.** [[information-coefficient-and-ir]], [[breadth]],
[[cross-sectional-vs-directional]], [[exp-018-swing-d1-w1-pepperstone]],
[[exp-009-ibs-reversion-4th-brick]], [[ledger]].
