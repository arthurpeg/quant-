---
type: experiment
id: exp-020
updated: 2026-08-18
status: done
verdict: partial
horizon: M5 / M15 / H1 / H4, IC a k = 1, 3, 5, 12, 24
universe: 20 symboles du mandat (10 FX, 5 indices, 3 matieres, 2 crypto)
code: [research/scripts/01_fetch_mt5_data.py, research/scripts/02_harvest_papers.py, research/scripts/03_compute_signal_ic.py, research/scripts/04_run_pipeline.py, research/scripts/signals.py, research/scripts/common.py]
---

# exp-020 — Moisson automatisee + porte IC, sans aucun backtest

**Hypothesis.** Mandat utilisateur : automatiser entierement la decouverte
(arXiv / SSRN / NBER), la formulation mathematique et le filtrage d'hypotheses
d'edges, et ne mesurer QUE la puissance predictive brute via l'Information
Coefficient. Porte : `|Mean IC| >= 0,03` ET `|t| >= 2,50` ET signe constant sur
>= 3 sous-periodes ET >= 500 occurrences independantes. Aucun SL, TP, trailing
ni sizing a ce stade.

**Setup.** Chaine complete dans [`research/`](../../research/) :
20 symboles x 4 UT tires du terminal Pepperstone (80 couples, 332 Mo),
**3 864 papiers** moissonnes, **168 definitions de signal** en 5 familles,
**28 300 cellules d'IC**. Le rapport lisible est
[`rapport_ic_gate.md`](../../research/rapport_ic_gate.md), le livrable
[`validated_hypotheses.json`](../../research/validated_hypotheses.json).
Estimateur d'IC repris d'[[exp-019-propresearch-ic-gate]] (rangs pris une fois,
blocs pour la seule dispersion), plus BH-FDR et temoin par rotation.

**Result.**

⭐⭐⭐ **LE RESULTAT CENTRAL EST UNE ANTICORRELATION : `Spearman(|t| , bord/peage)
= −0,608`** sur les 2 467 cellules qui franchissent la porte. **Plus une cellule
est significative, moins elle est exploitable**, et l'anticorrelation est forte,
pas marginale. La porte du mandat classe donc les hypotheses a peu pres a
l'ENVERS de leur viabilite economique. A l'inverse `Spearman(k , bord/peage) =
+0,358` : **l'horizon classe dans le bon sens, la significativite non.**

⭐⭐⭐ **CONTRAIREMENT A exp-019, LA GRILLE TROUVE VRAIMENT PLUS QUE LE HASARD :
2 467 cellules sur 28 300 passent (8,72 %) contre 123 pour le temoin a futur
pivote (0,43 %) — un rapport de 20,1x**, et q minimale 0,0000. C'est la premiere
fois que la porte IC de ce depot s'ouvre. La difference avec exp-019 (qui ne
passait sur AUCUN IC poole) tient a trois choix : les UT courtes M5/M15 y sont
autorisees, l'IC est mesure **par actif** et non poole, et la porte porte sur
`|IC|` — donc les refutations de mecanisme comptent comme des reussites.

⭐⭐⭐ **ET CE QUE LA PORTE RECOMPENSE LE PLUS EST LE REBOND BID-ASK.** Ses plus
gros scores — `atr_band_z` EURGBP M5 k=1, IC +0,052, **t = 26,1**, signe stable
4/4, temoin |IC| 0,001 — sont des reversions a une barre en M5. L'autocorrelation
a un pas est negative sur **toute** la grille (−0,022 en M5). C'est reel, c'est
ecrasant, et c'est la mecanique du carnet : le bord attendu y vaut **0,11 fois le
peage**. Sans le controle arithmetique, la phase 2 aurait backteste le spread.

⭐⭐ **LE RAPPORT BORD/PEAGE EST MONOTONE EN UT — 0,11 (M5) / 0,17 (M15) / 0,37
(H1) / 1,23 (H4) — ET LA PORTE NE L'EST PAS** (1 067 cellules passent en M5
contre 181 en H4). Le meme resultat que ce depot a mesure six fois par le P&L
([[exp-010-intraday-grid-search-3-families]] a [[exp-016-phase5-crypto-crosses]]),
obtenu ici **sans un seul backtest**. Le mecanisme est enfin lisible en amont.

