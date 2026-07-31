"""Round 2 — widen the GitHub harvest beyond the 25 curated repos.

Round 1 took 836 strategy files from repos found by a handful of searches. This round
searches systematically (many queries x several sort orders), drops the repos already
harvested, and pulls the rest. Same filters as always: a file counts only if it carries a
real entry/exit (populate_entry_trend / strategy.entry / OrderSend-OnTick), and the
external-data and ML exclusions are applied downstream by code_parse.py.

MQL5 note: mql5.com never serves the code body without an authenticated session (probed:
/view 404, ?view=source has no OnTick, 0 `input` lines visible). So MQL here comes from
GitHub mirrors only.

    python scratchpad/code_harvest2.py
"""
import sys; sys.stdout.reconfigure(encoding='utf-8')

import json
import re
import time
from pathlib import Path

import requests

UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) research/1.0'}
OUT = Path('scratchpad/code'); OUT.mkdir(parents=True, exist_ok=True)
API = 'https://api.github.com'

QUERIES = [
    # MQL — the best asset fit (FX / indices / gold)
    ('mql', 'mql5 expert advisor'), ('mql', 'mql4 expert advisor'),
    ('mql', 'metatrader expert advisor strategy'), ('mql', 'forex expert advisor'),
    ('mql', 'mt4 ea source'), ('mql', 'mt5 trading robot'),
    # Pine
    ('pine', 'pine script strategy backtest'), ('pine', 'tradingview strategy pine'),
    ('pine', 'pinescript v5 strategy'), ('pine', 'pine strategy collection'),
    # Freqtrade / generic python strategies
    ('freqtrade', 'freqtrade strategies collection'), ('freqtrade', 'freqtrade user_data strategies'),
    ('freqtrade', 'freqtrade hyperopt strategy'),
    ('freqtrade', 'backtrader strategy collection'), ('freqtrade', 'trading strategies python backtest'),
]
EXT = {'freqtrade': ('.py',), 'pine': ('.pine', '.txt', '.ps'), 'mql': ('.mq4', '.mq5')}
SIG = {
    'freqtrade': r'populate_entry_trend|populate_buy_trend|class \w+\(IStrategy\)|class \w+\(bt\.Strategy\)',
    'pine': r'strategy\s*\(|strategy\.entry|strategy\.close',
    'mql': r'OrderSend|PositionOpen|trade\.Buy|trade\.Sell|OnTick',
}


def search(q, sort):
    try:
        r = requests.get(f'{API}/search/repositories?q={q}&sort={sort}&per_page=30',
                         headers=UA, timeout=40)
        if r.status_code != 200:
            return []
        return [i['full_name'] for i in r.json().get('items', [])]
    except Exception:
        return []


def tree(repo):
    for br in ('main', 'master'):
        try:
            r = requests.get(f'{API}/repos/{repo}/git/trees/{br}?recursive=1', headers=UA, timeout=40)
        except Exception:
            return []
        if r.status_code == 200:
            return [x['path'] for x in r.json().get('tree', []) if x['type'] == 'blob']
        if r.status_code == 403:
            return ['__QUOTA__']
    return []


def raw(repo, path):
    for br in ('main', 'master'):
        try:
            r = requests.get(f'https://raw.githubusercontent.com/{repo}/{br}/{path}',
                             headers=UA, timeout=30)
        except Exception:
            continue
        if r.status_code == 200:
            return r.text
    return ''


def main():
    old = {e['repo'] for e in json.loads(Path('scratchpad/code_index.json').read_text(encoding='utf-8'))}
    found = {}
    for lang, q in QUERIES:
        for sort in ('stars', 'updated'):
            for r in search(q.replace(' ', '+'), sort):
                found.setdefault(r, lang)
            time.sleep(7)                       # unauthenticated search: ~10/min
    new = {r: l for r, l in found.items() if r not in old}
    print(f"  {len(found)} depots trouves, {len(new)} nouveaux a explorer\n")

    idx = json.loads(Path('scratchpad/code_index.json').read_text(encoding='utf-8'))
    added = 0
    for repo, lang in new.items():
        exts, sig = EXT[lang], SIG[lang]
        paths = tree(repo)
        if paths and paths[0] == '__QUOTA__':
            print('  ! quota API atteint -> arret propre'); break
        paths = [p for p in paths if p.lower().endswith(exts)]
        if not paths:
            continue
        d = OUT / lang / repo.replace('/', '__'); d.mkdir(parents=True, exist_ok=True)
        kept = 0
        for p in paths[:300]:
            f = d / re.sub(r'[^A-Za-z0-9._-]', '_', p)[-90:]
            txt = f.read_text(encoding='utf-8', errors='ignore') if f.exists() else raw(repo, p)
            if not f.exists():
                f.write_text(txt or '', encoding='utf-8'); time.sleep(0.05)
            if txt and re.search(sig, txt, re.I) and len(txt) > 400:
                idx.append(dict(lang=lang, repo=repo, path=p, file=str(f), chars=len(txt)))
                kept += 1; added += 1
        if kept:
            print(f'  [{lang}] {repo:<52} +{kept:>4} strategies', flush=True)
    Path('scratchpad/code_index.json').write_text(json.dumps(idx, indent=1), encoding='utf-8')
    from collections import Counter
    print(f'\n  +{added} nouveaux fichiers | TOTAL {len(idx)}')
    for k, v in Counter(x['lang'] for x in idx).items():
        print(f'    {k:<12} {v}')


if __name__ == '__main__':
    main()
