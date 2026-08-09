"""Couche DONNEES + SPECS pour le sweep INTRADAY metaux / indices US / indices EU.

Pourquoi ce fichier existe: `kauf_lib.py` (le moteur intraday verifie de la passe
Kaufman) lit `specs.json` depuis un repertoire temporaire d'une session precedente
qui a ete purge, et ses pulls M15 ont disparu avec. On reconstruit les deux depuis
le repo lui-meme + le pont MT5 vivant, sans rien changer au moteur.

SPECS
-----
`point` vient de MT5 (`symbol_info`), c'est la seule source d'autorite.
`spread_now` est le PLANCHER applique au spread historique du flux. On ne prend PAS
le spread instantane de MT5: hors seance un indice cote 5 a 10x son spread de
seance, ce qui rendrait tout le backtest absurdement pessimiste. On prend la
**mediane du spread du flux lui-meme sur les 6 derniers mois, restreinte a la
fenetre de seance** de l'actif — honnete, auto-contenue, et comparable d'un actif
a l'autre. Le spread instantane est enregistre a cote, pour information.

DONNEES
-------
Deux origines, selon ce que le cache du projet contient reellement:
  * 5 symboles ont du M1 natif (XAUUSD, NAS100, US500, US30, GER40) -> on
    reechantillonne en M5/M15/M30, ce qui donne ~8 ans d'historique;
  * 6 symboles n'ont que du M10 natif (XAGUSD, US2000, FRA40, UK100, SWI20,
    NETH25) -> on les prend tels quels.
Dans les deux cas les barres sont estampillees a l'heure SERVEUR par MT5 mais
etiquetees UTC: `kauf_lib.to_true_utc` les reinterprete avant toute logique de
seance (convention du projet, cf. edgelab/intraday/orb.py).
"""
import os, json, sys
sys.path.insert(0, 'scratchpad')
import numpy as np
import pandas as pd

OUT = os.path.join('scratchpad', '_inx')
os.makedirs(OUT, exist_ok=True)

METAL = ['XAUUSD', 'XAGUSD']
US_IDX = ['NAS100', 'US500', 'US30', 'US2000']
EU_IDX = ['GER40', 'FRA40', 'UK100', 'SWI20', 'NETH25']
ALL = METAL + US_IDX + EU_IDX

# de quoi on dispose reellement dans data_cache_mt5/
M1_SYMS = ['XAUUSD', 'NAS100', 'US500', 'US30', 'GER40']
M10_SYMS = ['XAGUSD', 'US2000', 'FRA40', 'UK100', 'SWI20', 'NETH25']

# fenetre de seance par classe, pour mediane de spread ET pour la logique de sortie
# (identique a kauf_lib.SESSION, etendue aux deux indices EU absents de sa table)
SESSION = {
    'XAUUSD': ('Europe/London', '08:00', '20:55'), 'XAGUSD': ('Europe/London', '08:00', '20:55'),
    'NAS100': ('America/New_York', '09:30', '15:55'), 'US500': ('America/New_York', '09:30', '15:55'),
    'US30': ('America/New_York', '09:30', '15:55'), 'US2000': ('America/New_York', '09:30', '15:55'),
    'GER40': ('Europe/Berlin', '09:00', '17:25'), 'FRA40': ('Europe/Paris', '09:00', '17:25'),
    'NETH25': ('Europe/Amsterdam', '09:00', '17:25'), 'SWI20': ('Europe/Zurich', '09:00', '17:25'),
    'UK100': ('Europe/London', '08:00', '16:25'),
}
SERVER_TZ = 'Europe/Athens'


def to_true_utc(idx):
    """MT5 estampille a l'heure serveur mais etiquette UTC -> on reinterprete."""
    naive = idx.tz_localize(None) if idx.tz is not None else idx
    return (naive.tz_localize(SERVER_TZ, ambiguous='NaT', nonexistent='NaT')
                 .tz_convert('UTC'))


