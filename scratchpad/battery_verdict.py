"""VERDICT — agregation des deux passes de batterie, avec DEDUPLICATION.

Ce script ne mesure rien: il lit `battery_tod_<SYM>.csv` (passe principale, placebo
et Null A apparies sur l'heure de seance) et `battery_full_<SYM>.csv` (passe de
controle, placebo uniforme) et en tire le verdict.

LES DEUX PIEGES QU'IL DESAMORCE
--------------------------------
1. **Les noms de signaux ne sont pas des mecanismes.** Le meme mecanisme arrive
   par trois sources (une regle TSaM + deux scripts Pine) et compte alors trois
   fois. Mesure sur NAS100: `T:NDB_10`, `ed171c5755ae` et `fea1f3e0a589` ont
   n=4155, t=3.813171 et Ryr=61.162887 IDENTIQUES a la 6e decimale. Compter les
   noms gonflerait le nombre de "decouvertes" d'un facteur 3 a 10.

   On deduplique donc sur une EMPREINTE de comportement: le vecteur
   (n, t) sur les 9 brackets, par actif. Deux signaux qui produisent exactement la
   meme suite de trades sur 9 brackets SONT la meme strategie, quel que soit le
   fichier d'ou ils viennent — c'est la bonne unite, et c'est aussi la seule qui
   rende le denominateur honnete (on deduplique la COHORTE, pas seulement les
   survivants).

2. **Le denominateur doit suivre.** Une fois la cohorte reduite a ses mecanismes
   distincts, on ne garde qu'UN representant par mecanisme, avec SES placebos.
   Sans ca on comparerait des survivants dedupliques a un taux placebo non-duplique.

3. **LE PIEGE PRINCIPAL: la cohorte reelle est DEJA PRESELECTIONNEE, pas le placebo.**
   Les 352 signaux sont ici parce qu'ils ont touche t>2 quelque part dans le sweep
   d'origine — sur CES MEMES donnees. Le placebo, lui, est tire frais, sans aucun
   filtre. Comparer les deux taux de survie brute revient donc a comparer des
   candidats deja filtres a des candidats non filtres, et la batterie ne fait alors
   que re-mesurer le filtre. Mesure: 13.6 % des cellules reelles atteignent t>2 sur
   au moins un des 9 brackets, contre 2.1 % des placebos — c'est cet ecart, et non
   un edge, qui produit le rapport brut de ~6x.

   Le seul rapport interpretable est donc **CONDITIONNEL A LA MEME PRESELECTION**:
   on ne garde des DEUX cotes que les cellules ayant t>2 sur >=1 des 9 brackets, et
   on compare leur taux de passage du RESTE de la batterie (nulls, demi-echantillons,
   stress de cout). C'est la lecture que ce script met en avant.

Le chiffre qui tranche est **survivants reels / survivants placebo A PRESELECTION
EGALE**, teste par Fisher exact (le taux placebo est estime, pas connu).

Usage:  python -u scratchpad/battery_verdict.py
"""
import sys, os, glob, warnings
sys.path.insert(0, 'scratchpad'); sys.path.insert(0, '.')
warnings.filterwarnings('ignore')
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import numpy as np
import pandas as pd
from scipy import stats

OUT = os.path.join('scratchpad', '_inx')
UNI = ['NAS100', 'US500', 'US30', 'GER40', 'FRA40', 'XAUUSD']


def load(tag):
    fs = sorted(glob.glob(f'{OUT}/battery_{tag}_*.csv'))
    if not fs:
        return None
    d = pd.concat([pd.read_csv(f) for f in fs], ignore_index=True)
    return d[d.sym.isin(UNI)]


def fingerprint(d):
    """Empreinte de comportement d'un (sig, sym): (n, t) sur les 9 brackets."""
    r = d[d.kind == 'reel']
    fp = (r.sort_values(['sl', 'tp'])
          .groupby(['sym', 'sig'])
          .apply(lambda g: '|'.join(f'{int(x)}:{y:.6f}' for x, y in zip(g.n, g.t))))
    return fp.rename('fp').reset_index()


