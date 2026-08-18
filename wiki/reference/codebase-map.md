---
type: reference
updated: 2026-07-11
---

# Codebase map — router

> Router page: links to the authoritative code; does not restate it. If a file's
> behavior changes, the truth is the file — update the one-liner, not a copy.

## Core pipeline
- `config.py` — single source of all "magic" parameters (whitelist, windows,
  barriers, sessions, seeds). [[prop-firm-universe]], [[triple-barrier]].
- `data_loader.py` — clean / resample / market-grid alignment.
- `calendar_utils.py` — forex market calendar (session masks, market grid, holidays).
- `labeling.py` — [[triple-barrier]] labels.
- `pipeline.py` — orchestration: validate → clean → features → label → (X, y);
  `walk_forward_split`, `dataset_hash`. [[walk-forward-embargo]], [[leakage]].
- `features/` — `momentum, volatility, volume, structure, temporal, seasonality,
  cross_asset, mtf`. Ordered build → stable column order → reproducible hash.

## Data loaders
- `fetch_data.py` — Yahoo (yfinance) → `data_cache/*.csv`. [[data-sources]]
- `mt5_loader.py` — MetaTrader5 → `data_cache_mt5/`. [[data-sources]]
- `fx_loader.py` — FX + metals panel for cross-section. [[exp-003-xsection-fx]]
- `equity_loader.py` — ~200-stock equity panel (survivorship-biased). [[exp-004-xsection-breadth-poc]]
- `macro_loader.py` — cross-asset/macro series (DXY synthetic, VIXY, UST). [[exp-002-v3-mt5-four-angles]]

## Backtests & experiments
- `backtest.py`, `backtest_v2.py`, `backtest_real.py`, `backtest_exec.py`,
  `backtest_mtf_base.py` — direction backtests. [[exp-001-v1-single-tf-direction]]
- `experiment_v3.py`, `experiment_flow.py` — the four-angle study. [[exp-002-v3-mt5-four-angles]]
- `orderflow.py` — quote-microstructure probe (order flow dead end). [[ledger]]
- `analyze_gold.py`, `analyze_gold_mt5.py` — gold single-asset analysis.
- `xsection_fx.py` — cross-sectional FX/metals. [[exp-003-xsection-fx]]
- `xsection_poc.py` — breadth POC. [[exp-004-xsection-breadth-poc]]

## edgelab framework (isolated package, 2026-07-28)
- `edgelab/` — a self-contained **research + validation framework** (distinct from
  the flat research scripts above). Subpackages: `research/` (arXiv q-fin scraper +
  candidate-edge fiches), `data/` (`DataProvider` ABC → MT5-csv / Yahoo, swappable),
  `edges/` (`BaseEdge` + momentum / mean-reversion / vol-breakout), `backtest/`
  (event-driven, no-lookahead, costs, walk-forward, metrics), `risk/` (mandatory
  SL/TP/time-exit + `PropFirmRules`), `portfolio/` (decorrelated selection + combine).
  Run: `python -m edgelab.run_pipeline`, `python -m edgelab.run_research`,
  `python -m pytest edgelab/tests`. All params in `edgelab/config.yaml`; see
  `edgelab/README.md`. Isolated to avoid shadowing the root `backtest.py`.
  [[prop-firm-universe]], [[cross-sectional-vs-directional]]
- `edgelab/edges/ibs.py` — brick 4: IBS reversion (`run_ibs`, `ibs_daily_R`), R-based with
  the mandatory ATR stop. `cadence='live'` (default, what the book uses) = the deployed
  driver's once-per-rollover clock; `cadence='literal'` = the exploratory loop, kept only
  for the `verify` parity proof. [[exp-009-ibs-reversion-4th-brick]]
