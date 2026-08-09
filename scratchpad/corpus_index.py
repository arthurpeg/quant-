"""ENTONNOIR DU CORPUS — 2380 Pine + 1256 MQ4 + 2202 MQ5, vers des signaux executables.

Mandat utilisateur (2026-08-09): *"fouille tous les fichiers/dossiers du projet pour
recuperer tous les scripts, papiers etc... filtre-les avec sl/tp/entree, si il n'y a pas
de sl tu testes differentes variantes de sl (ATR, structure etc...), les strategies ne
doivent pas necessiter de donnees externes ... teste ABSOLUMENT TOUTES les strategies
qui sont interessantes ... uniquement intraday sur indices US (sauf US2000), indices EU
(uniquement France et Allemagne), or ... teste chaque strat sur TOUS ces actifs meme si
il est ecrit qu'elle ne marche que sur un actif."*

DEUX CONSEQUENCES SUR LE FILTRE, differentes des passes precedentes:
  * **L'ABSENCE DE SL N'ELIMINE PLUS.** Les passes precedentes exigeaient que le script
    publie lui-meme SL et TP (`require_bracket=True`), ce qui jetait la majorite du
    corpus. Ici on compile **la regle d'ENTREE SEULE** et c'est NOUS qui balayons le
    bracket (ATR, et structure = plus-bas/plus-haut recent). Le filtre restant est donc:
    une entree mecanique + aucune donnee externe.
  * **AUCUN FILTRE PAR ACTIF.** Ce qu'un auteur affirme sur "son" marche n'est pas une
    donnee, c'est une opinion; chaque signal est score sur les 6 actifs.

UNIVERS (fixe par l'utilisateur): NAS100, US500, US30, GER40, FRA40, XAUUSD.

DEDUPLICATION SUR LE CODE COMPILE, jamais sur le titre: le meme "RSI + EMA200" est
publie des dizaines de fois sous des noms differents, et le compter 50 fois gonflerait
tous les comptes en aval.
"""
import os, sys, json, re, hashlib, time, warnings
sys.path.insert(0, 'scratchpad')
warnings.filterwarnings('ignore')
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from collections import Counter

CORP = os.path.join('scratchpad', '_corpus')
OUT = os.path.join('scratchpad', '_inx')
os.makedirs(OUT, exist_ok=True)

UNIVERSE = ['NAS100', 'US500', 'US30', 'GER40', 'FRA40', 'XAUUSD']

# --- donnees EXTERNES: motifs qui disqualifient, quel que soit le langage ------
# On refuse tout ce qui lit un AUTRE symbole ou une serie non-OHLCV du symbole.
EXTERNAL = re.compile(
    r'request\.security|request\.financial|request\.economic|request\.dividends|'
    r'request\.earnings|request\.quandl|request\.splits|syminfo\.tickerid\s*!=|'
    r'iCustom\s*\(\s*"[^"]|SymbolInfo|MarketInfo\s*\(\s*"|'
    r'\bVIX\b|\bDXY\b|\bTNX\b|COT\b|sentiment|fundamental|news',
    re.I)
# volume: MT5 CFD "volume" = compte de ticks, pas du volume echange (ledger, ligne
# order-flow). Un signal qui en depend n'est pas reproductible -> on le marque.
VOLUME = re.compile(r'\bvolume\b|obv|\bmfi\b|vwap|accdist|pvt|cmf', re.I)


def pine_funnel(limit=None):
    from tv_pine import Unsupported
    from tv_transpile import compile_script
    files = sorted(f for f in os.listdir(os.path.join(CORP, 'tv')) if f.endswith('.pine'))
    if limit:
        files = files[:limit]
    ok, why, specs = 0, Counter(), {}
    ext, vol = 0, 0
    for fn in files:
        p = os.path.join(CORP, 'tv', fn)
        src = open(p, encoding='utf-8', errors='replace').read()
        if EXTERNAL.search(src):
            ext += 1
            why['DONNEES EXTERNES'] += 1
            continue
        try:
            # require_bracket=False -> on ne garde que la REGLE D'ENTREE
            sp = compile_script(src, require_bracket=False)
        except Unsupported as e:
            why[str(e).split(':')[0][:46]] += 1
            continue
        except Exception as e:
            why[f'{type(e).__name__}'] += 1
            continue
        ok += 1
        if VOLUME.search(src):
            vol += 1
        specs.setdefault(sp.sig, dict(sig=sp.sig, code=sp.code, meta=sp.meta,
                                      src_file=fn, volume=bool(VOLUME.search(src)),
                                      n_dupes=0))
        specs[sp.sig]['n_dupes'] += 1
    return files, ok, why, specs, ext, vol


if __name__ == '__main__':
    t0 = time.time()
    lim = int(sys.argv[1]) if len(sys.argv) > 1 else None
    files, ok, why, specs, ext, vol = pine_funnel(lim)
    print('=' * 78)
    print(f'  PINE — {len(files)} fichiers')
    print('=' * 78)
    print(f'  rejetes DONNEES EXTERNES        {ext:5d}')
    print(f'  compiles (regle d\'entree seule) {ok:5d}  ({ok/len(files):.1%})')
    print(f'  dont dependants du VOLUME       {vol:5d}  (tick-count sur CFD -> marques)')
    print(f'  SIGNAUX DISTINCTS apres dedupe  {len(specs):5d}'
          f'   <- ce sont eux qui seront backtestes')
    print(f'\n  raisons de rejet (top 15):')
    for k, v in why.most_common(15):
        print(f'    {v:5d}  {k}')
    top = sorted(specs.values(), key=lambda s: -s['n_dupes'])[:8]
    print(f'\n  les signaux les plus republies (le meme code sous N titres):')
    for s in top:
        print(f'    x{s["n_dupes"]:3d}  {s["src_file"][:56]}')
    json.dump({k: {kk: vv for kk, vv in v.items() if kk != 'meta'}
               for k, v in specs.items()},
              open(f'{OUT}/pine_specs.json', 'w'), indent=0)
    print(f'\n  -> {OUT}/pine_specs.json   [{time.time()-t0:.0f}s]')
