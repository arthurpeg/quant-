"""ORB de Lundstrom / Holmberg-Lonnbark-Lundstrom (2013), porte a la lettre.

Source: `scratchpad/_pdf_txt/z.txt` — *Day trading returns across volatility states*.
Regle, telle que le papier l'ecrit (et Crabel 1990 avant lui):
  * seuils psi_u = P_open + rho et psi_l = P_open - rho;
  * le trader prend un LONG si le prix franchit psi_u par le bas, un SHORT s'il
    franchit psi_l par le haut;
  * il **sort a la cloture du marche** — pas de cible, pas de sortie sur signal;
  * la strategie n'a QU'UN parametre, rho, et le papier balaie volontairement un
    grand nombre de valeurs "pour eviter le data snooping". On fait pareil.
  * these centrale a tester: le rendement doit CROITRE avec l'etat de volatilite
    (deciles). C'est ce qui est reporte en bas, et c'est le vrai test du papier —
    pas le rendement moyen.

DEUX ECARTS, declares:
  1. **stop obligatoire** k x ATR14. Le papier n'en a pas (il sort a la cloture);
     la regle du projet l'impose. On balaie k, et on reporte aussi le cas quasi
     sans stop (k=6) pour voir ce que le stop coute a la these du papier.
  2. rho est exprime en multiples de la VOLATILITE DE SEANCE recente (ecart-type
     des |cloture-ouverture| des 20 dernieres seances), et non en pourcentage brut
     du prix: c'est ce qui rend le meme rho comparable entre le NAS100, le CAC et
     l'or. Le papier travaille sur un seul actif a la fois et n'a pas ce probleme.
"""
import sys, os, itertools, warnings
sys.path.insert(0, 'scratchpad')
warnings.filterwarnings('ignore')
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import numpy as np, pandas as pd
import kauf_lib as K
from corpus_run import UNIVERSE, TF, FLOOR, session_bars

RHO = (0.2, 0.4, 0.6, 0.8, 1.0, 1.5)      # multiples de la vol de seance
SL = (1.0, 2.0, 3.0, 6.0)                  # 6.0 ~= "presque pas de stop"


def signal(b, rho):
    win = np.asarray(b.in_window, bool); idx = np.flatnonzero(win)
    o, h, l, c = b.o[idx], b.h[idx], b.l[idx], b.c[idx]
    sess = np.asarray(b.sess)[idx]
    S = pd.Series(sess); pos = S.groupby(S, sort=False).cumcount().to_numpy()
    op = pd.Series(o).groupby(sess).first().reindex(sess).to_numpy()
    cl = pd.Series(c).groupby(sess).last()
    # volatilite de seance = ecart-type des moves cloture-ouverture, 20 seances,
    # DECALEE d'une seance (causal: on ne connait pas la seance en cours)
    mv = (cl - pd.Series(op).groupby(sess).first()).abs()
    sig_s = mv.rolling(20, min_periods=10).std().shift(1)
    sd = sig_s.reindex(sess).to_numpy()
    up, dn = op + rho * sd, op - rho * sd
    s = np.zeros(len(c), np.int8)
    s[(c > up) & (pos > 0)] = 1
    s[(c < dn) & (pos > 0) & ~(c > up)] = -1
    nz = s != 0
    first = pd.Series(np.where(nz, pos, 10**9)).groupby(sess).transform('min').to_numpy()
    s = np.where(nz & (pos == first), s, 0).astype(np.int8)   # une entree par seance
    full = np.zeros(b.n, np.int8); full[idx] = s
    # decile de volatilite de la seance (pour la these du papier)
    dec = pd.qcut(pd.Series(sd).rank(method='first'), 10, labels=False, duplicates='drop')
    fd = np.full(b.n, -1.0); fd[idx] = dec.to_numpy(float)
    return full, fd


def main():
    rows = []
    for sym in UNIVERSE:
        b = K.Bars(sym, TF[sym], source='inx', min_bars=5000)
        sb = session_bars(b)
        for rho, sl in itertools.product(RHO, SL):
            s, dec = signal(b, rho)
            idx = np.flatnonzero(s != 0); idx = idx[idx > K.WARMUP]
            if len(idx) < 30:
                continue
            tab = K.Table(b, sl, None, sb + 1, session=True, floor_spread=FLOOR)
            R, xi, ei = tab.walk_idx(idx, s[idx])
            st = K.cell_stats(b, R, xi)
            if st is None or st['n'] < 30:
                continue
            d = dec[ei]
            lo = R[d <= 2].mean() if (d <= 2).sum() > 8 else np.nan
            hi = R[d >= 7].mean() if (d >= 7).sum() > 8 else np.nan
            rows.append(dict(sym=sym, rho=rho, sl=sl, ER_lowvol=lo, ER_highvol=hi,
                             vol_spread=(hi - lo), **st))
        print(f'{sym:<7} ok', flush=True)
    df = pd.DataFrame(rows)
    df.to_parquet('scratchpad/_inx/orb_paper.parquet', index=False)
    print(f'\n{len(df)} cellules (6 actifs x {len(RHO)} rho x {len(SL)} stops)\n')
    print('--- rendement par actif (mediane et max sur la grille) ---')
    print(df.groupby('sym').agg(t_med=('t','median'), t_max=('t','max'),
                                ER_med=('ER','median'), n=('n','median')).round(3).to_string())
    print('\n--- THESE DU PAPIER: E[R] haute vol MOINS E[R] basse vol (doit etre > 0) ---')
    print(df.groupby('sym').agg(vol_spread_med=('vol_spread','median'),
                                positif=('vol_spread', lambda x: float((x>0).mean()))
                                ).round(3).to_string())
    print(f"\n  toutes cellules confondues: ecart median {df['vol_spread'].median():+.4f} R, "
          f"positif dans {float((df['vol_spread']>0).mean()):.0%} des cellules")
    print('\n--- effet du stop sur la these (le papier n\'en a pas) ---')
    print(df.groupby('sl').agg(t_med=('t','median'), ER_med=('ER','median'),
                               vol_spread=('vol_spread','median')).round(4).to_string())


if __name__ == '__main__':
    main()