- `edgelab/reports/monte_carlo_static.py` — canonical Monte Carlo of the frozen
  **4-brick** book (no compounding, fixed-fractional trade-R on a calendar index):
  `build_daily_R()` (the book's daily-R series) + `simulate()` (block bootstrap) feed both
  the CLI printout and the HTML reports — 1-yr R distribution + static-DD challenge
  time-to-pass + funded optimal sizing. [[system]]
- `edgelab/reports/build_reports.py` — **rebuilds both HTML reports** from one run
  (`portfolio_backtest.html` + `monte_carlo.html`, plus `_out/` and root `RAPPORT_*.html`
  copies). Run after adding or changing a brick. [[system]]
- `edgelab/reports/payout_frequency.py` — funded payout-cadence study (biweekly vs
  monthly vs quarterly; buffer policy). Reuses the same corrected R series. [[system]]

## edgelab/live — live / forward-test runner (2026-07-29)
- `edgelab/live/` — one Python process runs the frozen **4-brick** book on MT5/Pepperstone
  (brick 4 wired 2026-07-31, magic 105), **dry-run by default** (pulls bars, logs would-be
  orders, paper-tallies R). Modules:
  `signals.py` (pure decisions reusing the exact backtest math), `broker.py` (MT5 conn +
  order routing + dry-run paper book), `risk.py` (1R sizing + shared static-DD prop gate),
  `strategies.py` (per-brick drivers), `runner.py` (event loop: `python -m edgelab.live.runner`),
  `verify.py` (proves live==backtest: brick1 830/830, brick3 identical, brick2 ~98%,
  brick4 314/314 trades + a printed live-vs-backtest R gap),
  `config_live.yaml` (symbol map + `live_trading` flag + risk%). See `edgelab/live/README.md`.
  Resilience: runner self-heals dropped MT5 conn (health-check + reconnect), rotating
  `_out/runner.log`, exit 42 on blown account; single-instance mutex in `runner.py`.
  `run_forever.ps1` = supervisor (restart on crash, resolves the real python not the Store
  alias, STOP-file to halt); `install_task.ps1` = auto-start at logon; `summary.py` =
  one-command forward-test readout of `_out/trades.csv` (R total/per-brick/per-month). [[system]]
- `edgelab/live/summary.py` construit aussi le **rapport Discord quotidien**
  (`build_report_embed`) : compte, R du jour, **detail trade par trade du jour avec
  sa sleeve et son R**, progression challenge, positions ouvertes, table par brique.
  Tout y est en **R DE COMPTE** (une sleeve a 0.5R compte moitie). Le pourcentage de
  progression se mesure contre une **ancre fixe** — `propfirm.challenge_start_balance`
  en config, sinon `_out/account_start.json` ecrit une seule fois par
  `runner._challenge_anchor` — et **jamais** contre `risk.initial_balance`, que
  `size_from_account:true` recale au solde lu a chaque demarrage. [[system]]

## crosslab/ — Momentum cross-sectionnel intraday G8 (2026-08-16)
- `crosslab/config.py` — **le mandat cross-sectionnel en donnees**. Les 28 paires,
  l'incidence signee `W` (28x8, somme des forces nulle par construction), la table
  `CROSS` des 56 couples ordonnes -> paire directe + sens, le modele de cout ADDITIF
  (commission hors du `max()`, contrairement aux phases 1-5), les axes de grille et
  le decoupage IS/OOS. [[exp-017-xsection-fx-intraday]]
- `crosslab/fetch.py` — tirage M1 par ANNEE des 28 paires vers `data_cache_fx28/`
  (float32 + zstd, 1,4 Go pour 120,3 M barres).
- `crosslab/costs.py` — mesure le peage SUR LE FLUX : mediane des spreads **non nuls**
  en heures liquides + commission Razor convertie en points via `trade_tick_value`.
  Fige dans `_cost_floors.json` ; la grille et le direct lisent le meme instantane.
- `crosslab/panel.py` — le panel synchronise : INTERSECTION des seaux (jamais l'union
  — c'est le bug d'alignement qui avait donne un faux Sharpe 0,70 a [[exp-006-xsection-index-momentum]]),
  et la matrice `ent` qui relie chaque seau a l'index M1 d'entree DANS le tableau de
  chaque paire. `_column()` est le point de parite recherche/direct ;
  `panel_from_bars()` est le chemin du live.
- `crosslab/strength.py` — `S = W' x / 7`, les 4 modes de score, le classement, la
  dispersion et son z causal, l'invalidation du classement. `eval_bars()` ancre les
  instants d'evaluation sur `utc_tod % 30` et **non sur l'index du panel** : sinon la
  PHASE des evaluations depend de la date de debut et le direct evalue ailleurs que
  la grille. Fenetres de vol et de dispersion FINIES (1 000 barres) et non EWMA, pour
  la meme raison — un etat EWMA n'est pas reproductible depuis une fenetre bornee.
- `crosslab/engine.py` — 144 brackets en UNE passe de fenetres d'excursion (2 ATR x
  3 stops x 4 sorties x 3 durees x 2 regles). Rend le R NET **et le R BRUT** : le
  peage etant additif, le rejeu a cout nul est gratuit. Convention pessimiste (SL
  avant TP dans une meme barre M1) heritee de `gridlab.engine`.
