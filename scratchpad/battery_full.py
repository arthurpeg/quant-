"""BATTERIE COMPLETE sur TOUS les signaux ayant au moins une cellule t>2,
sur LES TROIS corpus, avec un JEU DE BRACKETS PRE-DECLARE et un PLACEBO APPARIE
qui subit exactement la meme procedure.

Demande utilisateur (2026-08-10): *"backtest toutes les strategies au-dessus de
t>2 peu importe s'il y en a moins que par chance ... avec tous les tests qu'on
fait passer on devrait etre en mesure de discerner la chance d'un edge"*.

CE QUE CE SCRIPT CORRIGE PAR RAPPORT A `battery_all.py`
-------------------------------------------------------
1. **La cohorte etait incomplete.** `battery_all.cohort()` ne balayait que
   `corpus_*.parquet` (Pine) et `mql_*.parquet`. Les 52 050 cellules du sweep
   TSaM + regles de seance vivent dans `part_<SYM>_<TF>.parquet` et n'etaient
   PAS ramassees — 92 signaux a t>2 manquaient a l'appel. Ici la cohorte est
   258 Pine + 92 regles (TSaM/seance) + 2 MQL = **352 signaux**, soit tout ce
   qui a jamais touche t>2 dans la campagne.

2. **Un seul bracket = faux negatifs.** `battery_all` re-testait tout le monde a
   SL 1.5xATR sans cible. Un signal dont le t>2 venait d'une cellule avec cible
   mourait mecaniquement, sans que ce soit une information sur son edge. On passe
   donc un **jeu de 9 brackets PRE-DECLARE** (SL 1.0/1.5/2.0 x TP none/1R/2R).
   Prendre le meilleur des 9 est une selection — mais le placebo prend AUSSI le
   meilleur de ses 9, donc le rapport reste calibre. C'est tout l'interet du
   placebo apparie: il ne teste pas "un signal", il teste **la procedure entiere**.
   Le bracket (1.5, none) est marque `primary` pour garder la lecture sans
   selection du tout.

3. **Nulls a deux etages.** Les nulls A et B (300 tirages chacun) coutent ~600
   walks par cellule; on ne les calcule que pour les cellules qui ont deja passe
   le crible bon marche (t>2, deux moities positives, coût-robuste). Le crible
   est **identique pour les reels et les placebos**, donc il ne biaise pas le
   rapport — il ne fait qu'eviter de payer les nulls sur des cellules deja mortes.

LA BATTERIE, par (signal, actif, bracket) — identique reels/placebos:
  1. n >= 40 trades
  2. t net > 2
  3. les DEUX demi-echantillons positifs
  4. stress de cout: t > 1 a +10 points/cote
  5. Null A (derive/timing des barres) — 300 tirages, p < 0.05
  6. Null B (direction, permutation des signes) — 300 tirages, p < 0.05
     (n/a si la regle est a sens unique)
  7. replication: nombre d'actifs ou le signal passe 1-6

Execution: fill a l'ouverture suivante, une position a la fois, barre couvrant les
deux barrieres resolue PESSIMISTEMENT au stop, sortie forcee a la cloture de la
seance (`session=True`), plancher 1R >= 25 spreads, cout = spread planche + 2 pts
+ commission. Univers impose: NAS100, US500, US30, GER40, FRA40, XAUUSD.

LE CHIFFRE QUI TRANCHE n'est pas le nombre de survivants mais
**survivants reels / survivants placebo**:
    >> 1  -> il y a un edge dans la cohorte
    ~= 1  -> les survivants sont ce que la chance produit, quel que soit le
             nombre de tests passes

Sortie: une ligne par cellule mesuree, un fichier par actif
(`scratchpad/_inx/battery_full_<SYM>.csv`), checkpointe au fil de l'eau.

Usage:
    python -u scratchpad/battery_full.py <SYM> [n_placebo]   # un actif (parallelisable)
    python -u scratchpad/battery_full.py report              # agrege les 6 fichiers
"""
import sys, os, json, glob, time, zlib, warnings
sys.path.insert(0, 'scratchpad'); sys.path.insert(0, '.')
warnings.filterwarnings('ignore')
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import numpy as np
import pandas as pd

import kauf_lib as K
import inx_data as D
from corpus_run import TF, FLOOR, session_bars

UNI = ['NAS100', 'US500', 'US30', 'GER40', 'FRA40', 'XAUUSD']
OUT = os.path.join('scratchpad', '_inx')
NDRAW = 300
MIN_TRADES = 40
# jeu de brackets PRE-DECLARE (aucun ne vient d'un resultat): stop ATR x cible en R
BRACKETS = [(sl, tp) for sl in (1.0, 1.5, 2.0) for tp in (None, 1.0, 2.0)]
PRIMARY = (1.5, None)


