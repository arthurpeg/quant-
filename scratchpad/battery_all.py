"""BATTERIE COMPLETE sur TOUS les signaux ayant une cellule t>2, + PLACEBO APPARIE.

Demande utilisateur (2026-08-10): *"backtest toutes les strategies au-dessus de t>2
peu importe s'il y en a moins que par chance ... avec tous les tests qu'on fait passer
on devrait etre en mesure de discerner la chance d'un edge"*.

LA DEMANDE EST FONDEE, ET ELLE CORRIGE UNE ERREUR DE MA PART: j'avais pre-filtre sur
la replication AVANT de faire passer la batterie. Or un filtre en amont jette peut-etre
un signal qui aurait survecu a tout le reste. On teste donc TOUT LE MONDE.

MAIS UNE BATTERIE NE DEFAIT PAS LA SELECTION — elle la DEPLACE, sauf si on la calibre.
Le ledger l'enregistre deja: une short-list choisie sur le fait de battre un null
repasse son propre null **81 %** du temps. Empiler 6 tests sur des tetes de grille
produit donc des "survivants" meme quand il n'y a rien, et on ne peut pas le savoir en
regardant seulement le nombre de survivants.

D'OU LE PLACEBO APPARIE, et c'est ce qui rend la demande de l'utilisateur decidable:
on fait passer **la batterie IDENTIQUE** a une cohorte de signaux ALEATOIRES construits
pour ressembler aux vrais (meme nombre d'entrees par actif, meme fraction longue, memes
barres eligibles en seance). Le chiffre qui tranche n'est alors pas "combien de vrais
survivent" mais **le RAPPORT survivants reels / survivants placebo**. C'est la methode
qui avait donne 6.4x sur la crypto et 0.2-0.5x sur FX/indices en D1.

  survie reelle >> survie placebo  -> il y a un edge dans la cohorte
  survie reelle ~= survie placebo  -> les survivants sont ce que la chance produit,
                                      quel que soit le nombre de tests passes

BATTERIE (identique pour reels et placebo), par (signal, actif), bracket PRE-DECLARE
SL 1.5 x ATR14 sans cible, sortie forcee a la cloture, plancher 25 spreads:
  1. t net
  2. Null A  (derive/timing) — 300 tirages
  3. Null B  (direction)     — 300 tirages, si la regle prend les deux sens
  4. demi-echantillons: les DEUX moities doivent etre positives
  5. stress de cout: t a +10 points/cote
  6. replication: nombre d'actifs qui passent 1-5

Usage:  python -u scratchpad/battery_all.py [n_placebo_par_signal]
"""
import sys, os, json, glob, warnings
sys.path.insert(0, 'scratchpad'); sys.path.insert(0, '.')
warnings.filterwarnings('ignore')
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import numpy as np, pandas as pd
import kauf_lib as K, inx_data as D
from corpus_run import TF, FLOOR, session_bars

SL, NDRAW = 1.5, 300
UNI = ['NAS100', 'US500', 'US30', 'GER40', 'FRA40', 'XAUUSD']
OUT = 'scratchpad/_inx'


def cohort():
    """Tous les signaux ayant AU MOINS UNE cellule t>2, quel que soit le corpus."""
    parts = []
    for pat, corp in (('corpus_*.parquet', 'pine'), ('mql_*.parquet', 'mql'),
                      ('fq_*.parquet', 'freqtrade')):
        fs = glob.glob(f'{OUT}/{pat}')
        if fs:
            d = pd.concat([pd.read_parquet(f) for f in fs], ignore_index=True)
            d['corpus'] = corp
            parts.append(d[['corpus', 'sig', 'sym', 't']])
    D_ = pd.concat(parts, ignore_index=True)
    hot = D_[D_['t'] > 2]['sig'].unique()
    return sorted(set(hot))


def signal_of(corp, sig, b, win, ps, ms):
    if corp == 'mql':
        import mql_transpile as MT
        return np.where(win, MT.run_compiled(ms[sig]['sides'], b), 0).astype(np.int8)
    from tv_transpile import Spec
    from tv_pine import F
    df = b.d.copy(); df.index = df.index.tz_convert(D.SESSION[b.sym][0])
    L, S, *_ = Spec(ps[sig]['code'], {}).run(F(df, K.SPECS[b.sym]['point']))
    a = np.zeros(b.n, np.int8)
    a[np.asarray(L, bool) & win] = 1
    a[np.asarray(S, bool) & win & ~np.asarray(L, bool)] = -1
    return a