- `crosslab/run.py` — la grille. Boucle EXTERIEURE sur les paires (les 28 tableaux M1
  pesent 6 Go), n'accumule que des statistiques exhaustives additives.
- `crosslab/validate.py` — gel sur l'IS seul -> BH-FDR sur le t JOURNALIER OOS, test
  poole par famille, **temoin de direction apparie** (chaque entree resolue dans les
  DEUX sens : la moyenne est ce que rend la meme geometrie de bracket sans aucune
  information directionnelle — controle exact, gratuit, qui remplace les tirages de
  placebo des phases precedentes), et une 2e cohorte gelee sur le BRUT.
- `crosslab/dispersion.py` — bord brut contre peage, **sans bracket** : rendement
  signe en bp de la croisee designee, IS/OOS, avec et sans saut d'un seau (controle
  de microstructure), contre le peage mesure de cette paire.
- `crosslab/test_engine.py` — 43 200 valeurs de R comparees a une boucle naive
  barre par barre. Ecart max 3,8e-07. `python -m crosslab.test_engine`.
- `crosslab/report.py` — assemble `rapport_quant_cross_sectional_pepperstone.md` ;
  chaque nombre est lu dans un parquet, aucun n'est saisi a la main.
- `live_cross_execution.py` — l'executeur `mt5.order_send`, **desarme par defaut ET**
  refusant de s'armer sans `"validated": true` dans sa config. Aplat a 23h50 SERVEUR
  (pas 21h50 UTC : le rollover tombe a 21h00 UTC l'ete, une consigne en UTC le
  franchirait six mois par an). `m1_bars_for()` dimensionne le tirage depuis les
  constantes de chauffe elles-memes.
- `check_live_parity_cross.py` — preuve numerique que le direct voit ce que la grille
  a vu. **A fait tomber deux defauts avant la production**, pas apres.

## cryptolab/ — Phase 5 : crypto & croisees volatiles (2026-08-14)
- `cryptolab/config.py` — **le mandat Phase 5 en donnees**. Univers, declencheurs,
  grille des trois barrieres, echelles de stop, seuils, decoupage IS/OOS. Rien en aval
  n'invente un parametre. [[exp-016-phase5-crypto-crosses]]
- `cryptolab/fetch.py` — tirage M1 par ANNEE depuis le terminal (contourne le plafond
  `MaxBarsInChart` qui tronque silencieusement un `copy_rates_range` trop large).
- `cryptolab/setups.py` — les 3 declencheurs du mandat (breakout, anomalie de volume,
  z-score) x 2 sens, plus `block_atr()` = **l'ATR LOCAL de la fenetre** (bloc de 4 h),
  le levier qui divise le peage par ~7. L'horizon vaut `min(H bougies, mise a plat)`.
- `cryptolab/labeling.py` — triple barriere relue DANS le moteur, purge/embargo,
  grille de decision. Reutilise `kzlab.labeling` pour ce qui n'a pas de parametre.
- `cryptolab/run.py` — grid search, un processus par symbole. `--zero-cost
  --reuse-probs` rejoue la grille gratuite en relisant les probabilites (exact : Y est
  invariant au cout, verifie au bit pres).
- `cryptolab/validate.py` — gel sur l'IS seul -> BH-FDR sur l'OOS + plateau + test
  poole par classe d'actifs. `top_features()` sert la feature importance du rapport.
- `cryptolab/report.py` — assemble `rapport_quant_phase5_pepperstone.md` ; chaque
  nombre est lu dans un parquet, aucun n'est saisi a la main.
- `cryptolab/export_model.py` — gele une cellule dans un bundle joblib (schema 5).
- `cryptolab/test_p5.py` — **24 assertions** de causalite, contrat intraday, -1R au
  stop, purge/embargo. `python -m cryptolab.test_p5`.