# --------------------------------------------------------------------------- cohorte
def cohort():
    """Tout signal ayant AU MOINS UNE cellule t>2, dans N'IMPORTE lequel des trois
    corpus. Retourne {nom: 'pine'|'mql'|'rule'}."""
    out = {}
    for pat, corp, col in (('corpus_*.parquet', 'pine', 'sig'),
                           ('mql_*.parquet', 'mql', 'sig'),
                           ('fq_*.parquet', 'freqtrade', 'sig'),
                           ('part_*.parquet', 'rule', 'rule')):
        fs = [f for f in glob.glob(f'{OUT}/{pat}') if '_all' not in os.path.basename(f)]
        if not fs:
            continue
        d = pd.concat([pd.read_parquet(f) for f in fs], ignore_index=True)
        for s in d.loc[d['t'] > 2, col].unique():
            out.setdefault(str(s), corp)
    return out


# --------------------------------------------------------------------- signaux/actif
def build_signals(b, sym, want, ps, ms):
    """{nom: array int8} pour les membres de la cohorte mesurables sur cet actif.

    Les trois corpus ont trois chemins d'evaluation distincts; on les construit une
    seule fois par actif (le frame Pine et les 188 regles coutent cher a rebatir).

    ⚠️ MESURE 2026-08-10: sous 6 processus concurrents, ~35-43 specs Pine par actif
    ont echoue ici de facon TRANSITOIRE (pression memoire), et le `except Exception`
    ci-dessous l'avalait en le presentant comme une incompatibilite du signal. Les 32
    "erreurs" d'US500 se reconstruisent toutes sans erreur une fois la machine libre.
    Le message est donc conserve dans `err` et doit etre IMPRIME par l'appelant: un
    signal absent d'une passe n'est pas un signal intestable. Ne jamais lire un
    compte "N en erreur" comme une propriete du corpus."""
    win = np.asarray(b.in_window, bool)
    sigs, err = {}, {}

    # --- regles TSaM + regles ancrees seance -------------------------------------
    if any(v == 'rule' for v in want.values()):
        import tsam_rules as T
        import inx_rules as IR
        rules = {f'T:{k}': v for k, v in T.all_rules(b).items()}
        rules.update({f'S:{k}': v for k, v in IR.all_rules(b).items()})
        for name, corp in want.items():
            if corp == 'rule' and name in rules:
                sigs[name] = np.where(win, rules[name], 0).astype(np.int8)

    # --- Pine ---------------------------------------------------------------------
    if any(v == 'pine' for v in want.values()):
        from tv_transpile import Spec
        from tv_pine import F
        df = b.d.copy()
        df.index = df.index.tz_convert(D.SESSION[sym][0])   # horloge de la PLACE
        f = F(df, K.SPECS[sym]['point'])
        for name, corp in want.items():
            if corp != 'pine' or name not in ps:
                continue
            try:
                L, S, *_ = Spec(ps[name]['code'], {}).run(f)
            except Exception as e:
                err[name] = f'{type(e).__name__}: {e}'
                continue
            L = np.asarray(L, bool); S = np.asarray(S, bool)
            a = np.zeros(b.n, np.int8)
            a[L & win] = 1
            a[S & win & ~L] = -1
            sigs[name] = a

    # --- MQL --------------------------------------------------------------------
    if any(v == 'mql' for v in want.values()):
        import mql_transpile as MT
        for name, corp in want.items():
            if corp != 'mql' or name not in ms:
                continue
            try:
                a = MT.run_compiled(ms[name]['sides'], b)
            except Exception as e:
                err[name] = f'{type(e).__name__}: {e}'
                continue
            sigs[name] = np.where(win, a, 0).astype(np.int8)

    return sigs, err


