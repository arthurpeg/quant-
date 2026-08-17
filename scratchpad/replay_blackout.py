"""Rejoue les DECISIONS LIVE des sleeves intraday sur les deux fenetres ou le runner
etait absent, avec les MEMES fonctions que `runner.py` appelle (`edgelab.live.signals`)
et les memes parametres que `edgelab.live.strategies` instancie.

Fenetres d'absence (UTC), etablies dans runner.log du VPS (CEST = UTC+2) :
    vendredi 2026-08-14 : 13:30 -> 15:17:20   (banniere de demarrage a 17:17:20 CEST)
    lundi    2026-08-17 : 13:30 -> 14:32:50   (banniere de demarrage a 16:32:50 CEST)

Lecture SEULE : le broker est construit avec live_trading force a False, donc aucun
ordre ne peut partir. Les barres viennent du meme flux Pepperstone que le VPS.
"""
import sys
import pandas as pd

sys.path.insert(0, '.')
pd.set_option('display.width', 200)

from edgelab.live import signals as S
from edgelab.live.broker import Broker
from edgelab.live.strategies import (NasOrbStrategy, HmaStochStrategy, TwoLegFadeStrategy,
                                     NasIbsStrategy, _mins)
from edgelab.live.runner import _load_live_cfg

BLACKOUTS = {
    pd.Timestamp('2026-08-14').date(): (pd.Timestamp('2026-08-14 13:30', tz='UTC'),
                                        pd.Timestamp('2026-08-14 15:17:20', tz='UTC')),
    pd.Timestamp('2026-08-17').date(): (pd.Timestamp('2026-08-17 13:30', tz='UTC'),
                                        pd.Timestamp('2026-08-17 14:32:50', tz='UTC')),
}


def tag(ts, day):
    lo, hi = BLACKOUTS[day]
    return '  <<< PENDANT LE TROU' if lo <= ts <= hi else ''


cfg = _load_live_cfg()
cfg = dict(cfg)
cfg['live_trading'] = False          # lecture seule, aucun ordre possible
br = Broker(cfg)
br.connect()
print(f'broker: server={br.server} demo={br.is_demo} live={br.live}\n')

# ---------------------------------------------------------------- BRIQUE 1 (M1)
print('=' * 100)
print('BRIQUE 1 — NAS100 ORB regime bas (M1) — `nas_orb_scan`, un trade/jour max')
print('=' * 100)
b1 = NasOrbStrategy(cfg)
p1 = b1.p
open_m, cut_m, close_m = _mins(p1.session_open), _mins(p1.entry_cutoff), _mins(p1.session_close)
print(f'  fenetre d entree {p1.session_open}-{p1.entry_cutoff} ET | regime={p1.regime_mode} '
      f'| k_break={p1.k_break} k_stop={p1.k_stop}')
m1 = br.get_bars(b1.logical, 'M1', 6000)
d1raw = br.get_bars_raw(b1.logical, 'D1', 60)
atr_map = S.prev_day_atrs(d1raw, p1)
loc1 = m1.index.tz_convert(p1.tz)
for day in BLACKOUTS:
    mask = (loc1.normalize().date == day) & \
           ((loc1.hour * 60 + loc1.minute) >= open_m) & ((loc1.hour * 60 + loc1.minute) <= close_m)
    sess = m1[mask][['open', 'high', 'low', 'close']]
    atrs = atr_map.get(day)
    print(f'\n  {day} : {len(sess)} barres M1 de seance')
    if atrs is None:
        print('    pas d ATR de veille -> le driver aurait skip')
        continue
    a14, a3, a20 = atrs
    print(f'    ATR14={a14:.2f} ATR3={a3:.2f} ATR20={a20:.2f} '
          f'-> regime bas {"OK" if S.nas_regime_ok(a3, a20, p1) else "REFUSE (pas de trade possible)"}')
    if len(sess) < 2:
        continue
    res = S.nas_orb_scan(sess, a14, a3, a20, p1)
    if res is None:
        print('    AUCUN breakout sur toute la seance -> aucun trade a manquer')
        continue
    ci, plan = res
    ct, ft = sess.index[ci], sess.index[min(ci + 1, len(sess) - 1)]
    print(f'    BREAKOUT : confirme a {ct} (close={sess["close"].iloc[ci]:.2f}), '
          f'fill au next open {ft} = {sess["open"].iloc[min(ci+1, len(sess)-1)]:.2f}')
    print(f'    plan: dir={plan.direction:+d} 1R={plan.sl_dist:.2f} pts reason={plan.reason}{tag(ft, day)}')