- `live_ml_execution_phase5.py` — l'executeur `mt5.order_send`, **desarme par
  defaut**. Sizing sur l'ATR local, stop+cible chez le courtier, barriere verticale
  recalculee depuis `position.time` (survit a un redemarrage), `FlatAtSessionClose` a
  chaque sondage.
- `cryptolab/multihorizon.py` — resout TOUS les horizons en UNE passe du moteur. Les
  courbes d'excursion etant monotones, l'indice du premier franchissement d'une
  barriere ne depend pas de l'horizon ; seule la question "tombe-t-il avant la fin de
  MON horizon ?" en depend. **x3,3**, equivalence algebrique verifiee sur de vraies
  barres (`python -m cryptolab.multihorizon`). [[exp-016-phase5-crypto-crosses]]
- `cryptolab/degeneracy.py` — le controle qui empeche de se mentir sur un stop large :
  part des trades qui touchent encore une barriere HORIZONTALE, par (stop, horizon).
  Sans lui, un rapport bord/peage qui monte peut n'etre qu'une strategie qui ne fait
  plus rien.
- `cryptolab/driftcontrol.py` — **le controle qui separe un bord d'une derive**. Un
  declencheur `follow` est long a la hausse et short a la baisse : sur un actif qui
  monte, la moyenne des deux est positive sans aucune information. On separe par SENS
  REEL et on correle l'asymetrie `long−short` au buy-and-hold de l'actif. C'est ce
  module qui a tue le candidat GER40 de la Phase 5b.
- `cryptolab/report_m15.py` — assemble `rapport_quant_phase5b_m15.md` (profil `p5b`).
- `check_live_parity_phase5.py` — deux preuves : parite de FEATURES colonne par
  colonne, et **parite de DECISION** (`--bundle`) qui rejoue de vraies minutes
  d'entree **a travers `Phase5Executor.score()`** et compare probabilite, sens et
  distance de stop. C'est ce script qui a trouve le bug `session_left`.

## External strategies (MQL5)
- `mql5/IntradayVolatilityBreakout.mq5` — MT5 Expert Advisor, intraday Nasdaq
  (NAS100) US-open ATR breakout + vol-regime filter. Runs in the MT5 Strategy Tester,
  not the Python pipeline. [[exp-005-mt5-intraday-vol-breakout]]

## swinglab/ — Swing D1 / W1 sur 19 actifs Pepperstone (2026-08-17)
- `swinglab/config.py` — **le mandat swing en donnees** : les 19 actifs, le modele de
  cout ADDITIF (spread mesure + commission + 1,0 pip de slippage PAR COTE + **swap**),
  les 120 geometries de bracket, les axes des 4 familles, le decoupage IS/OOS.
  [[exp-018-swing-d1-w1-pepperstone]]
- `swinglab/fetch.py` — tirage D1 (signal) + H1 (resolution) des 19 actifs vers
  `data_cache_swing/`. D1 porte le signal, H1 tranche l'ordre stop/cible dans la
  journee : les deux resolutions ne sont pas interchangeables.
- `swinglab/costs.py` — mesure le peage SUR LE FLUX et fige `_cost_floors.json`. Le
  point neuf par rapport a `gridlab`/`crosslab` est le **swap**, lu dans les DEUX
  modes que le terminal declare : `swap_mode` 1 = points (FX, or), `swap_mode` 5 =
  interet annuel en % du notionnel (CFD d'indices), plus le jour de triple rollover.
  `nightly_price()` est la seule conversion, partagee par la recherche et le direct.
  **Limite reportee : MT5 ne sert que le taux COURANT**, d'ou le rejeu a swap nul/double.
- `swinglab/data.py` — `asset_from_frames()` est **LE SEUL constructeur d'`Asset` du
  depot** : `load()` lit le cache parquet, `live_swing_execution.py` tire ses barres de
  MT5, et tous deux passent par la. La parite backtest/live est donc une propriete du
  chemin de code. `Asset.known()` rend TOUTE serie derivee decalee d'une barre — la
  parade au piege du ledger (« LOOK-AHEAD TRAP: daily conditions on intraday entries »).
- `swinglab/engine.py` — le moteur : R de **toute** barre × 2 sens × 120 geometries en
  une passe, resolu sur le chemin H1. Trois conventions pessimistes : stop avant cible
  dans la meme barre, **gap paye a l'ouverture** (un swing traverse des week-ends, son
  stop ne tient donc pas a −1R exactement), et fenetre de maintien qui doit tenir dans
  l'historique. Rend `brut`, `cout_R` et `swap_R` SEPAREMENT, ce qui rend le rejeu a
  cout nul / swap double gratuit.
