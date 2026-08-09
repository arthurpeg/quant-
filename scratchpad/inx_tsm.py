"""TSM-COIL — une strategie intraday COMPOSEE a partir de TSaM (Kaufman, 5e ed.).

Pas une cellule d'un sweep: une strategie dessinee a partir de ce que le livre
ARGUMENTE, et dont chaque ingredient repond a un ECHEC MESURE de la passe du
2026-08-07 (`RESEARCH_LOG_KAUFMAN.md`). Aucune donnee externe: OHLC + spread du
seul sous-jacent.

CE QUE LA MESURE IMPOSE AU DESIGN
---------------------------------
1. **La friction est LA contrainte, pas le signal.** Le peage median mesure
   **0.079 R/trade** en M15, et la loi de bruit de Kaufman ne vaut que **+0.010
   R/trade**: 8x trop petit. Median t passe de -2.7 net a -0.02 brut — toute la
   distribution est un decalage de friction. => il faut **peu de trades** et un
   **1R grand devant le spread**, pas un filtre de plus.
2. **Le seul edge BRUT positif de facon consistante est la CONTINUATION de
   cassure intraday sur indices US** (brut median: kaer_follow +1.70, kaer_switch
   +1.87, kama_flip +1.39, meyers +0.96; forex NEGATIF brut). => sens = suivi de
   cassure, univers = indices d'abord.
3. **La strategie intraday du livre (Midday S/R) n'a aucun edge brut** (median
   brut -0.26, et -0.29 sur la jambe fade des indices US, la ou Kaufman la dit la
   meilleure). => ne pas la reprendre.
4. **KAER est rejetee pour 3 raisons a ne pas reproduire**: 293 trades/an (donc
   23 R/an de friction), replication cross-actifs qui echoue (significative sur 1
   actif), et corr **+0.370** a la brique 1 avec 40% de jours communs. => viser
   **~30-60 trades/an/actif**, sur un ancrage DIFFERENT de celui de la brique 1.
5. **Piege declare** (Meyers/USDJPY): brut +5.07 -> net -0.55, et le meme signal
   "survit" a SL 2.0xATR (net +2.01) uniquement parce qu'elargir 1R dilue le
   peage. **Un edge qui n'apparait qu'en elargissant le stop est un choix de
   largeur de stop, pas un edge.** On teste donc la grille de stops en entier et
   on regarde si le resultat est plat ou pique.

LA COMPOSITION (5 chapitres, chacun pour une raison)
----------------------------------------------------
* **ch.16 (Day Trading) — niveau ANCRE SUR LA SEANCE.** Le niveau casse est
  l'OPENING RANGE de la premiere heure, un niveau REALISE, pas une projection
  ATR autour de l'ouverture (qui est la brique 1). C'est ce qui rend l'ancrage
  different et la correlation a la brique 1 une question empirique.
* **ch.16 (precondition de Crabel) — SEANCE ENROULEE.** On n'accepte la cassure
  que si l'opening range est ETROIT par rapport a sa propre histoire recente.
  C'est le seul ingredient qui reduit le nombre de trades d'un ordre de
  grandeur, donc le seul qui attaque la friction a la racine.
* **ch.1 / ch.17 / ch.20 — QUALITE DU MOUVEMENT via l'efficiency ratio, lu A LA
  BARRE DE SIGNAL.** La passe precedente a etabli la distinction qui compte: lu
  en t-n l'ER teste la *loi de regime* de Kaufman et elle est trop faible
  (t=1.93); lu a la barre de signal — la convention de Kaufman lui-meme, puisque
  le `sc_t` de KAMA utilise `ER_t` — il mesure **la qualite du mouvement achete**
  (une cassure nette plutot qu'un faux depart) et c'est bien plus fort (t=3.19).
* **ch.23 (Stops and Profit-Taking) — stop ADAPTATIF a la volatilite**, jamais un
  montant fixe: SL = k x ATR14.
* **PLANCHER SPREAD — la lecon KELT du projet, qui est aussi celle de ch.23**
  ("le stop doit etre en dehors du bruit"): 1R = max(k x ATR14, F x spread). Sans
  plancher, KELT affichait +27.1 R/an au lieu de +17.2. Ici il empeche
  mecaniquement de prendre un trade dont le peage mange le R.

TOUT EST PRE-DECLARE. La grille ci-dessous est fixee avant de regarder un
resultat, et le script imprime la grille ENTIERE, pas son maximum.
"""
import sys, os, itertools, time, warnings
sys.path.insert(0, 'scratchpad')
warnings.filterwarnings('ignore')
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import numpy as np
import pandas as pd