# ------------------------------------------------------------------------- batterie
def cell(tab, t10, pool, idx, sgn):
    """La batterie sur UNE cellule (signal x actif x bracket).

    Etage 1 (bon marche): n, t, demi-echantillons, stress de cout.
    Etage 2 (nulls, ~600 walks): seulement si l'etage 1 passe. Le crible est le
    meme pour les reels et les placebos, donc il ne deforme pas le rapport."""
    R, xi, ei = tab.walk_idx(idx, sgn)
    if len(R) < MIN_TRADES:
        return None
    t0 = K.tstat(R)
    h = len(R) // 2
    tpre, trec = K.tstat(R[:h]), K.tstat(R[h:])
    R10, _, _ = t10.walk_idx(idx, sgn)
    t10s = K.tstat(R10)
    lf = float((sgn > 0).mean())
    gate1 = bool(t0 > 2 and tpre > 0 and trec > 0 and t10s > 1)

    pA = pB = np.nan
    if gate1:
        nt = K.null_ts(tab, pool, len(R), lf, ndraw=NDRAW,
                       rng=np.random.default_rng(7))
        pA = float((nt >= t0).mean()) if len(nt) else np.nan
        if 0.02 < lf < 0.98:                      # Null B n'a de sens qu'a deux sens
            rng = np.random.default_rng(11)
            tb = []
            for _ in range(NDRAW):
                Rb, _, _ = tab.walk_idx(idx, rng.permutation(sgn))
                if len(Rb) > 20:
                    tb.append(K.tstat(Rb))
            tb = np.array([x for x in tb if np.isfinite(x)])
            pB = float((tb >= t0).mean()) if len(tb) else np.nan
    passe = bool(gate1 and (pA < 0.05) and (np.isnan(pB) or pB < 0.05))
    # R/an et RoMaD pour lire l'ampleur des survivants, pas pour les filtrer
    st = K.cell_stats(tab.b, R, xi) or {}
    return dict(n=len(R), lf=lf, t=float(t0), t_pre=float(tpre), t_rec=float(trec),
                t_cost10=float(t10s), pA=pA, pB=pB, gate1=gate1, passe=passe,
                Ryr=st.get('Ryr', np.nan), RoMaD=st.get('RoMaD', np.nan),
                PF=st.get('PF', np.nan), win=st.get('win', np.nan))


def placebo_like(a, pool, rng):
    """Signal aleatoire apparie: meme nombre d'entrees, meme fraction longue,
    barres tirees dans la meme fenetre de seance eligible."""
    idx = np.flatnonzero(a != 0)
    k = len(idx)
    if k == 0 or k > len(pool):
        return None, None
    lf = float((a[idx] > 0).mean())
    pick = np.sort(rng.choice(pool, size=k, replace=False))
    sgn = np.where(rng.random(k) < lf, 1, -1).astype(np.int8)
    return pick, sgn


# ----------------------------------------------------------------------------- main
def run_asset(sym, nplac):
    """Un actif = un processus. Ecrit `battery_full_<SYM>.csv` en continu."""
    want = cohort()
    ps = json.load(open(f'{OUT}/pine_specs.json'))
    ms = json.load(open(f'{OUT}/mql_specs.json'))
    print(f'[{sym}] cohorte {len(want)} signaux {pd.Series(want).value_counts().to_dict()}'
          f' x {len(BRACKETS)} brackets x (1 reel + {nplac} placebos)', flush=True)

    T0 = t0 = time.time()
    b = K.Bars(sym, TF[sym], source='inx', min_bars=5000)
    b.sym = sym
    sb = session_bars(b)
    i = np.arange(b.n)
    pool = np.flatnonzero((i > K.WARMUP) & (i < b.n - 1) & np.asarray(b.in_window, bool))

    tabs = {br: K.Table(b, br[0], br[1], sb + 1, session=True, floor_spread=FLOOR)
            for br in BRACKETS}
    c10 = b.cost(extra_pts=10)
    t10s = {br: K.Table(b, br[0], br[1], sb + 1, rt=c10, session=True,
                        floor_spread=FLOOR) for br in BRACKETS}

    sigs, err = build_signals(b, sym, want, ps, ms)
    print(f'[{sym}] {TF[sym]} {b.n} barres, {sb} barres/seance, '
          f'{len(sigs)} signaux construits, {len(err)} en erreur '
          f'[{time.time()-t0:.0f}s]', flush=True)

    path = f'{OUT}/battery_full_{sym}.csv'
    rows, done = [], 0
    for name, a in sigs.items():
        done += 1
        idx = np.flatnonzero(a != 0)
        idx = idx[idx > K.WARMUP]
        if len(idx) < MIN_TRADES:
            continue
        cohorts = [('reel', idx, a[idx])]
        rng = np.random.default_rng(zlib.crc32(f'{sym}|{name}'.encode()) % (2**31))
        for r in range(nplac):
            pi, psg = placebo_like(a, pool, rng)
            if pi is not None:
                cohorts.append((f'placebo{r}', pi, psg))
        for kind, ii, ss in cohorts:
            for br in BRACKETS:
                res = cell(tabs[br], t10s[br], pool, ii, ss)
                if res:
                    rows.append(dict(kind='reel' if kind == 'reel' else 'placebo',
                                     rep=kind, corpus=want[name], sig=name, sym=sym,
                                     sl=br[0], tp=br[1],
                                     primary=(br == PRIMARY), **res))
        if done % 20 == 0:
            pd.DataFrame(rows).to_csv(path, index=False)
            d = pd.DataFrame(rows)
            print(f'[{sym}] {done}/{len(sigs)} signaux | {len(rows)} cellules | '
                  f'survivantes reel={int(d[d.kind=="reel"].passe.sum())} '
                  f'plac={int(d[d.kind=="placebo"].passe.sum())} | '
                  f'{(time.time()-T0)/60:.0f}min', flush=True)

    df = pd.DataFrame(rows)
    df.to_csv(path, index=False)
    print(f'[{sym}] TERMINE {len(df)} cellules -> {path} '
          f'[{(time.time()-T0)/60:.1f}min]', flush=True)


