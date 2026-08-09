"""ENTONNOIR MQL — 1256 .mq4 + 2202 .mq5 -> signaux d'entree executables.

`mql_transpile.compile_file` extrait la CONDITION D'ENTREE (il remonte des appels
OrderSend/trade.Buy/PositionOpen vers les `if` englobants et les combine), et jette
bracket, lots, trailing et money management — le bracket est le notre, ce qui est
exactement ce que l'utilisateur a demande ("si il n'y a pas de sl tu testes
differentes variantes de sl").

Le multi-timeframe est gere par le transpileur et il est CAUSAL: une barre H4
estampillee t n'est complete qu'a t+4h, donc la valeur visible a la cloture de la
barre M15 courante est la derniere barre H4 close. C'est le piege look-ahead que le
ledger enregistre pour les conditions journalieres sur entrees intraday.
"""
import os, sys, json, time, hashlib, warnings
sys.path.insert(0, 'scratchpad')
warnings.filterwarnings('ignore')
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from collections import Counter

OUT = os.path.join('scratchpad', '_inx')
MQ4 = os.path.join('scratchpad', '_corpus', 'mt4')
MQ5 = r'C:\Users\arthu\OneDrive\Desktop\src'


def walk(root, ext):
    return [os.path.join(dp, f) for dp, _, fs in os.walk(root)
            for f in fs if f.lower().endswith(ext)]


def funnel():
    from mql_transpile import compile_file, Unsupported
    files = [('mq4', p) for p in walk(MQ4, '.mq4')] + [('mq5', p) for p in walk(MQ5, '.mq5')]
    why, specs = Counter(), {}
    for lang, p in files:
        try:
            sides, meta = compile_file(p)     # -> ({'long':expr,'short':expr}, meta)
        except Unsupported as e:
            why[str(e)[:44]] += 1
            continue
        except Exception as e:
            why[type(e).__name__] += 1
            continue
        key = hashlib.md5(json.dumps(sides, sort_keys=True).encode()).hexdigest()[:12]
        if key in specs:
            specs[key]['n_dupes'] += 1
            continue
        specs[key] = dict(sig=key, lang=lang, sides=sides,
                          file=os.path.basename(p), n_dupes=1)
    return files, why, specs


if __name__ == '__main__':
    t0 = time.time()
    files, why, specs = funnel()
    n4 = sum(1 for l, _ in files if l == 'mq4')
    print('=' * 78)
    print(f'  MQL — {len(files)} fichiers ({n4} .mq4 + {len(files)-n4} .mq5)')
    print('=' * 78)
    print(f'  compiles                        {sum(s["n_dupes"] for s in specs.values()):5d}')
    print(f'  SIGNAUX DISTINCTS apres dedupe  {len(specs):5d}   <- a backtester')
    print(f'\n  raisons de rejet (top 18):')
    for k, v in why.most_common(18):
        print(f'    {v:5d}  {k}')
    json.dump(specs, open(f'{OUT}/mql_specs.json', 'w'), indent=0)
    print(f'\n  -> {OUT}/mql_specs.json   [{time.time()-t0:.0f}s]')