def _read(sym, tf):
    for ext, rd in (('parquet', pd.read_parquet), ('csv', pd.read_csv)):
        p = os.path.join('data_cache_mt5', f'{sym}_{tf}.{ext}')
        if os.path.exists(p):
            d = rd(p)
            d.columns = [c.lower() for c in d.columns]
            return d
    return None


def bars(sym, tf):
    """Barres en VRAI UTC pour (sym, tf). tf in {M5,M10,M15,M30}."""
    if tf == 'M10':
        d = _read(sym, 'M10')
        if d is None:
            return None
    else:
        d = _read(sym, 'M1')
        if d is None:
            return None
        rule = {'M5': '5min', 'M15': '15min', 'M30': '30min'}[tf]
        d['time'] = pd.to_datetime(d['time'], utc=True)
        agg = {'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last'}
        if 'spread' in d:
            agg['spread'] = 'median'
        if 'tick_volume' in d:
            agg['tick_volume'] = 'sum'
        d = (d.set_index('time').resample(rule, label='left', closed='left')
               .agg(agg).dropna(subset=['open']).reset_index())
    d['time'] = pd.to_datetime(d['time'], utc=True)
    idx = to_true_utc(pd.DatetimeIndex(d['time']))
    d = d.loc[idx.notna()].copy()
    d.index = idx[idx.notna()]
    return d.sort_index().drop(columns=['time'])


def session_mask(d, sym):
    tz, t0, t1 = SESSION[sym]
    loc = d.index.tz_convert(tz)
    mins = np.asarray(loc.hour * 60 + loc.minute)
    hm = lambda s: int(s[:2]) * 60 + int(s[3:])
    return (mins >= hm(t0)) & (mins <= hm(t1)) & (np.asarray(loc.dayofweek) < 5)


def build_specs():
    """point depuis MT5; spread_now = mediane EN SEANCE du flux sur 6 mois."""
    import MetaTrader5 as mt5
    if not mt5.initialize():
        raise RuntimeError(f'MT5 init failed: {mt5.last_error()}')
    specs = {}
    for s in ALL:
        info = mt5.symbol_info(s)
        if info is None:
            mt5.symbol_select(s, True)
            info = mt5.symbol_info(s)
        d = bars(s, 'M10' if s in M10_SYMS else 'M15')
        floor = np.nan
        if d is not None and 'spread' in d:
            recent = d[d.index >= d.index.max() - pd.Timedelta(days=182)]
            m = session_mask(recent, s)
            if m.sum() > 100:
                floor = float(np.nanmedian(recent['spread'].to_numpy()[m]))
        specs[s] = dict(point=float(info.point), digits=int(info.digits),
                        spread_live=float(info.spread),
                        spread_now=float(floor if np.isfinite(floor) else info.spread),
                        contract=float(info.trade_contract_size))
    mt5.shutdown()
    json.dump(specs, open(os.path.join(OUT, 'specs.json'), 'w'), indent=1)
    return specs


if __name__ == '__main__':
    sp = build_specs()
    print(f"{'sym':8s} {'point':>8s} {'spr live':>9s} {'spr seance':>11s} {'contrat':>8s}")
    for s, v in sp.items():
        print(f"{s:8s} {v['point']:8.5f} {v['spread_live']:9.1f} {v['spread_now']:11.1f} "
              f"{v['contract']:8.1f}")
    print()
    print(f"{'sym':8s} {'tf':4s} {'barres':>9s} {'debut':12s} {'fin':12s} {'bar/seance':>10s}")
    for s in ALL:
        for tf in (['M10'] if s in M10_SYMS else ['M5', 'M15', 'M30']):
            d = bars(s, tf)
            if d is None:
                print(f"{s:8s} {tf:4s}   ABSENT"); continue
            m = session_mask(d, s)
            ds = d[m]
            per = ds.groupby(ds.index.tz_convert(SESSION[s][0]).normalize()).size()
            print(f"{s:8s} {tf:4s} {len(ds):9d} {str(ds.index.min().date()):12s} "
                  f"{str(ds.index.max().date()):12s} {per.median():10.0f}")
