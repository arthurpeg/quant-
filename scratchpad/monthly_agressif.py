"""Monthly profile of the AGRESSIF book (what is deployed live on the demo).

AGRESSIF = b1 + b2 + b3 + b4 @1R, KAER@0.5R, KELT@0.5R   (= the old "config D")
FUNDED   = b1 + b2 + b3@0.5R + b4 @1R, KELT@0.5R          (= the old "config E")

Sizing is fixed-fractional on the INITIAL balance and does NOT compound (the project's
convention, and the prop model's), so a month's % return is simply
    month %  =  month R  x  risk-per-trade.
"""
import sys, warnings
sys.path.insert(0, 'scratchpad'); sys.path.insert(0, '.')
warnings.filterwarnings('ignore')
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import numpy as np
import pandas as pd

from book_optimise import sleeves, perf, NAMES

BOOKS = {'AGRESSIF (live demo)': (1, 1, 1, 1, .5, .5),
         'FUNDED':               (1, 1, .5, 1, 0, .5)}
RISKS = (0.005, 0.0075, 0.01)


def monthly(s):
    return s.resample('ME').sum()


def main():
    M, (s0, s1) = sleeves()
    mid = M.index[len(M) // 2]
    for nm, w in BOOKS.items():
        s = pd.Series(M[NAMES].to_numpy() @ np.array(w), index=M.index)
        for tag, sl in (('echantillon complet', slice(None)),
                        ('2e moitie (proxy fwd-test)', slice(mid, None))):
            m = monthly(s.loc[sl])
            m = m[:-1] if len(m) and m.index[-1].month == s.index[-1].month else m  # drop partial
            print('=' * 92)
            print(f'{nm}  —  {tag}   ({len(m)} mois complets, {m.index[0]:%Y-%m} -> {m.index[-1]:%Y-%m})')
            print('=' * 92)
            print(f'  moyenne   {m.mean():+7.2f} R/mois     mediane {m.median():+7.2f} R')
            print(f'  ecart-type{m.std():7.2f} R          meilleur {m.max():+.2f} R   pire {m.min():+.2f} R')
            print(f'  MOIS POSITIFS : {int((m > 0).sum())}/{len(m)} = {(m > 0).mean():.1%}'
                  f'   (>= +1R : {(m >= 1).mean():.1%})')
            q = m.quantile([.05, .25, .5, .75, .95])
            print('  percentiles R : ' + '  '.join(f'{int(p*100)}e {v:+.1f}' for p, v in q.items()))
            print(f"  {'risque/trade':<14}{'moyenne %/mois':>16}{'mediane %/mois':>16}"
                  f"{'pire mois':>12}{'meilleur':>10}")
            for r in RISKS:
                print(f'  {r*100:>8.2f}%     {m.mean()*r*100:>14.2f}%{m.median()*r*100:>16.2f}%'
                      f'{m.min()*r*100:>11.2f}%{m.max()*r*100:>9.2f}%')
            if tag.startswith('echantillon'):
                print('\n  R par annee civile (mois complets) :')
                y = m.groupby(m.index.year)
                for yy, v in y:
                    print(f'    {yy}  {v.sum():+7.1f} R   ({int((v > 0).sum())}/{len(v)} mois +)')
            print()


if __name__ == '__main__':
    main()
