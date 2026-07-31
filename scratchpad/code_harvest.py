"""Harvest mechanical trading rules from CODE (not papers) — Freqtrade / Pine / MQL5.

Why code: a paper describes, code executes. Every strategy file has a 100%-mechanical
entry, exit and (usually) an explicit stop — so it passes the user's "clear rules" filter
by construction, which ~19 800 screened papers and blog posts did not.

ACCESS REALITY (probed 2026-07-31):
  * mql5.com    — the CodeBase page does NOT contain the source; downloading it requires
                  a logged-in account -> not harvested from there.
  * tradingview — pine-facade only serves TradingView's own BUILT-IN indicators
                  (STD; prefix, 145 of them). Community published Pine needs the site's
                  internal API -> not harvested from there.
  * GitHub      — serves all three languages as raw files, no auth needed. So GitHub is
                  the single practical door, and it is used for all three.

Strategy: 1 API call per repo (git trees, recursive) to list files, then raw.githubusercontent
for the files themselves (no API rate limit on raw). That keeps us well inside the
unauthenticated API budget.

    python scratchpad/code_harvest.py
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

# Curated high-volume repos per language (found via the GitHub search API).
REPOS = {
    'freqtrade': [
        'freqtrade/freqtrade-strategies', 'iterativv/NostalgiaForInfinity',
        'eovie/freqtrade_strs', 'nateemma/strategies', 'PeetCrypto/freqtrade-stuff',
        'werkkrew/freqtrade-strategies', 'paulcpk/freqtrade-strategies-that-work',
        'Rikj000/MoniGoMani', 'ssssi/freqtrade_strs', 'hippocritical/freqtrade_strategies',
        'froggleston/cryptofrog-strategies', 'raph92/freqtrade-strategies',
    ],
    'pine': [
        'everget/tradingview-pinescript-indicators', 'Alorse/pinescript-strategies',
        'fmzquant/strategies', 'AlbertoCuadra/algo_trading_weighted_strategy',
        'pinecoders/pine-utils', 'just-nilux/awesome-tradingview',
        'TreborNamor/TradingView-Machine-Learning-GUI',
    ],
    'mql': [
        'EA31337/EA31337-classes', 'EarnForex/MQL-Scripts', 'mql5-org/mql5-samples',
        'ForexRobotAcademy/mql5', 'jonchun/mt4-mql', 'rosasurfer/mt4-mql',
    ],
}
EXT = {'freqtrade': ('.py',), 'pine': ('.pine', '.txt', '.ps'), 'mql': ('.mq4', '.mq5')}
# a file must look like a STRATEGY, not a helper/indicator/library
SIG = {
    'freqtrade': r'populate_entry_trend|populate_buy_trend|class \w+\(IStrategy\)',
    'pine': r'strategy\s*\(|strategy\.entry|strategy\.close',
    'mql': r'OrderSend|PositionOpen|trade\.Buy|trade\.Sell|OnTick',
}


def tree(repo):
    for br in ('main', 'master'):
        try:
            r = requests.get(f'{API}/repos/{repo}/git/trees/{br}?recursive=1',
                             headers=UA, timeout=40)
        except Exception:
            return []
        if r.status_code == 200:
            return [x['path'] for x in r.json().get('tree', []) if x['type'] == 'blob']
        if r.status_code == 403:
            print('   ! quota API GitHub atteint'); return []
    return []


def raw(repo, path):
    for br in ('main', 'master'):
        u = f'https://raw.githubusercontent.com/{repo}/{br}/{path}'
        try:
            r = requests.get(u, headers=UA, timeout=30)
        except Exception:
            continue
        if r.status_code == 200:
            return r.text
    return ''


def main():
    idx = []
    for lang, repos in REPOS.items():
        exts, sig = EXT[lang], SIG[lang]
        kept = 0
        for repo in repos:
            paths = [p for p in tree(repo) if p.lower().endswith(exts)]
            if not paths:
                continue
            d = OUT / lang / repo.replace('/', '__'); d.mkdir(parents=True, exist_ok=True)
            for p in paths[:400]:
                f = d / re.sub(r'[^A-Za-z0-9._-]', '_', p)[-90:]
                if f.exists():
                    txt = f.read_text(encoding='utf-8', errors='ignore')
                else:
                    txt = raw(repo, p)
                    f.write_text(txt or '', encoding='utf-8')
                    time.sleep(0.05)
                if txt and re.search(sig, txt, re.I) and len(txt) > 400:
                    idx.append(dict(lang=lang, repo=repo, path=p, file=str(f), chars=len(txt)))
                    kept += 1
            print(f'  [{lang}] {repo:<48} {len(paths):>4} fichiers, {kept:>4} strategies cumulees',
                  flush=True)
    Path('scratchpad/code_index.json').write_text(json.dumps(idx, indent=1), encoding='utf-8')
    print(f'\n  TOTAL: {len(idx)} fichiers de STRATEGIE recoltes')
    from collections import Counter
    for k, v in Counter(x['lang'] for x in idx).items():
        print(f'    {k:<12} {v}')


if __name__ == '__main__':
    main()