def dedupe(d):
    """Garde UN representant par (sym, empreinte), avec ses placebos."""
    fp = fingerprint(d)
    keep = fp.sort_values('sig').groupby(['sym', 'fp'], as_index=False).first()
    idx = pd.MultiIndex.from_frame(keep[['sym', 'sig']])
    m = pd.MultiIndex.from_frame(d[['sym', 'sig']]).isin(idx)
    return d[m], fp


def survival(d, label, primary_only=False):
    dd = d[d['primary']] if primary_only else d
    g = (dd.groupby(['kind', 'rep', 'sig', 'sym'])['passe'].max().reset_index()
         .groupby('kind')['passe'].agg(['sum', 'size']))
    if 'reel' not in g.index:
        return None
    sr, nr = int(g.loc['reel', 'sum']), int(g.loc['reel', 'size'])
    sp = int(g.loc['placebo', 'sum']) if 'placebo' in g.index else 0
    npl = int(g.loc['placebo', 'size']) if 'placebo' in g.index else 0
    pr = sr / nr if nr else np.nan
    pp = sp / npl if npl else np.nan
    _, pval = stats.fisher_exact([[sr, nr - sr], [sp, npl - sp]], alternative='greater')
    rat = f'{pr/pp:>6.2f}x' if pp and pp > 0 else ('   inf' if sr else '   n/a')
    print(f'  {label:<44} reel {sr:>4}/{nr:<5} ({pr:6.2%})   '
          f'placebo {sp:>4}/{npl:<5} ({pp:6.2%})   {rat}   Fisher p={pval:.3g}')
    return dict(sr=sr, nr=nr, sp=sp, npl=npl, p=pval)


def conditional(d, label):
    """LE test decisif: a PRESELECTION EGALE (>=1 des 9 brackets a t>2 des deux
    cotes), le reel passe-t-il le RESTE de la batterie plus souvent que le placebo ?"""
    u = (d.groupby(['kind', 'rep', 'sig', 'sym'])
         .agg(sel=('t', lambda x: bool((x > 2).any())), passe=('passe', 'max'))
         .reset_index())
    print(f'\n  {label}')
    print(f'    taux de PRESELECTION (>=1 des 9 brackets a t>2): '
          f'reel {u[u.kind=="reel"].sel.mean():.1%} | '
          f'placebo {u[u.kind=="placebo"].sel.mean():.1%}'
          f'   <- cet ecart est la SELECTION, pas un edge')
    s = u[u.sel]
    a = s[s.kind == 'reel'].passe.values.astype(int)
    b = s[s.kind == 'placebo'].passe.values.astype(int)
    if not len(a) or not len(b):
        print('    pas assez de cellules preselectionnees des deux cotes')
        return
    print(f'    reel    {a.sum():>4}/{len(a):<5} = {a.mean():6.2%} passent le reste')
    print(f'    placebo {b.sum():>4}/{len(b):<5} = {b.mean():6.2%} passent le reste')
    rng = np.random.default_rng(0)
    r = [x.mean() / y.mean() for x, y in
         ((rng.choice(a, len(a)), rng.choice(b, len(b))) for _ in range(20000))
         if y.mean() > 0]
    r = np.array(r)
    _, p1 = stats.fisher_exact([[a.sum(), len(a) - a.sum()],
                                [b.sum(), len(b) - b.sum()]], alternative='greater')
    _, p2 = stats.fisher_exact([[a.sum(), len(a) - a.sum()],
                                [b.sum(), len(b) - b.sum()]], alternative='two-sided')
    print(f'    RAPPORT CONDITIONNEL = {a.mean()/b.mean():.2f}x  '
          f'IC bootstrap 95% [{np.percentile(r,2.5):.2f}, {np.percentile(r,97.5):.2f}]'
          f'   Fisher p(reel>placebo)={p1:.3f}  bilateral={p2:.3f}')
    rep = s.groupby(['kind', 'rep', 'sig']).passe.sum().reset_index()
    for k in ('reel', 'placebo'):
        x = rep[rep.kind == k].passe
        if len(x):
            print(f'    replication {k:<8} >=1 actif {int((x>=1).sum()):>3} | '
                  f'>=2 {int((x>=2).sum()):>3} | >=3 {int((x>=3).sum()):>3}'
                  f'   (sur {len(x)})')


