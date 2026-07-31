"""Pass 2 — find the articles whose rules are actually STATED, then apply the user's filters.

Structural fact discovered in pass 1: quantifiedstrategies.com gates the formal
"Trading Rules" box behind MemberPress ("THIS SECTION IS FOR MEMBERS ONLY" /
"You find the trading rules at the bottom of the article"). A minority of articles
nevertheless state the rule in running prose, e.g.

  "enter a long position when the IBS value is below 0.2 ... exit ... above 0.8"
  "We go long at the close on the fifth last trading day of the month, and we exit after seven days"

Those are reproducible; the gated ones are not. This pass separates them and applies the
user's three filters (mechanical rules / no external data / US-EU indices, FX, gold, crypto).

    python scratchpad/qs_triage2.py
"""
import sys; sys.stdout.reconfigure(encoding='utf-8')

import os
import re
import glob

import pandas as pd

P = 'scratchpad/qs_pages'
GATED = r"section is for members only|become a member to get access|" \
        r"you find the trading rules at the bottom|members only"
ACTION = r"(?:we |you |traders? (?:can|may) )?(?:buy|sell|go long|go short|enter|exit|close|" \
         r"take a long|take a short|long|short)\b"
COND = r"(?:when|if|at|after|on the|below|above|cross(?:es)?|reaches|greater than|less than|" \
        r"lower than|higher than)"
# a STATED rule = action + condition + (a number OR an explicit indicator/session word)
NUMISH = r"(?:\d|first|second|third|fourth|fifth|sixth|seventh|last|close|open|high|low|" \
         r"average|band|channel|cross)"
RULE_SENT = re.compile(rf"[^.!?]*?\b{ACTION}\b[^.!?]{{0,80}}?\b{COND}\b[^.!?]{{0,120}}?"
                       rf"{NUMISH}[^.!?]{{0,120}}[.!?]", re.I)

ASSET = {
    'US': r"S&P ?500|\bSPY\b|\bSPX\b|e-?mini|\bES\b|\bNasdaq\b|\bQQQ\b|\bNQ\b|Dow Jones|"
          r"\bDJIA\b|\bDIA\b|Russell 2000|\bIWM\b|\bRTY\b",
    'EU': r"\bDAX\b|Euro ?Stoxx|\bFTSE\b|\bCAC\b|\bIBEX\b|\bAEX\b|\bSMI\b",
    'FX': r"\bforex\b|EUR ?/? ?USD|GBP ?/? ?JPY|EUR ?/? ?JPY|USD ?/? ?JPY|currency pair",
    'GOLD': r"\bgold\b|\bGLD\b|\bXAU\b",
    'CRYPTO': r"\bbitcoin\b|\bBTC\b|\bcrypto|\bethereum\b",
}
OFF = (r"\bTLT\b|treasur|\bbond\b|NIFTY|\bsector\b|\bXL[PUEVFYKIB]\b|penny stock|\bsilver\b|"
       r"platinum|\bcorn\b|cocoa|\bsugar\b|heating oil|\bcrude\b|lumber|\bcopper\b|\bREIT\b|"
       r"\bAAPL\b|\bNVDA\b|\bAMZN\b|\bMETA\b|Vanguard|\bFXI\b|\bBrazil\b|\bIndia\b|"
       r"mutual fund|\bportfolio\b allocation|merger arb|short interest")
EXT = (r"\bVIX\b|put[- ]call|\bNAAIM\b|\bAAII\b|Investors Intelligence|\bTRIN\b|advance[- ]decline|"
       r"\bCPI\b|\bPMI\b|\bISM\b|non[- ]farm|\bNFP\b|interest rate|earnings report|F-Score|"
       r"consumer confidence|MOVE index|\bCOT\b|short interest|fundamental")


def main():
    rows = []
    for f in sorted(glob.glob(f'{P}/*.txt')):
        t = open(f, encoding='utf-8', errors='ignore').read()
        low = t.lower()
        sents = [re.sub(r'\s+', ' ', s).strip() for s in RULE_SENT.findall(t)]
        # drop boilerplate / marketing sentences
        sents = [s for s in sents if 8 < len(s.split()) < 60
                 and not re.search(r'(?i)member|subscrib|click here|article|newsletter|course', s)]
        a = {k: len(re.findall(v, t, re.I)) for k, v in ASSET.items()}
        rows.append(dict(
            slug=os.path.basename(f)[:-4], chars=len(t),
            gated=len(re.findall(GATED, low)), n_rule=len(sents),
            asset=max(a, key=a.get) if max(a.values()) else '-', asset_hits=max(a.values()),
            off=len(re.findall(OFF, t, re.I)), ext=len(re.findall(EXT, t, re.I)),
            rules=' || '.join(sents[:6])))
    df = pd.DataFrame(rows)
    df.to_csv('scratchpad/qs_triage2.csv', index=False, encoding='utf-8')

    print(f"  {len(df)} articles")
    print(f"  explicitement VERROUILLES (members only)      : {(df.gated > 0).sum()}")
    print(f"  avec >=1 phrase-regle exploitable dans le texte: {(df.n_rule >= 1).sum()}")
    print(f"  avec >=2 phrases-regles                        : {(df.n_rule >= 2).sum()}")

    keep = df[(df.n_rule >= 2) & (df.asset_hits >= 3) & (df.ext <= 3) & (df.off <= 8)]
    keep = keep.sort_values(['asset', 'n_rule'], ascending=[True, False])
    keep.to_csv('scratchpad/qs_shortlist.csv', index=False, encoding='utf-8')
    print(f"\n  APRES LES 3 FILTRES UTILISATEUR -> {len(keep)} articles a lire en detail")
    print(f"  par classe d'actif: {dict(keep.asset.value_counts())}")
    for r in keep.itertuples():
        print(f"\n  [{r.asset}] {r.slug}  (regles={r.n_rule} ext={r.ext} off={r.off})")
        for s in r.rules.split(' || ')[:3]:
            print(f"      - {s[:180]}")


if __name__ == '__main__':
    main()
