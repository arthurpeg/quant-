"""Stage 2 — turn 836 harvested strategy files into testable (family, parameters) specs.

No transpiling: reading arbitrary Pine/MQL/Python and executing it faithfully is not
realistic. What IS realistic, and honest, is to read out of each file
  * which indicator families it keys on, with the parameters it declares,
  * the numeric thresholds it compares them to,
  * its stop / ROI / trailing settings when the language declares them,
and then to backtest the DISTINCT (family, parameter) combinations on our own engine.

That is a screen of the ideas the corpus contains, not a re-execution of each robot — and
the report says so. Duplicates collapse hard: 836 files carry far fewer distinct ideas.

    python scratchpad/code_parse.py
"""
import sys; sys.stdout.reconfigure(encoding='utf-8')

import json
import re
from collections import Counter

import pandas as pd

IDX = json.loads(open('scratchpad/code_index.json', encoding='utf-8').read())

# family -> regex that finds the indicator AND (where possible) its period
FAM = {
    'rsi':        r'(?:ta\.)?rsi\s*[\(<]\s*(?:[^,)\n]{0,30}?,\s*)?(\d{1,3})|RSIPeriod\s*=\s*(\d{1,3})|rsi_?(?:period|length)\D{0,6}(\d{1,3})',
    'ema':        r'(?:ta\.)?ema\s*\(\s*[^,)\n]{0,30},\s*(\d{1,4})|iMA\([^)]*MODE_EMA[^)]*\)|ema_?(?:period|length)\D{0,6}(\d{1,4})',
    'sma':        r'(?:ta\.)?sma\s*\(\s*[^,)\n]{0,30},\s*(\d{1,4})|MODE_SMA|sma_?(?:period|length)\D{0,6}(\d{1,4})',
    'macd':       r'macd',
    'bbands':     r'bollinger|bbands|ta\.bb\b|BandsPeriod',
    'stoch':      r'stoch(?:astic)?',
    'atr':        r'(?:ta\.)?atr\s*\(|ATRPeriod|atr_?(?:period|length)',
    'adx':        r'\badx\b|iADX',
    'cci':        r'\bcci\b|iCCI',
    'donchian':   r'donchian|highest\s*\(\s*high|lowest\s*\(\s*low|iHighest|iLowest',
    'ichimoku':   r'ichimoku|tenkan|kijun',
    'williams':   r'willr|williams.?%?r|iWPR',
    'mfi':        r'\bmfi\b',
    'obv':        r'\bobv\b',
    'psar':       r'\bsar\b|parabolic',
    'supertrend': r'supertrend',
    'keltner':    r'keltner',
    'vwap':       r'\bvwap\b',
    'ibs':        r'\bibs\b|internal.?bar.?strength',
    'heikin':     r'heikin|heiken',
    'pivot':      r'\bpivot\b',
    'fib':        r'fibonacci|\bfib\b',
    'ml':         r'sklearn|tensorflow|torch|xgboost|lightgbm|RandomForest|neural',
}
# things that disqualify under the user's filters
EXTERNAL = r'\bvix\b|fear.?greed|funding.?rate|open.?interest|orderbook|order.?book|' \
           r'social|twitter|sentiment|on.?chain|blockchain\.info|glassnode|cryptoquant|' \
           r'news|earnings|macro|\bcpi\b|\bfomc\b'
# freqtrade declares its risk explicitly
FT_STOP = r'stoploss\s*=\s*(-?\d*\.?\d+)'
FT_TF = r"timeframe\s*=\s*['\"]([0-9]+[mhd])['\"]"
FT_ROI = r'minimal_roi'


def main():
    rows = []
    for e in IDX:
        t = open(e['file'], encoding='utf-8', errors='ignore').read()
        low = t.lower()
        fams = [f for f, rx in FAM.items() if re.search(rx, low, re.I)]
        stop = re.search(FT_STOP, t)
        tf = re.search(FT_TF, t)
        rows.append(dict(
            lang=e['lang'], repo=e['repo'], path=e['path'], chars=e['chars'],
            fams='|'.join(sorted(fams)), n_fam=len(fams),
            external=bool(re.search(EXTERNAL, low)),
            ml='ml' in fams,
            stoploss=float(stop.group(1)) if stop else None,
            timeframe=tf.group(1) if tf else '',
            has_roi=bool(re.search(FT_ROI, t)),
        ))
    d = pd.DataFrame(rows)
    d.to_csv('scratchpad/code_specs.csv', index=False, encoding='utf-8')

    print(f"  {len(d)} fichiers de strategie parses\n")
    print("  FAMILLES DE SIGNAL PRESENTES (un fichier peut en avoir plusieurs) :")
    c = Counter(f for s in d.fams for f in s.split('|') if f)
    for f, n in c.most_common():
        print(f"    {f:<12} {n:>4}  ({n/len(d)*100:.0f}% des fichiers)")

    print(f"\n  FILTRES UTILISATEUR :")
    print(f"    utilisent des donnees EXTERNES (VIX, funding, on-chain, sentiment...) : {d.external.sum()}")
    print(f"    utilisent du MACHINE LEARNING (regle non figee)                       : {d.ml.sum()}")
    elig = d[(~d.external) & (~d.ml) & (d.n_fam > 0)]
    print(f"    -> eligibles                                                          : {len(elig)}")

    print(f"\n  TIMEFRAME declare (freqtrade) :")
    for k, v in elig[elig.timeframe != ''].timeframe.value_counts().head(8).items():
        print(f"    {k:<6} {v}")

    print(f"\n  IDEES DISTINCTES (combinaison de familles) — c'est le vrai nombre a tester :")
    combos = elig.fams.value_counts()
    print(f"    {len(combos)} combinaisons distinctes pour {len(elig)} fichiers "
          f"(facteur de duplication x{len(elig)/max(len(combos),1):.1f})")
    for k, v in combos.head(18).items():
        print(f"    {v:>4}x  {k}")
    elig.to_csv('scratchpad/code_eligible.csv', index=False, encoding='utf-8')


if __name__ == '__main__':
    main()
