# research/ — Phase 1 : de la litterature a la porte IC

Chaine autonome qui va de la **moisson d'hypotheses** a la **mesure du pouvoir
predictif brut**, et qui s'arrete la. Aucun stop, aucune cible, aucun trailing,
aucun sizing, aucun cout n'entre dans cette phase : c'est la lettre du mandat, et
c'est aussi la seule facon de ne pas confondre un bord avec la geometrie d'un
bracket.

## Arborescence

```
research/
├── data/                        # parquet MT5 nettoyes + literature.json + hypotheses.json + ic_results*.parquet
├── scripts/
│   ├── common.py                # univers, horloges, chargement, journal   (socle)
│   ├── signals.py               # LA formule exacte de chaque S_t          (socle)
│   ├── 01_fetch_mt5_data.py     # synchronisation MT5 / Pepperstone
│   ├── 02_harvest_papers.py     # arXiv + NBER + OpenAlex + corpus local -> catalogue
│   ├── 03_compute_signal_ic.py  # moteur d'IC vectorise + auto-tests
│   └── 04_run_pipeline.py       # orchestration + porte + FDR + livrables
├── logs/research_execution.log
├── validated_hypotheses.json    # LIVRABLE consomme par la phase 2
└── rapport_ic_gate.md           # LIVRABLE lisible
```

`common.py` et `signals.py` ne sont pas dans le mandat : ils existent parce que
les quatre scripts numerotes partageaient sinon trois copies de la meme horloge
et de la meme formule d'ATR — et ce depot a deja perdu la parite backtest/live
exactement comme ca.

## Lancer

```bash
python research/scripts/04_run_pipeline.py                 # tout, en sautant ce qui est deja calcule
python research/scripts/04_run_pipeline.py --refresh all   # tout recalculer
python research/scripts/03_compute_signal_ic.py --selftest  # les 4 auto-tests, seuls
```

## Les quatre auto-tests (`03 --selftest`)

1. **1a** — marche aleatoire au reglage reel : l'estimateur retenu doit rendre IC ~ 0.
2. **1b** — le meme bruit avec un bloc court et une memoire longue : l'estimateur
   NAIF doit rendre IC ~ **-0,176**. C'est le piege du recentrage local, montre a
   l'echelle ou il mord, et c'est la raison pour laquelle les blocs sont grands.
3. **2** — signal plante a rapport connu : l'IC mesure doit retrouver ~0,43.
4. **3** — **causalite** : on perturbe la seconde moitie des barres et on verifie
   que la premiere moitie de CHAQUE signal du catalogue ne bouge pas d'un bit.
   C'est le test qui rend le "pas de look-ahead" verifiable au lieu de promis.

## Ce que la chaine ne fait pas

- Elle **ne lit pas les formules dans les PDF**. La litterature apporte la
  provenance et le mecanisme ; la formule vient de `signals.py`, ecrite a la
  main. Le champ `formula_provenance` vaut `"template"` partout, exprès.
- Elle **ne moissonne pas SSRN en direct** : `api.ssrn.com` rend 401 sans cle.
  SSRN est atteint via OpenAlex et via le corpus local du depot.
- Elle **n'a pas de DXY ni de US10Y** : ce terminal n'en sert pas. L'indice
  dollar est reconstruit depuis les sept majeures presentes ; USDJPY et US500
  servent de relais taux/risque. Les deux substitutions sont ecrites dans le
  code, pas sous-entendues.

## Phase 2 (`05_vectorized_backtester.py`)

Les 173 cellules retenues (k >= 5 ET bord/peage >= 1,0) x 3 seuils x 3 sorties =
**1 557 configurations**. 1R = 1,5 x ATR14, sortie a k barres ou au stop,
variantes a +2R / +3R, peage complet, **une position a la fois**.

**Zero survivante** a `E[R] >= 0,18 & N >= 100 & PF >= 1,25`. La contrainte qui
mord est l'esperance seule (`N` passe 1557/1557, `PF` passe 12, `E[R]` passe 0).

Le temoin de sens apparie donne la raison : bord **directionnel** median
**+0,0024 R**, positif dans **52 %** des configurations — un pile ou face. Un IC
reel mesure *sans stop* ne survit pas au stop obligatoire.

### `--selftest` en 8 points

Le stop touche rend exactement −1R ; **un gap sous le stop rend pire que −1R** ;
la cible rend +2R ; **le stop gagne** si stop et cible tombent dans la meme
barre ; long et court sont exactement symetriques sur une serie miroir ; la
regle d'occupation refuse les chevauchements ; le seuil d'entree est causal ;
et **un signal de session recoit quand meme un rang** — ce dernier test existe
parce que sans lui la fenetre glissante comptait des BARRES au lieu des
OCCURRENCES et annulait en silence 39 % de la grille.

## Etape 6 : la geometrie de sortie (`06_stop_geometry.py`)

Memes 173 cellules, memes entrees, meme peage. **Seule la sortie change** : stop
dur a 2 / 3 / 4 x ATR14, Chandelier a 2 / 3 x ATR14 sur l'extreme des 5
dernieres barres. **2 595 configurations, zero survivante** — mais la question
d'exp-021 est tranchee.

**Le piege d'unite, et sa sortie.** `1R = m x ATR14` : elargir le stop agrandit
l'unite de compte, donc tout ce qui est libelle en R retrecit mecaniquement.
`add_price_units()` reexprime le bord en **bps de prix** — la taille de 1R en
bps se deduit du peage, connu a la fois en R et en bps. Relu ainsi, le bord
directionnel **double** entre 1,5x et 4,0x, et le **Chandelier a 2x atteint
bord/peage = 1,03**, la premiere fois que le bord egale le peage ici.

Et l'esperance nette reste negative partout : le Chandelier sort sur son
trailing dans **91 %** des trades — il trouve la direction et la rend en
whipsaw.

## Etape 7 : optimiser la sortie (`07_exit_optimization.py`)

Chandelier **retarde** (+1R) et fenetre d'extreme **elargie** (10/15/20 barres),
sur les deux configurations robustes d'exp-022. **Les deux sont refutees.**

**Le controle de generalisation est ce qui decide.** Les deux configurations
sont le sommet d'une grille de 2 595 : optimiser leur sortie sur elles-memes est
de l'in-sample sur de l'in-sample. Les memes variantes sont donc rejouees sur
les 173 cellules — et les deux parties se **contredisent**. Sur les 173 le
Chandelier elargi est la meilleure variante ; sur les deux cellules rentables il
est la pire.

Le diagnostic qui tranche : `Spearman(E[R] de depart, gain) = -0,921`. Une
"amelioration" d'autant plus grande que la cellule etait mauvaise est de la
**troncature de pertes**, pas de l'alpha — 5 cellules gagnantes sur 27 y
survivent.

**Et elargir la fenetre RESSERRE le trailing** : le maximum sur 20 barres est
toujours >= le maximum sur 5, donc le stop est plus haut, donc plus proche du
prix. Le levier qui relache un trailing est la fenetre COURTE.