import kauf_lib as K
import inx_data as D

OUT = os.path.join('scratchpad', '_inx')
os.makedirs(OUT, exist_ok=True)

CLS = {**{s: 'metal' for s in D.METAL}, **{s: 'us_idx' for s in D.US_IDX},
       **{s: 'eu_idx' for s in D.EU_IDX}}
TF = {s: ('M15' if s in D.M1_SYMS else 'M10') for s in D.ALL}
BAR_MIN = {'M5': 5, 'M10': 10, 'M15': 15, 'M30': 30}

# --- grille PRE-DECLAREE ----------------------------------------------------
COIL_Q = (0.33, 0.50, 1.01)      # 1.01 = pas de filtre d'enroulement (temoin)
ER_Q = (0.00, 0.50, 0.67)        # 0.00 = pas de filtre de qualite (temoin)
SL_MULT = (1.0, 1.5, 2.0, 3.0)   # ch.23; la grille entiere est imprimee
TP_MULT = (None, 2.0)            # KAER n'a pas de target; on teste les deux
FLOOR_SPREAD = 25.0              # lecon KELT: 1R >= 25 spreads
OR_MINUTES = 60                  # ch.16: la premiere heure


def signal(b, coil_q, er_q, first_only=True):
    """+1/-1/0 par barre. Decision a la CLOTURE de la barre, fill a l'ouverture
    de la suivante (le moteur s'en charge). Tout se calcule dans le sous-espace
    EN SEANCE: les barres M15 reconstruites du M1 couvrent 23 h, donc la
    "premiere barre de la seance" prise sur le jour calendaire serait une barre
    de minuit — piege silencieux, cf. inx_rules.py."""
    n = b.n
    win = np.asarray(b.in_window, bool)
    idx = np.flatnonzero(win)
    if len(idx) < 1000:
        return np.zeros(n, np.int8)
    h, l, c = b.h[idx], b.l[idx], b.c[idx]
    sess = np.asarray(b.sess)[idx]
    atr = np.asarray(b.atr)[idx]
    er_rank = np.asarray(b.er_rank)[idx]
    S = pd.Series(sess)
    pos = S.groupby(S, sort=False).cumcount().to_numpy()

    k = max(1, int(round(OR_MINUTES / BAR_MIN[b.tf])))
    def first_k(x, how):
        masked = np.where(pos < k, x, -np.inf if how == 'max' else np.inf)
        v = pd.Series(masked).groupby(sess).agg(how).reindex(sess).to_numpy()
        return np.where(pos >= k, v, np.nan)

    orh, orl = first_k(h, 'max'), first_k(l, 'min')

    # --- ch.16 Crabel: la seance est-elle ENROULEE ? -------------------------
    # largeur de l'opening range normalisee par l'ATR (sans quoi on ne compare
    # que des niveaux de volatilite), rangee contre ses ~60 dernieres seances.
    width = (orh - orl) / np.where(np.isfinite(atr) & (atr > 0), atr, np.nan)
    w_sess = pd.Series(width).groupby(sess).first()
    w_rank = w_sess.rolling(60, min_periods=20).rank(pct=True)
    coil = w_rank.reindex(sess).to_numpy() <= coil_q

    # --- cassure de l'opening range ------------------------------------------
    up, dn = (c > orh), (c < orl)
    # --- ch.17 qualite du mouvement A LA BARRE DE SIGNAL ---------------------
    good = er_rank >= er_q if er_q > 0 else np.ones(len(c), bool)

    long_c = up & coil & good
    short_c = dn & coil & good
    s = np.zeros(len(c), np.int8)
    s[long_c] = 1
    s[short_c & ~long_c] = -1

    if first_only:
        # une seule cassure par seance: c'est l'ORB de ch.16, et c'est ce qui
        # divise le nombre de trades (donc la facture de friction) par ~5.
        nz = s != 0
        firstpos = pd.Series(np.where(nz, pos, 10**9)).groupby(sess).transform('min').to_numpy()
        s = np.where(nz & (pos == firstpos), s, 0).astype(np.int8)

    full = np.zeros(n, np.int8)
    full[idx] = s
    return full


