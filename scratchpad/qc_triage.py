"""Stage 2 — filter the 7606 Quantocracy links on title + excerpt (the user's 3 criteria).

At this stage only the asset filter and the external-data filter can be applied reliably;
"has explicit rules" needs the article itself. So this pass decides WHAT TO FETCH, and is
deliberately permissive on rules and strict on the two filters that titles can settle.

Quantocracy is dominated by things the user excluded: single-stock factor research
(value/momentum/quality on a stock cross-section), portfolio allocation / TAA / risk parity,
ML methodology, options & vol surface, fixed income, and macro commentary.

    python scratchpad/qc_triage.py
"""
import sys; sys.stdout.reconfigure(encoding='utf-8')

import re

import pandas as pd

ASSET = (r"\bS&P ?500\b|\bSPX\b|\bSPY\b|\bES\b|e-?mini|\bNasdaq\b|\bQQQ\b|\bNDX\b|\bNQ\b|"
         r"Dow Jones|\bDJIA\b|Russell ?2000|\bIWM\b|\bRUT\b|\bstock index\b|equity index|"
         r"index future|\bDAX\b|Euro ?Stoxx|\bFTSE\b|\bCAC ?40\b|\bIBEX\b|\bAEX\b|"
         r"\bforex\b|\bFX\b|currency pair|\bEUR ?/? ?USD\b|\bEURUSD\b|\bGBP ?/? ?USD\b|"
         r"\bUSD ?/? ?JPY\b|\bdollar index\b|\bDXY\b|"
         r"\bgold\b|\bXAU\b|\bGLD\b|"
         r"\bbitcoin\b|\bBTC\b|\bcrypto|\bethereum\b|\bETH\b")

# things that disqualify outright (either wrong asset or external data)
OFF = (r"single stock|stock selection|cross[- ]section of stock|\bfactor\b|value premium|"
       r"quality factor|profitability|book[- ]to[- ]market|\bsmall cap\b|\bvalue vs growth\b|"
       r"earnings|fundamental|\bP/E\b|balance sheet|\bREIT\b|\bbond\b|treasur|\bcredit\b|"
       r"yield curve|\bTLT\b|\bmunicipal\b|commodit(?:y|ies) (?!.*gold)|crude|natural gas|"
       r"\bsoybean\b|\bcorn\b|\bwheat\b|\bcopper\b|\bsilver\b|\blivestock\b|"
       r"asset allocation|risk parity|portfolio construction|rebalanc|\b60/40\b|"
       r"tactical asset|\bTAA\b|retirement|\bdrawdown plan\b|\bmutual fund\b|\bETF pick|"
       r"machine learning|deep learning|neural net|\bLLM\b|\bGPT\b|reinforcement learning|"
       r"random forest|\bXGBoost\b|feature engineering|\bNLP\b|"
       r"\boption(?:s)?\b|implied vol|\bIV\b|straddle|\bskew\b|\bgamma\b|\bdelta hedg|"
       r"\bVIX\b|\bVVIX\b|\bterm structure\b|volatility surface|"
       r"\bCPI\b|inflation|\bGDP\b|\bFed\b|FOMC|interest rate|unemploy|\bPMI\b|macro|"
       r"sentiment|put[- ]call|\bAAII\b|\bNAAIM\b|short interest|insider|analyst|"
       r"\bCOT\b|positioning|fund flow|breadth|advance[- ]decline")

# a hint that the post might carry an actual rule (permissive on purpose)
RULEISH = (r"\bstrateg|\bsystem\b|\brules?\b|\bbacktest|\bsignal\b|\bentry\b|\bexit\b|"
           r"\bmean reversion\b|\bmomentum\b|\btrend follow|\bbreakout\b|\bseasonal|"
           r"\bmoving average\b|\bRSI\b|\bMACD\b|\bBollinger\b|\bIBS\b|overnight|"
           r"\bgap\b|\bopening range\b|\bpattern\b|\bday trad|\bswing trad")

# clearly not a strategy post
NOISE = (r"\bpodcast\b|\binterview\b|\bbook review\b|\bconference\b|\bwebinar\b|\bcourse\b|"
         r"\bhiring\b|\bjob\b|\bnewsletter\b|\bround ?up\b|\blinks\b|\bin memoriam\b|"
         r"introduction to |\bhow to install|\btutorial\b|\bpart 1 of|\bpython package\b|"
         r"\blibrary\b|\bopen source\b|\bAPI\b|\bdata source\b|\bR package\b")


def main():
    d = pd.read_csv('scratchpad/qc_links.csv').fillna('')
    d['txt'] = (d.title + ' || ' + d.excerpt)
    n0 = len(d)

    d['asset'] = d.txt.str.count(ASSET, flags=re.I) if False else \
        d.txt.apply(lambda s: len(re.findall(ASSET, s, re.I)))
    d['off'] = d.txt.apply(lambda s: len(re.findall(OFF, s, re.I)))
    d['ruleish'] = d.txt.apply(lambda s: len(re.findall(RULEISH, s, re.I)))
    d['noise'] = d.txt.apply(lambda s: len(re.findall(NOISE, s, re.I)))

    keep = d[(d.asset >= 1) & (d.off == 0) & (d.ruleish >= 1) & (d.noise == 0)].copy()
    keep = keep.sort_values(['asset', 'ruleish'], ascending=False)
    keep.to_csv('scratchpad/qc_shortlist.csv', index=False, encoding='utf-8')

    print(f"  {n0} liens au depart")
    print(f"    dont sur un actif autorise           : {(d.asset >= 1).sum()}")
    print(f"    dont sans marqueur d'exclusion       : {((d.asset >= 1) & (d.off == 0)).sum()}")
    print(f"    dont avec un indice de regle         : {((d.asset >= 1) & (d.off == 0) & (d.ruleish >= 1)).sum()}")
    print(f"    dont hors bruit (podcast/tuto/...)   : {len(keep)}")
    print(f"\n  -> {len(keep)} articles a recuperer chez {keep.host.nunique()} blogs")
    print(f"\n  repartition par blog (top 20) :")
    for h, c in keep.host.value_counts().head(20).items():
        print(f"    {c:>4}  {h}")
    print(f"\n  echantillon de 20 titres retenus :")
    for r in keep.head(20).itertuples():
        print(f"    [{r.blog[:18]:<18}] {r.title[:88]}")


if __name__ == '__main__':
    main()