def replication(d, label):
    s = (d.groupby(['kind', 'rep', 'sig', 'sym'])['passe'].max().reset_index()
         .groupby(['kind', 'rep', 'sig'])['passe'].sum().reset_index())
    for k in ('reel', 'placebo'):
        x = s[s.kind == k]['passe']
        if len(x):
            print(f'    {label} {k:<8} >=1 actif: {int((x>=1).sum()):>4} | '
                  f'>=2: {int((x>=2).sum()):>3} | >=3: {int((x>=3).sum()):>3} | '
                  f'>=4: {int((x>=4).sum()):>3}   (sur {len(x)} tirages)')


def main():
    tod, full = load('tod'), load('full')
    print('=' * 96)
    print('VERDICT — batterie complete sur tous les signaux ayant touche t>2')
    print('=' * 96)
    for tag, d in (('TOD', tod), ('UNIF', full)):
        if d is not None:
            print(f'{tag:<5} {len(d):>7,} cellules | {d.sym.nunique()} actifs '
                  f'| {d[d.kind=="reel"].sig.nunique()} noms de signaux')
    if tod is None:
        sys.exit('passe TOD absente')

    syms = sorted(set(tod.sym) & (set(full.sym) if full is not None else set(tod.sym)))
    print(f'\nActifs communs aux deux passes: {syms}')

    for tag, d in (('PASSE PRINCIPALE — placebo + Null A apparies sur l\'heure de seance', tod),
                   ('PASSE DE CONTROLE — placebo uniforme dans la seance', full)):
        if d is None:
            continue
        d = d[d.sym.isin(syms)]
        ded, fp = dedupe(d)
        nm = fp.groupby('sym').size().to_dict()
        nd = ded[ded.kind == 'reel'].groupby('sym').sig.nunique().to_dict()
        print('\n' + '-' * 96)
        print(tag)
        print(f'  noms de signaux par actif : {nm}')
        print(f'  MECANISMES DISTINCTS      : {nd}')
        print()
        print('  --- survie BRUTE (trompeuse: le placebo n a subi aucune preselection)')
        survival(d, 'AVANT dedup, best-of-9 brackets')
        survival(ded, 'APRES dedup, best-of-9 brackets')
        survival(ded, 'APRES dedup, bracket primaire seul', primary_only=True)
        print()
        replication(ded, 'dedup')
        conditional(ded, '>>> TEST DECISIF — a PRESELECTION EGALE des deux cotes <<<')

    # ---- les survivants de la passe principale, dedupliques -------------------
    ded, _ = dedupe(tod[tod.sym.isin(syms)])
    surv = ded[(ded.kind == 'reel') & ded.passe]
    print('\n' + '=' * 96)
    print(f'SURVIVANTS (passe principale, dedupliques) — {len(surv)} cellules, '
          f'{surv.sig.nunique()} mecanismes, {surv.sym.nunique()} actifs')
    if len(surv):
        by = (surv.groupby(['sig', 'corpus'])
              .agg(actifs=('sym', 'nunique'), cellules=('t', 'size'),
                   t_max=('t', 'max'), n_max=('n', 'max'),
                   Ryr_max=('Ryr', 'max'), RoMaD_max=('RoMaD', 'max'))
              .sort_values(['actifs', 't_max'], ascending=False))
        print(by.head(40).to_string())
        print('\nrepartition par actif:')
        print(surv.groupby('sym').agg(cellules=('t', 'size'),
                                      mecanismes=('sig', 'nunique')).to_string())
        rep = surv.groupby('sig').sym.nunique()
        multi = rep[rep >= 2]
        print(f'\nMECANISMES REPLIQUANT SUR >=2 ACTIFS: {len(multi)}')
        if len(multi):
            print(surv[surv.sig.isin(multi.index)]
                  [['sig', 'corpus', 'sym', 'sl', 'tp', 'n', 't', 't_pre', 't_rec',
                    't_cost10', 'pA', 'pB', 'Ryr', 'RoMaD']]
                  .sort_values(['sig', 'sym']).to_string(index=False))
    ded.to_csv(f'{OUT}/battery_verdict_dedup.csv', index=False)
    print(f'\n-> {OUT}/battery_verdict_dedup.csv')


if __name__ == '__main__':
    main()