def session_bars(b):
    s = pd.Series(b.in_window.astype(int)).groupby(b.sess).sum()
    return int(max(4, np.median(s[s > 0].to_numpy())))


def run_grid(syms=None):
    syms = syms or D.ALL
    rows = []
    for sym in syms:
        tf = TF[sym]
        try:
            b = K.Bars(sym, tf, source='inx', min_bars=5000)
        except Exception as e:
            print(f'{sym} SKIP {e}', flush=True)
            continue
        sb = session_bars(b)
        yrs = (b.time[-1] - b.time[0]).days / 365.25
        # la Table ne depend QUE du bracket, pas du signal: on la construit une
        # fois par (sl, tp) et on y fait passer les 9 variantes de signal.
        tables = {(sl, tp): K.Table(b, sl, tp, sb + 1, session=True,
                                    floor_spread=FLOOR_SPREAD)
                  for sl, tp in itertools.product(SL_MULT, TP_MULT)}
        for cq, eq in itertools.product(COIL_Q, ER_Q):
            sig = signal(b, cq, eq)
            idx = np.flatnonzero(sig != 0)
            if len(idx) < 30:
                continue
            for sl, tp in itertools.product(SL_MULT, TP_MULT):
                tab = tables[(sl, tp)]
                R, xi, ei = tab.walk_idx(idx, sig[idx])
                st = K.cell_stats(b, R, xi)
                if st is None or st['n'] < 30:
                    continue
                rows.append(dict(sym=sym, cls=CLS[sym], tf=tf, coil=cq, erq=eq,
                                 sl=sl, tp=(tp or 0), n_yr=st['n'] / yrs, **st))
        print(f'{sym:<7} {tf}  cellules={sum(1 for r in rows if r["sym"]==sym):>3} '
              f'[{time.time()-T0:.0f}s]', flush=True)
    return pd.DataFrame(rows)


T0 = time.time()
if __name__ == '__main__':
    df = run_grid(sys.argv[1].split(',') if len(sys.argv) > 1 else None)
    df.to_parquet(f'{OUT}/tsm_grid.parquet', index=False)
    print(f'\n=== {len(df)} cellules, {time.time()-T0:.0f}s ===\n')

    print('--- LA GRILLE ENTIERE par classe (mediane de t), pas son maximum ---')
    print(df.pivot_table(index=['coil', 'erq'], columns='cls', values='t',
                         aggfunc='median').round(2).to_string())
    print('\n--- effet du filtre d\'enroulement (temoin coil=1.01) ---')
    print(df.groupby(['cls', 'coil']).agg(cellules=('t', 'size'), t_med=('t', 'median'),
                                          n_par_an=('n_yr', 'median'),
                                          ER_med=('ER', 'median')).round(3).to_string())
    print('\n--- effet du filtre de qualite ER ---')
    print(df.groupby(['cls', 'erq']).agg(cellules=('t', 'size'), t_med=('t', 'median'),
                                         n_par_an=('n_yr', 'median')).round(3).to_string())
    print('\n--- profil de STOP (piege Meyers: un edge qui n\'apparait qu\'au stop large) ---')
    print(df.groupby(['cls', 'sl']).agg(t_med=('t', 'median'), ER_med=('ER', 'median'),
                                        PF_med=('PF', 'median')).round(3).to_string())
    print('\n--- par symbole, meilleure cellule ET mediane (la replication est le test) ---')
    g = df.groupby('sym').agg(cellules=('t', 'size'), t_med=('t', 'median'),
                              t_max=('t', 'max'), n_yr=('n_yr', 'median'))
    print(g.sort_values('t_max', ascending=False).round(2).to_string())
    print('\n--- top 15 cellules brutes ---')
    cols = ['sym', 'cls', 'tf', 'coil', 'erq', 'sl', 'tp', 'n', 'n_yr', 'ER', 'PF', 't', 'Ryr']
    cols = [c for c in cols if c in df.columns]
    print(df.sort_values('t', ascending=False).head(15)[cols].round(3).to_string(index=False))
    print(f'\n-> {OUT}/tsm_grid.parquet')