- `swinglab/families.py` — familles 1 (Donchian, croisement d'EMA + pente, compression
  NR7/BB) et 3 (z-score, RSI court, rejet de bande). Un signal ne produit qu'une DATE
  et un SENS ; tout le reste appartient au moteur, donc aucune famille ne peut gagner
  par une sortie plus indulgente. `Frame` porte la traduction « barre de signal » →
  « barre d'entree » pour D1 et pour W1.
- `swinglab/xsection.py` — famille 2, rotation hebdomadaire. Panel par **INTERSECTION**
  des semaines (jamais l'union — le bug d'alignement d'[[exp-006-xsection-index-momentum]]),
  jambes longues et courtes rapportees separement.
- `swinglab/ml.py` — famille 4, triple barriere + LightGBM. Validation croisee
  **purgee** a l'interieur de l'IS (sinon le seuil `P > 0,60` se choisit sur des
  probabilites d'entrainement), et **double AUC** rapportee : « une barriere touchee »
  contre « laquelle ». `cost_atr` et `swap_atr` sont des features EXPLICITES, pour que
  la chasse aux barres bon marche se LISE dans l'importance au lieu de se deduire.
- `swinglab/run.py` — la grille f1/f3. `nonoverlap()` = la regle d'occupation (une
  position a la fois, balayage glouton causal) ; purge exacte a la frontiere IS/OOS ;
  cache disque des brackets partage avec la validation.
- `swinglab/validate.py` — gel sur l'IS SEUL (aucune colonne `_oos` lue), BH-FDR,
  batterie : temoins de derive, plateau, tenue au swap ×0/×2, degenerescence,
  concentration annuelle, correlation aux 4 briques du book.
- `swinglab/driftcontrol.py` — les trois temoins anti-beta : « chaque barre », direction
  APPARIEE (chaque entree resolue dans les deux sens, tout le reste constant) et
  decomposition long/court.
- `swinglab/report.py` — genere `rapport_quant_swing_d1_pepperstone.md` DEPUIS les
  artefacts de `_out/` : aucun chiffre du rapport n'est saisi a la main.
- `swinglab/test_engine.py` — **7 preuves du moteur** : cible, stop, gap, barriere
  verticale, symetrie long/court, alignement D1↔H1 sur les 19 actifs REELS,
  degenerescence.
- `live_swing_execution.py` — l'executeur MT5 : une passe apres le rollover serveur,
  dimensionnement 1R, trailing Chandelier/Donchian, barriere verticale, une position
  par strategie, **dry-run par defaut** (exige `--live` ET `live_trading:true`).
  Le journal `_out/live_positions.json` est sa memoire.
- `check_live_parity_swing.py` — rejoue 400 jours en TRONQUANT les frames comme MT5 les
  aurait servies : dates d'entree ET unite de risque doivent coincider.

## `research/` — phase 1 : moisson automatisee + porte IC (exp-020)

Chaine autonome litterature → IC. **Aucun backtest** : ni stop, ni cible, ni sizing.
Le README du dossier porte l'arborescence et les commandes.

- `research/scripts/common.py` — univers (20 symboles), horloges, chargement. L'estampille
  serveur est **convertie en UTC**, pas supposee UTC : la moitie des familles sont des
  signaux de SESSION et une erreur d'une heure deux fois par an fabrique une saisonnalite.
- `research/scripts/signals.py` — **LA** formule exacte de chaque `S_t`, une seule fois pour
  la recherche et l'execution future. Sessions ancrees sur l'heure LOCALE de leur place
  (NY 09h30 America/New_York), jamais sur une heure UTC fixe.
- `research/scripts/01_fetch_mt5_data.py` — tirage MT5 par tranches d'un an, derniere barre
  jetee (elle est en formation), **coupe du remplissage broker** par densite mensuelle
  (BTCUSD/USOIL « H1» a 300 barres/an = du journalier re-etiquete), et le **peage** par la
  methode de `swinglab/costs.py` — plancher de spread NON NUL, sinon la mediane vaut 0 sur
  les majeures et le rapport bord/peage part a l'infini. `--costs-only`, `--clean-only`.
- `research/scripts/02_harvest_papers.py` — arXiv (Atom, q-fin.*), NBER, OpenAlex, corpus
  local. **SSRN direct rend 401 sans cle** : c'est journalise, pas contourne. Le classement
  papier → famille est a mots-cles ; `formula_provenance` vaut `"template"` partout, exprès.
- `research/scripts/03_compute_signal_ic.py` — le moteur d'IC. Rangs pris **une fois**, blocs
  pour la seule dispersion ; `--selftest` en 4 points, dont la reproduction du piege de
  l'estimateur naif (**IC = −0,176 sur du bruit**) et un **test de causalite** qui perturbe la
  seconde moitie des barres et exige que la premiere moitie de chaque signal ne bouge pas.
- `research/scripts/04_run_pipeline.py` — orchestration, porte du mandat, **BH-FDR**, temoin
  par rotation, et le bloc `feasibility` (`|IC| x sigma(R)` contre le peage) qui est ce qui
  separe un bord d'un rebond bid-ask. Ecrit `validated_hypotheses.json` et `rapport_ic_gate.md`.
- `research/scripts/05_vectorized_backtester.py` — **phase 2** : le moteur R-multiples.
  1R = 1,5 x ATR14, entree a l'open de t+1, sortie a k barres ou au stop, cibles 2R/3R.
  Quatre regles qui decident du resultat : **une position a la fois** (sans quoi exp-019
  avait vu E[R] passer de +0,190 a +0,500), **le gap est honore** (une barre qui OUVRE
  sous le stop sort a l'ouverture, donc a pire que −1R), **le stop gagne** quand stop et
  cible tombent dans la meme barre, et le **peage est deduit en R** et non applique aux
  prix (sinon il compte double). Le seuil d'entree est un **rang causal sur les
  OCCURRENCES** du signal, pas sur les barres — compter les barres annulait en silence les
  familles de session. `--selftest` en 8 points ; deux temoins (sens apparie, entree
  aleatoire) plus BH-FDR et les deux moities chronologiques.
- `research/scripts/06_stop_geometry.py` — le balayage de la **geometrie de sortie**
  (stop dur 2/3/4 x ATR14, Chandelier 2/3 x ATR14 sur l'extreme des 5 dernieres barres).
  Reutilise les briques de `05_` (rang causal, regle d'occupation, metriques) pour que
  les deux etapes partagent exactement les memes regles. Deux points qui decident du
  resultat : le niveau de trailing en vigueur PENDANT une barre est calcule sur les
  barres **precedentes** (sinon le stop se pose avec le plus haut de la barre qui va le
  toucher), et `add_price_units()` reexprime tout en **bps de prix** — sans quoi la
  comparaison entre largeurs de stop compare des unites differentes, puisque
  `1R = m x ATR14`. `--selftest` en 7 points, `--report-only` pour regenerer le rapport
  sans remesurer.
- `research/scripts/07_exit_optimization.py` — l'optimisation de sortie des deux
  configurations robustes, **et son controle**. Le trailing peut y etre ARME EN RETARD
  (apres un gain latent de +1R) ; l'armement est causal comme le trailing, et dans une
  meme barre **le stop est teste AVANT l'armement** (une barre qui touche +1R puis revient
  chercher le stop est une perte pleine). La partie B rejoue les memes variantes sur les
  173 cellules : c'est elle qui decide, parce que la partie A optimise deux cellules deja
  selectionnees comme le sommet d'une grille de 2 595. Le diagnostic qui tranche est
  `Spearman(E[R] de depart, gain)` — a -0,92, une "amelioration" est de la troncature de
  pertes, pas de l'alpha. `--selftest` en 5 points, dont la parite exacte avec `06_`.
- `research/scripts/08_ger40_book_candidate.py` — l'instruction d'admission d'une sleeve au
  book, appliquee a GER40. Quatre mesures dans cet ordre : cout du broker DU BOOK (et non
  celui de la recherche), decorrelation aux sleeves DEJA en place, apport en RoMaD/Sharpe/
  maxDD, robustesse. Deux pieges qu'il rend visibles : comparer aux 4 briques au lieu du
  book REEL fait passer un candidat « mitige » pour un candidat « ameliore tout » ; et une
  sleeve dont le maxDD propre depasse celui du book entier degrade le RoMaD meme quand elle
  ajoute du R/an. Le swap inconnu est traite par SENSIBILITE (a partir de quel taux la
  sleeve meurt) plutot qu'invente.
- `research/scripts/09_ger40_ftmo_montecarlo.py` — GER40 NET des couts FTMO, puis le
  Monte-Carlo du depot (`monte_carlo_static.simulate`, meme graine et memes blocs) contre
  le book AGRESSIF reconstruit par `books_report.load_sleeves` + `_ftmo_costs`. Rien n'est
  reimplemente : seule la sleeve est ajoutee. Deux points de methode : le **spread FTMO
  inconnu est balaye** (on mesure a partir de quelle largeur la sleeve cesse de convaincre)
  plutot qu'invente, et la comparaison est faite **NET DES DEUX COTES** -- en brut le RoMaD
  de l'ajout paraissait degrade, en net il s'ameliore, parce que le swap crypto penalise le
  book et pas le candidat.
- `research/scripts/10_candidate_shortlist.py` — la shortlist COMPLETE des candidats issus de
  la chaine `research/`, au seuil pre-enregistre et avec la batterie de temoins, **classee par
  RoMaD standalone** parce que c'est le test d'admission du depot (`system.md`) et non E[R].
  Il existe pour corriger une erreur de methode : les deux candidats d'exp-023 avaient ete
  choisis en lisant le haut d'un tableau trie par E[R] -- ils sont 2e et 3e sur 31. Le script
  rend aussi la correlation mensuelle au book, qui revele l'arbitrage : les meilleurs RoMaD
  sont les plus correles.
- `research/scripts/11_basket_montecarlo.py` — le panier de petits decorreles, NET FTMO, au
  Monte-Carlo du depot. Le panier est defini par une REGLE (corr <= +0,10, RoMaD >= 0,38, une
  config par signal x actif) et non a l'oeil. Deux mesures que le script existe pour produire :
  la **mutualisation** (somme des maxDD des composantes contre maxDD du panier) et le **temoin
  de selection** (des paniers de meme taille tires AU HASARD dans la shortlist) -- sans ce
  dernier on croirait que la regle de decorrelation choisit bien, alors qu'elle n'est qu'au
  73e centile du tirage aleatoire. Le swap FTMO y coupe les composantes en deux : la selection
  faite sur des couts Pepperstone ne survit pas au broker du book.
- `research/scripts/12_net_ftmo_shortlist.py` — la selection refaite **nativement nette** des
  couts FTMO : cout d'abord, classement ensuite, et deduplication sur le NET et non sur le
  brut. Il existe parce que le panier de `11_` avait ete choisi sur des couts Pepperstone et
  que le swap FTMO coupait ses composantes en deux. Deux enseignements qu'il produit : la
  **geometrie optimale nette n'est pas la brute** (GER40 passe de stop 2,0 a 3,0), et la
  granularite **protege du swap mais expose au spread** -- les survivantes nettes tiennent
  1,18 nuit en mediane contre 0,32 pour les recalees, l'inverse de l'intuition.
- `research/scripts/13_ftmo_read_specs.py` — la LECTURE SEULE des specs FTMO (spread mesure
  par la meme methode que chez Pepperstone, swap converti en % annuel du prix). Trois
  garde-fous : refus de lire si le terminal n'est pas FTMO, relevé des ordres/positions AVANT
  et APRES (le journal enregistre qu'un `mt5.initialize()` peut reveiller des EA endormis), et
  aucun appel qui ecrive. Sortie figee dans `research/data/ftmo_specs.json`, que `12_` lit.
  ⚠️ Le piege que ce fichier a paye : convertir des points de swap en POURCENT annuel demande
  un `* 100` final -- l'oublier rend un taux 100 fois trop petit et fait lire "+0,07 %/an" la
  ou GER40 en paie 6,62.
- `research/scripts/14_swap_test_vs_book.py` — la comparaison des candidates a CHAQUE sleeve du
  book, et le test de REMPLACEMENT que `system.md` avait tranche en brut le 2026-07-31. Tout est
  net des deux cotes et restreint a la fenetre COMMUNE : comparer des sleeves sur leurs spans
  propres fabriquerait un ecart qui n'est que du calendrier. Rend aussi un rejeu a **swap
  double**, parce que MT5 ne sert que le taux courant et que US30 a inverse ses cotes en huit
  jours.

