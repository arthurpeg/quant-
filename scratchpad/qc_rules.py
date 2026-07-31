"""Stage 4 — find which of the 144 fetched articles actually state a mechanical rule."""
import sys; sys.stdout.reconfigure(encoding='utf-8')
import re, glob, os, hashlib
import pandas as pd

ACTION = (r"(?:we |you |I )?(?:buy|sell|go long|go short|enter|exit|close|take a long|"
          r"take a short|short|long)\b")
COND = (r"(?:when|if|at|after|on the|below|above|cross(?:es|ed)?|reaches|greater than|"
        r"less than|lower than|higher than|falls|rises|closes)")
NUM = r"(?:\d|first|second|third|last|close|open|high|low|average|band|channel)"
RULE = re.compile(rf"[^.!?]*?\b{ACTION}\b[^.!?]{{0,90}}?\b{COND}\b[^.!?]{{0,140}}?{NUM}[^.!?]{{0,140}}[.!?]", re.I)
GATE = r"(?i)members only|subscribe to (?:read|continue)|paid subscriber|this post is for|premium content|sign up to read"

def slug(u):
    base = re.sub(r'[^a-z0-9]+','-',u.rstrip('/').split('/')[-1].lower())[:60]
    return f"{base or 'x'}-{hashlib.md5(u.encode()).hexdigest()[:6]}"

d = pd.read_csv('scratchpad/qc_shortlist.csv').fillna('')
rows=[]
for r in d.itertuples():
    f = f'scratchpad/qc_pages/{slug(r.url)}.txt'
    if not os.path.exists(f): continue
    t = open(f, encoding='utf-8', errors='ignore').read()
    if len(t) < 1500: continue
    sents = [re.sub(r'\s+',' ',s).strip() for s in RULE.findall(t)]
    sents = [s for s in sents if 7 < len(s.split()) < 55
             and not re.search(r'(?i)subscrib|member|click|cookie|newsletter|comment|email|privacy', s)]
    seen=set(); uniq=[]
    for s in sents:
        k=s.lower()[:60]
        if k not in seen: seen.add(k); uniq.append(s)
    rows.append(dict(title=r.title, blog=r.blog, url=r.url, chars=len(t),
                     gated=len(re.findall(GATE,t)), n_rule=len(uniq),
                     rules=' || '.join(uniq[:6])))
x = pd.DataFrame(rows).sort_values('n_rule', ascending=False)
x.to_csv('scratchpad/qc_rules.csv', index=False, encoding='utf-8')
print(f"  {len(x)} articles avec du texte exploitable")
print(f"    verrouilles (paywall detecte)   : {(x.gated>0).sum()}")
print(f"    avec >=1 phrase-regle chiffree  : {(x.n_rule>=1).sum()}")
print(f"    avec >=3 phrases-regles         : {(x.n_rule>=3).sum()}")
print(f"    avec >=5 phrases-regles         : {(x.n_rule>=5).sum()}")
print(f"\n  LES 22 ARTICLES LES PLUS RICHES EN REGLES :\n")
for i,r in enumerate(x.head(22).itertuples(),1):
    print(f"{i:>2}. [{r.blog[:20]:<20}] {r.title[:78]}  (regles={r.n_rule})")
    for s in str(r.rules).split(' || ')[:2]:
        print(f"      - {s[:155]}")