def run_one(b, tab, pool, a, cost10_tab):
    """La batterie sur un (signal, actif). -> dict ou None si pas mesurable."""
    idx = np.flatnonzero(a != 0); idx = idx[idx > K.WARMUP]
    if len(idx) < 40:
        return None
    R, xi, ei = tab.walk_idx(idx, a[idx])
    if len(R) < 40:
        return None
    t0 = K.tstat(R); lf = float((a[idx] > 0).mean()); h = len(R) // 2
    nt = K.null_ts(tab, pool, len(R), lf, ndraw=NDRAW, rng=np.random.default_rng(7))
    pA = float((nt >= t0).mean())
    pB = np.nan
    if 0.02 < lf < 0.98:
        rng = np.random.default_rng(11); tb = []
        for _ in range(NDRAW):
            Rb, _, _ = tab.walk_idx(idx, rng.permutation(a[idx]))
            if len(Rb) > 20:
                tb.append(K.tstat(Rb))
        pB = float((np.array(tb) >= t0).mean()) if tb else np.nan
    R10, _, _ = cost10_tab.walk_idx(idx, a[idx])
    tpre, trec = K.tstat(R[:h]), K.tstat(R[h:])
    ok = (t0 > 2 and pA < 0.05 and (np.isnan(pB) or pB < 0.05)
          and tpre > 0 and trec > 0 and K.tstat(R10) > 1)
    return dict(n=len(R), t=t0, pA=pA, pB=pB, t_pre=tpre, t_rec=trec,
                t_cost10=K.tstat(R10), passe=bool(ok))


def placebo_like(a, pool, rng):
    """Signal aleatoire apparie: meme nombre d'entrees, meme fraction longue,
    barres tirees dans la meme fenetre de seance."""
    idx = np.flatnonzero(a != 0)
    k, lf = len(idx), float((a[idx] > 0).mean()) if len(idx) else 0.5
    out = np.zeros(len(a), np.int8)
    if k == 0 or k > len(pool):
        return out
    pick = rng.choice(pool, size=k, replace=False)
    sgn = np.where(rng.random(k) < lf, 1, -1).astype(np.int8)
    out[pick] = sgn
    return out


def main():
    nplac = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    ps = json.load(open(f'{OUT}/pine_specs.json'))
    ms = json.load(open(f'{OUT}/mql_specs.json'))
    sigs = cohort()
    print(f'{len(sigs)} signaux avec au moins une cellule t>2 -> batterie sur {len(UNI)} actifs')
    rows = []
    for sym in UNI:
        b = K.Bars(sym, TF[sym], source='inx', min_bars=5000)
        b.sym = sym
        win = np.asarray(b.in_window, bool); sb = session_bars(b)
        tab = K.Table(b, SL, None, sb + 1, session=True, floor_spread=FLOOR)
        t10 = K.Table(b, SL, None, sb + 1, rt=b.cost(extra_pts=10), session=True,
                      floor_spread=FLOOR)
        i = np.arange(b.n)
        pool = np.flatnonzero((i > K.WARMUP) & (i < b.n - 1) & win)
        rng = np.random.default_rng(2026)
        for sig in sigs:
            corp = 'mql' if sig in ms else 'pine'
            try:
                a = signal_of(corp, sig, b, win, ps, ms)
            except Exception:
                continue
            r = run_one(b, tab, pool, a, t10)
            if r:
                rows.append(dict(kind='reel', corpus=corp, sig=sig, sym=sym, **r))
            for _ in range(nplac):
                rp = run_one(b, tab, pool, placebo_like(a, pool, rng), t10)
                if rp:
                    rows.append(dict(kind='placebo', corpus=corp, sig=sig, sym=sym, **rp))
        print(f'  {sym} fait ({len(rows)} lignes)', flush=True)
    df = pd.DataFrame(rows)
    df.to_csv(f'{OUT}/battery_all.csv', index=False)
    print(f'\n-> {OUT}/battery_all.csv')
    g = df.groupby('kind')['passe'].agg(['sum', 'size', 'mean'])
    print('\n=== SURVIE A LA BATTERIE COMPLETE ===')
    print(g.rename(columns={'sum': 'survivants', 'size': 'testes', 'mean': 'taux'}).to_string())
    r = g.loc['reel', 'mean'] / max(g.loc['placebo', 'mean'], 1e-9) if 'placebo' in g.index else np.nan
    print(f"\n  RAPPORT reel/placebo = {r:.2f}x   "
          f"(>>1 = edge dans la cohorte; ~1 = ce que la chance produit)")
    rep = df[df.kind == 'reel'].groupby('sig')['passe'].sum().sort_values(ascending=False)
    print(f'\n  signaux passant la batterie sur >=2 actifs: {int((rep >= 2).sum())}')
    print(rep[rep >= 1].head(20).to_string())


if __name__ == '__main__':
    main()
