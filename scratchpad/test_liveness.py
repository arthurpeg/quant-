"""Tests de l'alerte de liveness et du garde-fou auto_update, sans toucher au live.

Les alertes Discord sont interceptees (webhook absent du cfg de test), donc rien ne part.
On verifie: (1) la porte de seance, (2) le seuil proportionnel a l'UT, (3) le silence sur
un runner sain, (4) le cooldown, (5) le refus de sortir en 75 sans superviseur.
"""
import os
import sys
import pandas as pd

sys.path.insert(0, '.')
import edgelab.live.runner as R

FAILS = []


def check(name, got, want):
    ok = got == want
    print(f"  [{'OK ' if ok else 'ECHEC'}] {name}: got={got} want={want}")
    if not ok:
        FAILS.append(name)


class Sleeve:
    """Faux sleeve: juste ce que l'alerte lit."""
    def __init__(self, magic, tf, acted_bar):
        self.magic = magic
        self.bar_minutes = tf
        self._acted_bar = acted_bar


class Rollover:
    """Sleeve NON scannante (brique 2/3/4): pas de bar_minutes -> jamais jugee."""
    def __init__(self, magic):
        self.magic = magic


ALERTS = []
R._alert = lambda cfg, msg: ALERTS.append(msg)      # on intercepte
CFG = {}                                            # tous les defauts du code


def run(now_utc, sleeves, reset=True):
    if reset:
        R._LAST_LIVENESS_ALERT = None
    ALERTS.clear()
    R._maybe_liveness_alert(CFG, sleeves, now_utc)
    return len(ALERTS)


print('=== 1. la porte de seance US ===')
# 2026-08-17 est un lundi. 14:00 UTC = 10:00 ET -> en seance. 11:00 UTC = 07:00 ET -> hors.
stale = Sleeve(108, 15, pd.Timestamp('2026-08-17 11:00', tz='UTC'))
check('en seance (14:00 UTC) -> alerte', run(pd.Timestamp('2026-08-17 14:00', tz='UTC'), [stale]), 1)
check('avant ouverture (11:00 UTC) -> silence',
      run(pd.Timestamp('2026-08-17 11:00', tz='UTC'), [stale]), 0)
check('apres 15:55 ET (20:30 UTC) -> silence',
      run(pd.Timestamp('2026-08-17 20:30', tz='UTC'), [stale]), 0)
# samedi 2026-08-15
check('samedi -> silence', run(pd.Timestamp('2026-08-15 14:00', tz='UTC'), [stale]), 0)
# Labor Day 2026 = lundi 7 septembre -> ferie, le calendrier avance l'aplat
check('ferie US (Labor Day 2026-09-07, 18:00 UTC) -> silence',
      run(pd.Timestamp('2026-09-07 18:00', tz='UTC'), [stale]), 0)

print('\n=== 2. le seuil suit l UT (age normal = 0..UT) ===')
now = pd.Timestamp('2026-08-17 16:27', tz='UTC')
# M15 sain: derniere barre close = 16:00 (close 16:15) -> age 12 min < seuil max(20,15+5)=20
check('M15 age 12 min -> silence', run(now, [Sleeve(108, 15, pd.Timestamp('2026-08-17 16:00', tz='UTC'))]), 0)
# M15 en retard: barre de 15:30 (close 15:45) -> age 42 min > 20
check('M15 age 42 min -> alerte', run(now, [Sleeve(108, 15, pd.Timestamp('2026-08-17 15:30', tz='UTC'))]), 1)
# M5 sain: barre 16:20 (close 16:25) -> age 2 min
check('M5 age 2 min -> silence', run(now, [Sleeve(109, 5, pd.Timestamp('2026-08-17 16:20', tz='UTC'))]), 0)
# H1 a 55 min d age: normal pour du H1 (seuil max(20,60+5)=65), aurait hurle avec un seuil fixe a 20
check('H1 age 55 min -> silence (seuil 65)',
      run(now, [Sleeve(107, 60, pd.Timestamp('2026-08-17 15:15', tz='UTC'))]), 0)
check('H1 age 132 min -> alerte',
      run(now, [Sleeve(107, 60, pd.Timestamp('2026-08-17 13:15', tz='UTC'))]), 1)

print('\n=== 3. sleeve non scannante et _acted_bar absent ===')
check('sleeve sans bar_minutes -> jamais jugee', run(now, [Rollover(105), Rollover(102)]), 0)
# jamais scanne, 10 min apres l ouverture (13:40 UTC = 09:40 ET) -> dans la grace
check('jamais scanne, 10 min apres l ouverture -> silence',
      run(pd.Timestamp('2026-08-17 13:40', tz='UTC'), [Sleeve(108, 15, None)]), 0)
check('jamais scanne, 2h57 apres l ouverture -> alerte',
      run(pd.Timestamp('2026-08-17 16:27', tz='UTC'), [Sleeve(108, 15, None)]), 1)

print('\n=== 4. cooldown: une seule alerte par heure ===')
R._LAST_LIVENESS_ALERT = None
s = [Sleeve(108, 15, pd.Timestamp('2026-08-17 15:00', tz='UTC'))]
n1 = run(pd.Timestamp('2026-08-17 16:00', tz='UTC'), s, reset=False)
n2 = run(pd.Timestamp('2026-08-17 16:30', tz='UTC'), s, reset=False)   # +30 min < 60
n3 = run(pd.Timestamp('2026-08-17 17:05', tz='UTC'), s, reset=False)   # +65 min > 60
check('1re alerte', n1, 1)
check('2e a +30 min etouffee', n2, 0)
check('3e a +65 min repasse', n3, 1)

print('\n=== 5. le garde-fou auto_update ===')
os.environ.pop('EDGELAB_SUPERVISED', None)
R._UNSUPERVISED_WARNED = False
R._LAST_UPDATE_CHECK = 0.0
check('_is_supervised sans la variable', R._is_supervised(), False)
check('_check_update NON supervise -> False (ne sort pas en 75)',
      R._check_update({'auto_update': True}), False)
os.environ['EDGELAB_SUPERVISED'] = '1'
check('_is_supervised avec la variable', R._is_supervised(), True)
check('auto_update:false -> False quoi qu il arrive',
      R._check_update({'auto_update': False}), False)

print('\n=== 6. le superviseur exporte bien la variable ===')
ps1 = open('edgelab/live/run_forever.ps1', encoding='utf-8').read()
check('run_forever.ps1 pose EDGELAB_SUPERVISED', '$env:EDGELAB_SUPERVISED = "1"' in ps1, True)
check('elle est posee AVANT le lancement du runner',
      ps1.index('$env:EDGELAB_SUPERVISED') < ps1.index('launching runner'), True)

print()
if FAILS:
    print(f'{len(FAILS)} ECHEC(S): {FAILS}')
    sys.exit(1)
print('TOUS LES TESTS PASSENT')
