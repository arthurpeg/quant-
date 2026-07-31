"""Stage 3 — fetch the 231 shortlisted Quantocracy articles from their source blogs."""
import sys; sys.stdout.reconfigure(encoding='utf-8')
import re, time, hashlib
from pathlib import Path
import pandas as pd, requests

OUT = Path('scratchpad/qc_pages'); OUT.mkdir(parents=True, exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) research/1.0"}

def slug(u):
    base = re.sub(r'[^a-z0-9]+', '-', u.rstrip('/').split('/')[-1].lower())[:60]
    return f"{base or 'x'}-{hashlib.md5(u.encode()).hexdigest()[:6]}"

def fetch(u):
    f = OUT / f'{slug(u)}.txt'
    if f.exists(): return len(f.read_text(encoding='utf-8', errors='ignore'))
    try:
        r = requests.get(u, headers=UA, timeout=25, allow_redirects=True)
        h = r.text if r.status_code == 200 else ''
    except Exception:
        h = ''
    if not h:
        f.write_text('', encoding='utf-8'); return 0
    h = re.sub(r'(?is)<(script|style|nav|footer|header|form|aside).*?</\1>', ' ', h)
    t = re.sub(r'(?s)<[^>]+>', ' ', h)
    t = re.sub(r'&#\d+;|&[a-z]+;', ' ', t)
    t = re.sub(r'[ \t]+', ' ', t); t = re.sub(r'\n\s*\n+', '\n', t)
    f.write_text(t, encoding='utf-8'); time.sleep(0.5)
    return len(t)

d = pd.read_csv('scratchpad/qc_shortlist.csv').fillna('')
ok = dead = 0
for i, u in enumerate(d.url, 1):
    n = fetch(u)
    if n > 1500: ok += 1
    else: dead += 1
    if i % 40 == 0: print(f'  {i}/{len(d)} | exploitables {ok} | vides/morts {dead}', flush=True)
print(f'\nTERMINE: {ok} articles exploitables, {dead} vides ou morts', flush=True)
