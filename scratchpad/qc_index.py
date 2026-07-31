"""Stage 1 — scrape the Quantocracy link index (153 pages, ~3000 links).

Quantocracy hosts nothing: it is a daily link aggregator pointing at 100+ external quant
blogs. So the funnel is longer than the quantifiedstrategies one:
    index pages -> titles/excerpts/URLs -> filter -> fetch each EXTERNAL blog post ->
    extract rules -> keep the fully-specified ones -> backtest.

This file does the index only, and caches it, so the filtering can be iterated offline.

    python scratchpad/qc_index.py
"""
import sys; sys.stdout.reconfigure(encoding='utf-8')

import re
import time
from pathlib import Path

import pandas as pd
import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) research/1.0"}
OUT = Path('scratchpad/qc'); OUT.mkdir(parents=True, exist_ok=True)
BASE = 'https://quantocracy.com/'


def page(n: int) -> str:
    f = OUT / f'idx_{n:03d}.html'
    if f.exists():
        return f.read_text(encoding='utf-8', errors='ignore')
    url = BASE if n == 1 else f'{BASE}?pg={n}'
    try:
        h = requests.get(url, headers=UA, timeout=30).text
    except Exception as exc:
        print(f'   ! page {n}: {type(exc).__name__}'); return ''
    f.write_text(h, encoding='utf-8')
    time.sleep(0.6)
    return h


def parse(html: str) -> list[dict]:
    """Entries are <article class='qo-entry'> with a qo-title link, a qo-description
    summary and a dated footer. Titles carry the source blog in trailing [Brackets]."""
    rows = []
    for m in re.finditer(r"<article class='qo-entry'>(.*?)</article>", html, re.S):
        blk = m.group(1)
        a = re.search(r"<a class='qo-title' href='([^']+)'[^>]*>(.*?)</a>", blk, re.S)
        if not a:
            continue
        url = a.group(1)
        title = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', a.group(2))).strip()
        blog = ''
        b = re.search(r'\[([^\]]+)\]\s*$', title)
        if b:
            blog = b.group(1).strip(); title = title[:b.start()].strip()
        d = re.search(r"<summary class='qo-description'>(.*?)</summary>", blk, re.S)
        exc = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', d.group(1))).strip() if d else ''
        dt = re.search(r'<span class="qo-500-ignore">,\s*([^<]+)</span>', blk)
        rows.append(dict(title=title, blog=blog, url=url,
                         date=dt.group(1).strip() if dt else '',
                         excerpt=exc.replace('(...)', '')[:500],
                         host=re.sub(r'^www\.', '', url.split('/')[2])))
    return rows


def main():
    all_rows, n = [], 1
    while n <= 200:
        h = page(n)
        if not h:
            break
        rows = parse(h)
        if not rows and n > 3:
            print(f'  page {n}: 0 entree -> fin'); break
        all_rows += rows
        if n % 20 == 0:
            print(f'  page {n}: cumul {len(all_rows)} liens')
        # stop when pagination runs out
        if n > 1 and f'pg={n+1}' not in h and 'older' not in h.lower():
            print(f'  page {n}: plus de pagination -> fin'); break
        n += 1
    df = pd.DataFrame(all_rows).drop_duplicates('url')
    df.to_csv('scratchpad/qc_links.csv', index=False, encoding='utf-8')
    print(f'\n  {len(df)} liens uniques sur {n} pages -> scratchpad/qc_links.csv')
    print(f'  {df.host.nunique()} blogs sources. Top 15 :')
    for h, c in df.host.value_counts().head(15).items():
        print(f'    {c:>4}  {h}')


if __name__ == '__main__':
    main()