⭐⭐ **173 cellules survivent aux deux filtres** (k >= 5 pour sortir de la memoire
du carnet, ET bord attendu > peage), soit **60 couples (actif, signal) distincts**.
Concentration : **UK100 77**, BTCUSD 22, US100 20 — et sur UK100 ce sont **16
types de signaux differents**, ce qui ressemble a une propriete de l'actif plutot
qu'a une decouverte de signal ; a verifier avant d'y croire.

⭐⭐ **UN SPREAD MEDIAN NAIF VAUT ZERO SUR LES MAJEURES, ET CE ZERO EST FAUX.** Le
flux Razor imprime 0 point sur **50 %** des barres EURUSD ; la mediane brute tombe
donc sur 0 et le rapport bord/peage part a l'infini. Le premier jet de cette
chaine avait produit des `edge_to_cost = inf`. Corrige en reprenant la methode
deja validee du depot ([`swinglab/costs.py`](../../swinglab/costs.py)) : plancher
de spread **non nul** en heures liquides + commission Razor + slippage, les trois
composantes rendues **separement** parce que sur EURUSD le slippage pese 20 des
33 points et que c'est une hypothese, pas une mesure.

⭐⭐ **UN PIEGE DE DONNEES ATTRAPE A L'ENTREE : le terminal sert BTCUSD et USOIL
en "H1" depuis 2012 a ~300 barres/an**, c'est-a-dire du JOURNALIER re-etiquete
horaire. Le test de densite mensuelle coupe ces tetes de serie (0,33 % des barres
au total, jusqu'a 14 % sur BTCUSD H4). Complete [[mt5-data-quality]].

⭐ **Le critere de stabilite du mandat n'est PAS le maillon faible.** Un signe
constant n'etant pas une amplitude constante, on pouvait craindre qu'il laisse
passer des signaux eteints : mesure faite, le dernier quart vaut en mediane
**0,87** fois le premier, seules **5,6 %** des cellules tombent sous 25 %, et
**37,5 %** sont plus fortes a la fin. C'est le peage le maillon faible, pas lui.

⭐ **Le signe pre-enregistre separe les familles** : la reversion sort dans le sens
annonce a **84 %**, le momentum intraday a **20 %** seulement (donc il se REFUTE
quatre fois sur cinq et la porte en `|IC|` compte ces refutations comme des
succes), les sessions a 50 % = pile ou face.

⭐ **`ibs` — le seul fil vivant d'[[exp-019-propresearch-ic-gate]] — reapparait**
mais reste sous la barre : BTCUSD H1 k=5 rend IC +0,032 / t 8,6 / stabilite 0,91
pour un bord/peage de **0,89**. Il manque toujours un petit facteur, et c'est
coherent avec le « facteur ~2 » d'exp-019.

**Verdict.** ⚠️ **partial.** Le livrable existe et est consommable
(2 467 hypotheses au schema demande, chacune portant ses controles FDR, temoin,
et son rapport bord/peage). Mais **aucune brique n'en sort** : les 173 cellules
economiquement plausibles sont in-sample, non deduplicquees en 60 couples reels,
concentrees sur un actif, et n'ont vu ni stop, ni cible, ni sizing — c'est-a-dire
exactement ce que le mandat interdisait a cette phase.

**Why it matters / next.** Deux acquis reutilisables. **(1)** La porte IC seule
ne suffit pas et on sait maintenant de combien : il faut la croiser avec
`|IC| x sigma(R) / peage`, sinon elle designe le rebond bid-ask. **(2)** La
chaine est outillee pour la phase 2 — mais la phase 2 doit partir des **173**,
pas des 2 467, et commencer par H4/H1 ou le rapport depasse 1. La question ouverte
la plus rentable est UK100 : 16 signaux differents y passent, ce qui est soit une
vraie propriete de l'indice, soit un artefact a nommer.

**Links.** [[information-coefficient-and-ir]], [[exp-019-propresearch-ic-gate]],
[[exp-016-phase5-crypto-crosses]], [[exp-010-intraday-grid-search-3-families]],
[[leakage]], [[prop-firm-universe]], [[ledger]].