# ---------------------------------------------------------------- HMASTO (M15)
print('\n' + '=' * 100)
print('HMASTO — NAS100 M15 @0.5R — `hma_scan`, rejoue barre par barre')
print('=' * 100)
h = HmaStochStrategy(cfg)
ph = h.p
open_mh, cut_mh = _mins(ph.session_open), _mins(ph.entry_cutoff)
print(f'  fenetre d entree {ph.session_open}-{ph.entry_cutoff} ET (+15 min de tolerance driver)')
m15 = br.get_bars(h.logical, 'M15', 3000)
for day in BLACKOUTS:
    locm = m15.index.tz_convert(ph.tz)
    idx = [i for i in range(len(m15)) if locm[i].date() == day]
    hits = []
    for i in idx:
        ts = m15.index[i]
        et = ts.tz_convert(ph.tz)
        minute = et.hour * 60 + et.minute          # minute de la CLOTURE de la barre
        if not (open_mh <= minute <= cut_mh + 15):
            continue
        r = S.hma_scan(m15.iloc[:i + 1], ph, h.logical)
        if r is not None:
            _, plan = r
            hits.append((ts + pd.Timedelta(minutes=15), plan))
    print(f'\n  {day} : {len(idx)} barres M15 dans la seance, {len(hits)} signal(aux)')
    for ts, plan in hits:
        print(f'    signal barre close {ts} -> dir={plan.direction:+d} 1R={plan.sl_dist:.2f} '
              f'{plan.reason}{tag(ts, day)}')

# ---------------------------------------------------------------- TLF (M5)
print('\n' + '=' * 100)
print('TLF — NAS100 (109) + US500 (110), M5 @0.5R — `tlf_scan`, rejoue barre par barre')
print('=' * 100)
for sym in cfg.get('tlf_symbols', ['NAS100', 'US500']):
    t = TwoLegFadeStrategy(cfg, sym)
    pt = t.p
    open_mt, cut_mt = _mins(pt.session_open), _mins(pt.entry_cutoff)
    m5 = br.get_bars(t.logical, 'M5', 6000)
    print(f'\n  --- {sym} (magic {t.magic}) | fenetre {pt.session_open}-{pt.entry_cutoff} ET '
          f'| {len(m5)} barres M5 tirees')
    locm = m5.index.tz_convert(pt.tz)
    for day in BLACKOUTS:
        idx = [i for i in range(len(m5)) if locm[i].date() == day]
        hits = []
        for i in idx:
            ts = m5.index[i]
            et = ts.tz_convert(pt.tz)
            minute = et.hour * 60 + et.minute
            if not (open_mt <= minute <= cut_mt + 5):
                continue
            r = S.tlf_scan(m5.iloc[:i + 1], pt, t.logical)
            if r is not None:
                _, plan = r
                hits.append((ts + pd.Timedelta(minutes=5), plan))
        print(f'    {day} : {len(idx)} barres M5 dans la seance, {len(hits)} ordre(s) STOP arme(s)')
        for ts, plan in hits:
            print(f'      arme barre close {ts} -> SELL STOP @ {plan.trigger:.2f} '
                  f'1R={plan.sl_dist:.2f}{tag(ts, day)}')

# ---------------------------------------------------------------- BRIQUE 4 (D1)
print('\n' + '=' * 100)
print('BRIQUE 4 — NAS100 IBS (D1) — `ibs_state` au rollover 00:00 serveur')
print('=' * 100)
i4 = NasIbsStrategy(cfg)
d1 = br.get_bars(i4.logical, 'D1', 120)
for day in BLACKOUTS:
    sub = d1[d1.index.tz_convert('UTC').normalize() <= pd.Timestamp(day, tz='UTC')]
    if not len(sub):
        continue
    st = S.ibs_state(sub, i4.p)
    last = sub.index[-1]
    ibs_val = ((sub['close'] - sub['low']) / (sub['high'] - sub['low']).replace(0, float('nan'))).iloc[-1]
    print(f'  cloture {last.date()} : IBS={ibs_val:.3f} -> entry={st.is_entry} exit={st.is_exit} '
          f'1R={st.sl_dist:.2f}')

br.disconnect()
print('\n(brique 2 XAUUSD turn-of-month : hors fenetre calendaire a la mi-aout ; brique 3 crypto : '
      'les deux positions du 29/07 sont ENCORE ouvertes, donc aucune entree possible de toute facon)')
