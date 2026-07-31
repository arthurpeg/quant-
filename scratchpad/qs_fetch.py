"""Fetch + triage the QuantifiedStrategies.com free-strategy index (user request).

User filters:
  * fully mechanical rules (entry + exit, ideally an explicit SL/TP)
  * NO external data (VIX, put/call, sentiment, macro, fundamentals, breadth, ...)
  * assets limited to US & EU INDICES, FOREX, GOLD, CRYPTO

Pass 1 (this file) is mechanical: pull every article linked from the index, strip it to
text, and score it on asset / external-data / rule-explicitness keywords. Pass 2 is a
human (well, LLM) read of whatever survives — keyword triage decides what to READ, never
what to keep.

    python scratchpad/qs_fetch.py          # fetch (cached) + write the triage table
"""
import sys; sys.stdout.reconfigure(encoding='utf-8')

import re
import time
from pathlib import Path

import pandas as pd
import requests

INDEX = "https://www.quantifiedstrategies.com/trading-strategies-free/"
OUT = Path("scratchpad/qs_pages"); OUT.mkdir(parents=True, exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) research/1.0"}

# --- what counts as one of the user's asset classes -------------------------------
ASSET = {
    "us_index": r"\bS&P ?500\b|\bSPY\b|\bSPX\b|\bES\b futures|e-?mini|\bNasdaq\b|\bQQQ\b|\bNQ\b|"
                r"\bDow Jones\b|\bDJIA\b|\bDIA\b|\bRussell 2000\b|\bIWM\b|\bRTY\b|MidCap",
    "eu_index": r"\bDAX\b|Euro ?Stoxx|\bFTSE\b|\bCAC\b|\bIBEX\b|\bAEX\b|\bSMI\b|Bund",
    "forex":    r"\bforex\b|\bEUR ?/? ?USD\b|\bGBP ?/? ?JPY\b|\bEUR ?/? ?JPY\b|\bUSD ?/? ?JPY\b|"
                r"\bcurrency pair\b|\bFX\b",
    "gold":     r"\bgold\b|\bGLD\b|\bXAU\b|\bGC\b futures",
    "crypto":   r"\bbitcoin\b|\bBTC\b|\bcrypto|\bethereum\b|\bETH\b",
}
# assets that DISQUALIFY when they are the subject (not just mentioned in passing)
OFF_ASSET = (r"\bTLT\b|\btreasur|\bbond\b|\bNIFTY\b|\bsector\b|\bXL[PUEVFYKIB]\b|penny stock|"
             r"\bsilver\b|\bplatinum\b|\bcorn\b|\bcocoa\b|\bsugar\b|heating oil|\bcrude\b|\boil\b|"
             r"\blumber\b|\bcopper\b|\bREIT\b|\bAAPL\b|\bNVDA\b|\bAMZN\b|\bMETA\b|mutual fund|"
             r"\bVanguard\b|\bChina\b|\bFXI\b|\bBrazil\b|\bIndia\b|\bItaly\b|\bAustralia")
EXTERNAL = (r"\bVIX\b|put[- ]call|\bNAAIM\b|\bAAII\b|Investors Intelligence|\bTRIN\b|"
            r"advance[- ]decline|short interest|\bCPI\b|inflation rate|\bPMI\b|\bISM\b|"
            r"non[- ]farm|\bNFP\b|interest rate|\bFed\b funds|earnings report|\bP/E\b|"
            r"book value|F-Score|fundamental|consumer confidence|\bMOVE index\b|open interest|"
            r"COT report|sentiment surve")
RULES = r"trading rules|buy (?:when|if|at)|sell (?:when|if|at)|entry|we go long|go short|" \
        r"\benter\b|\bexit\b"
SLTP = r"stop[- ]loss|\bstop\b|take[- ]profit|profit target|\btarget\b|trailing"


def links_from_index() -> list[str]:
    html = requests.get(INDEX, headers=UA, timeout=30).text
    urls = re.findall(r'href="(https://www\.quantifiedstrategies\.com/[a-z0-9\-/]+/?)"', html)
    bad = ("/tag/", "/category/", "/author/", "/lessons/", "/courses/", "/about", "/contact",
           "/privacy", "/terms", "/disclaimer", "/blog/", "/shop", "/membership", "/course")
    keep = {u for u in urls if not any(b in u for b in bad)
            and u.rstrip("/") != INDEX.rstrip("/")
            and len(u.rstrip("/").split("/")[-1]) > 8}
    return sorted(keep)


def slug(u):  return u.rstrip("/").split("/")[-1]


def fetch(u: str) -> str:
    f = OUT / f"{slug(u)}.txt"
    if f.exists():
        return f.read_text(encoding="utf-8", errors="ignore")
    try:
        html = requests.get(u, headers=UA, timeout=30).text
    except Exception as exc:
        print(f"    ! {slug(u)}: {type(exc).__name__}"); return ""
    html = re.sub(r"(?is)<(script|style|nav|footer|header|form).*?</\1>", " ", html)
    txt = re.sub(r"(?s)<[^>]+>", " ", html)
    txt = re.sub(r"&#\d+;|&[a-z]+;", " ", txt)
    txt = re.sub(r"[ \t]+", " ", txt)
    txt = re.sub(r"\n\s*\n+", "\n", txt)
    f.write_text(txt, encoding="utf-8")
    time.sleep(0.7)                     # be polite
    return txt


def main():
    urls = links_from_index()
    print(f"  {len(urls)} article URLs from the index")
    rows = []
    for i, u in enumerate(urls, 1):
        t = fetch(u)
        if len(t) < 800:
            continue
        low = t.lower()
        hits = {k: len(re.findall(v, t, re.I)) for k, v in ASSET.items()}
        rows.append(dict(
            slug=slug(u), url=u, chars=len(t),
            **{f"a_{k}": v for k, v in hits.items()},
            asset_any=sum(hits.values()),
            off=len(re.findall(OFF_ASSET, t, re.I)),
            ext=len(re.findall(EXTERNAL, t, re.I)),
            rules=len(re.findall(RULES, low)),
            sltp=len(re.findall(SLTP, low)),
            has_table=int("trading rules" in low or "the rules are" in low),
        ))
        if i % 25 == 0:
            print(f"    {i}/{len(urls)} fetched")
    df = pd.DataFrame(rows)
    df.to_csv("scratchpad/qs_triage.csv", index=False, encoding="utf-8")
    print(f"\n  {len(df)} pages with usable text -> scratchpad/qs_triage.csv")
    elig = df[(df.asset_any >= 2) & (df.ext <= 2) & (df.rules >= 3)]
    print(f"  pre-filter (asset>=2, external<=2, rule-words>=3): {len(elig)} to READ")


if __name__ == "__main__":
    main()
