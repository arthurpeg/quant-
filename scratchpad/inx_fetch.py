"""RAPATRIEMENT AUTOMATIQUE DES TIMEFRAMES depuis Pepperstone MT5.

Mandat utilisateur (2026-08-09): *"si une strategie necessite une time frame qu'on n'a
pas encore recuperee via pepperstone mt5, je veux que tu recuperes les timeframes ...
ceci est valable pour tous les travaux en cours"*.

C'est directement un multiplicateur de rendement pour le portage MQL: `Ctx._tf` du
transpileur leve `Unsupported('no <TF> bars for <SYM>')` des qu'une condition appelle un
indicateur sur un timeframe absent du cache (`iMA(NULL, PERIOD_H4, ...)` est la norme, pas
l'exception — mesure de la passe MQL: 1099 conditions d'entree sur 500 fichiers appellent
un autre timeframe que celui du graphique). Chaque TF manquant rejetait donc des scripts
parfaitement traduisibles.

CE QUE CE MODULE GARANTIT
  * `ensure(sym, tf)` rend un chemin de parquet utilisable, en le TELECHARGEANT si besoin;
  * les barres sont ecrites dans `data_cache_mt5/` — le cache du projet — donc tout
    travail ulterieur en beneficie sans re-telecharger;
  * la fenetre est celle du projet (2018-01-01 -> maintenant), decoupee en tranches pour
    rester sous la limite de barres du terminal;
  * **les timestamps sont laisses tels que MT5 les rend** (heure serveur etiquetee UTC),
    exactement comme les parquets deja presents. La reinterpretation en vrai UTC est faite
    PLUS TARD et une seule fois, par `inx_data.to_true_utc` / `kauf_lib.to_true_utc`. La
    faire ici la ferait deux fois et decalerait les seances de 2-3 h en silence.
"""
import os, sys, time
import numpy as np
import pandas as pd

CACHE = 'data_cache_mt5'
START = pd.Timestamp('2018-01-01', tz='UTC')
_MT5 = None

# Tous les timeframes qu'un script MQL peut demander (PERIOD_*).
TF_MT5 = {
    'M1': 1, 'M2': 2, 'M3': 3, 'M4': 4, 'M5': 5, 'M6': 6, 'M10': 10, 'M12': 12,
    'M15': 15, 'M20': 20, 'M30': 30, 'H1': 16385, 'H2': 16386, 'H3': 16387,
    'H4': 16388, 'H6': 16390, 'H8': 16392, 'H12': 16396, 'D1': 16408,
    'W1': 32769, 'MN1': 49153,
}
# minutes par barre, pour dimensionner les tranches de telechargement
TF_MIN = {'M1': 1, 'M2': 2, 'M3': 3, 'M4': 4, 'M5': 5, 'M6': 6, 'M10': 10, 'M12': 12,
          'M15': 15, 'M20': 20, 'M30': 30, 'H1': 60, 'H2': 120, 'H3': 180, 'H4': 240,
          'H6': 360, 'H8': 480, 'H12': 720, 'D1': 1440, 'W1': 10080, 'MN1': 43200}


def _mt5():
    global _MT5
    if _MT5 is None:
        import MetaTrader5 as mt5
        if not mt5.initialize():
            raise RuntimeError(f'MT5 initialize failed: {mt5.last_error()}')
        _MT5 = mt5
    return _MT5


def path(sym, tf):
    return os.path.join(CACHE, f'{sym}_{tf}.parquet')


def have(sym, tf):
    p = path(sym, tf)
    if os.path.exists(p):
        return p
    c = os.path.join(CACHE, f'{sym}_{tf}.csv')
    return c if os.path.exists(c) else None


def fetch(sym, tf, start=START, verbose=True):
    """Telecharge (sym, tf) depuis MT5 et ecrit le parquet. Rend le chemin ou None."""
    if tf not in TF_MT5:
        return None
    mt5 = _mt5()
    if mt5.symbol_info(sym) is None:
        mt5.symbol_select(sym, True)
        if mt5.symbol_info(sym) is None:
            if verbose:
                print(f'    [fetch] symbole inconnu du broker: {sym}')
            return None
    per = TF_MT5[tf]
    end = pd.Timestamp.now('UTC') + pd.Timedelta(days=1)
    # tranches de ~40k barres pour rester sous la limite du terminal
    step = pd.Timedelta(minutes=TF_MIN[tf] * 40000)
    chunks, t = [], start
    while t < end:
        t2 = min(t + step, end)
        r = mt5.copy_rates_range(sym, per, t.to_pydatetime(), t2.to_pydatetime())
        if r is not None and len(r):
            chunks.append(pd.DataFrame(r))
        t = t2
    if not chunks:
        if verbose:
            print(f'    [fetch] aucune barre rendue pour {sym} {tf}')
        return None
    d = pd.concat(chunks, ignore_index=True).drop_duplicates(subset='time')
    d['time'] = pd.to_datetime(d['time'], unit='s', utc=True)   # tel quel: heure SERVEUR
    d = d.sort_values('time').reset_index(drop=True)
    keep = [c for c in ('time', 'open', 'high', 'low', 'close', 'tick_volume', 'spread',
                        'real_volume') if c in d.columns]
    d = d[keep]
    os.makedirs(CACHE, exist_ok=True)
    p = path(sym, tf)
    d.to_parquet(p, index=False)
    if verbose:
        print(f'    [fetch] {sym} {tf}: {len(d)} barres '
              f'{str(d["time"].iloc[0])[:10]} -> {str(d["time"].iloc[-1])[:10]}')
    return p


def ensure(sym, tf, verbose=True):
    """Le chemin des barres (sym, tf), en telechargeant si le cache ne les a pas."""
    p = have(sym, tf)
    if p:
        return p
    return fetch(sym, tf, verbose=verbose)


if __name__ == '__main__':
    # rapatrie tout ce dont l'univers a besoin, tous timeframes intraday utiles
    UNI = ['NAS100', 'US500', 'US30', 'GER40', 'FRA40', 'XAUUSD']
    TFS = sys.argv[1].split(',') if len(sys.argv) > 1 else \
        ['M1', 'M5', 'M10', 'M15', 'M30', 'H1', 'H4', 'D1']
    t0 = time.time()
    print(f'{"symbole":9s} ' + ' '.join(f'{t:>8s}' for t in TFS))
    for s in UNI:
        cells = []
        for tf in TFS:
            pre = have(s, tf)
            p = ensure(s, tf, verbose=False)
            cells.append('  ok' if pre else ('FETCH' if p else '  --'))
        print(f'{s:9s} ' + ' '.join(f'{c:>8s}' for c in cells), flush=True)
    print(f'\n[{time.time()-t0:.0f}s]  ok = deja en cache, FETCH = telecharge maintenant, '
          '-- = indisponible chez le broker')