def load_all():
    fs = glob.glob(f'{OUT}/battery_full_*.csv')
    if not fs:
        sys.exit('aucun battery_full_<SYM>.csv')
    return pd.concat([pd.read_csv(f) for f in fs], ignore_index=True)


def report(df):
    print('=' * 78)
    print(f'{len(df):,} cellules mesurees sur {df.sym.nunique()} actifs, '
          f'{df[df.kind=="reel"].sig.nunique()} signaux')

    for lbl, d in (('BRACKET PRIMAIRE SEUL (SL 1.5xATR, sans cible) — aucune selection',
                    df[df['primary']]),
                   ('MEILLEUR DES 9 BRACKETS (selection, calibree par le placebo)', df)):
        print('\n' + '-' * 78)
        print(lbl)
        # une cellule = un (kind, rep, sig, sym); "passe" = au moins un bracket passe
        g = (d.groupby(['kind', 'rep', 'sig', 'sym'])['passe'].max()
             .reset_index().groupby('kind')['passe'].agg(['sum', 'size', 'mean']))
        print(g.rename(columns={'sum': 'survivants', 'size': 'testees',
                                'mean': 'taux'}).to_string())
        if 'placebo' in g.index and 'reel' in g.index:
            from scipy import stats
            sr, nr = int(g.loc['reel', 'sum']), int(g.loc['reel', 'size'])
            sp, npl = int(g.loc['placebo', 'sum']), int(g.loc['placebo', 'size'])
            pr, pp = sr / nr, sp / npl
            # le taux placebo est lui-meme ESTIME -> Fisher exact sur le 2x2, pas une
            # binomiale contre un taux suppose connu (qui exploserait a placebo=0).
            odds, pval = stats.fisher_exact([[sr, nr - sr], [sp, npl - sp]],
                                            alternative='greater')
            rtxt = f'{pr/pp:.2f}x' if pp > 0 else ('n/a (0 survivant placebo)'
                                                   if sr else 'n/a (0 des deux cotes)')
            print(f'  taux reel {pr:.4f} ({sr}/{nr}) vs placebo {pp:.4f} ({sp}/{npl})'
                  f'  -> rapport {rtxt}')
            print(f'  Fisher exact (reel > placebo): p = {pval:.4g}'
                  f'   [p<0.05 = la cohorte reelle survit plus que le hasard]')

        # replication cross-actifs, reels vs placebos
        rep = (d.groupby(['kind', 'rep', 'sig', 'sym'])['passe'].max().reset_index()
               .groupby(['kind', 'rep', 'sig'])['passe'].sum().reset_index())
        for k in ('reel', 'placebo'):
            s = rep[rep.kind == k]['passe']
            if len(s):
                print(f'  {k:<8} signaux passant sur >=1 actif: {int((s>=1).sum()):>4}'
                      f' | >=2: {int((s>=2).sum()):>4} | >=3: {int((s>=3).sum()):>4}'
                      f'  (sur {len(s)} tirages de signal)')

    dr = df[df.kind == 'reel']
    top = (dr.groupby(['sig', 'corpus'])
           .agg(actifs_passes=('passe', 'sum'), t_max=('t', 'max'),
                t_med=('t', 'median'), Ryr_max=('Ryr', 'max'))
           .sort_values(['actifs_passes', 't_med'], ascending=False))
    print('\n' + '-' * 78)
    print('TETES DE COHORTE (reels), classees par nombre de cellules passant la batterie')
    print(top.head(25).to_string())
    surv = dr[dr.passe]
    if len(surv):
        print('\nCELLULES SURVIVANTES (reels):')
        print(surv[['corpus', 'sig', 'sym', 'sl', 'tp', 'n', 't', 't_pre', 't_rec',
                    't_cost10', 'pA', 'pB', 'Ryr', 'RoMaD']]
              .sort_values('t', ascending=False).to_string(index=False))


if __name__ == '__main__':
    arg = sys.argv[1] if len(sys.argv) > 1 else 'report'
    if arg == 'report':
        report(load_all())
    elif arg in UNI:
        run_asset(arg, int(sys.argv[2]) if len(sys.argv) > 2 else 2)
    else:
        sys.exit(f'usage: battery_full.py [{"|".join(UNI)}|report] [n_placebo]')
