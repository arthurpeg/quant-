"""Pull M1 for the FX majors missing from the cache (London breakout test)."""
import sys; sys.path.insert(0, '.'); sys.stdout.reconfigure(encoding='utf-8')
from edgelab.data.mt5_live import pull_and_cache
import pandas as pd

for sym in ['GBPUSD', 'AUDUSD', 'USDCAD', 'USDCHF']:
    try:
        p = pull_and_cache(sym, 'M1', '2019-01-01')
        df = pd.read_parquet(p)
        print(f'{sym} M1: {len(df)} barres {df["time"].iloc[0]} -> {df["time"].iloc[-1]}', flush=True)
    except Exception as e:
        print(f'{sym} M1 ERREUR: {type(e).__name__} {e}', flush=True)
print('TERMINE', flush=True)
