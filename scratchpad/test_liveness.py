"""Tests de l'alerte de liveness et du garde-fou auto_update, sans toucher au live.

Les alertes Discord sont interceptees, donc rien ne part.

Couvre notamment les DEUX FAUX POSITIFS vus a la premiere mise en service le 2026-08-17 :
  * une sleeve qui PORTE une position ne scanne pas -> ne doit jamais etre accusee ;
  * un processus qui vient de demarrer a `_acted_bar = None` -> la grace se compte depuis
    LE DEMARRAGE, pas depuis l'ouverture de la seance.
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
    def __init__(self, magic, tf, acted_bar):
        self.magic = magic
        self.bar_minutes = tf
        self._acted_bar = acted_bar


class Rollover:
    """Sleeve NON scannante (brique 2/3/4): pas de bar_minutes -> jamais jugee."""
    def __init__(self, magic):
        self.magic = magic


class FakeBroker:
    """`open_position(magic)` non-None = la sleeve porte une position."""
    def __init__(self, in_position=()):
        self.in_position = set(in_position)

    def open_position(self, magic):
        return object() if magic in self.in_position else None


class BrokenBroker:
    def open_position(self, magic):
        raise RuntimeError('MT5 hoquette')


ALERTS = []
R._alert = lambda cfg, msg: ALERTS.append(msg)
CFG = {}
FLAT = FakeBroker()
# par defaut on se place LONGTEMPS apres le demarrage, pour ne pas dependre de la grace
R._STARTED_AT = pd.Timestamp('2026-08-17 12:00', tz='UTC')


def run(now_utc, sleeves, broker=FLAT, reset=True):
    if reset:
        R._LAST_LIVENESS_ALERT = None
    ALERTS.clear()
    R._maybe_liveness_alert(broker, CFG, sleeves, now_utc)
    return len(ALERTS)


print('=== 1. la porte de seance US ===')
stale = Sleeve(108, 15, pd.Timestamp('2026-08-17 11:00', tz='UTC'))
check('en seance (14:00 UTC) -> alerte', run(pd.Timestamp('2026-08-17 14:00', tz='UTC'), [stale]), 1)
check('avant ouverture (11:00 UTC) -> silence',
      run(pd.Timestamp('2026-08-17 11:00', tz='UTC'), [stale]), 0)
check('apres 15:55 ET (20:30 UTC) -> silence',
      run(pd.Timestamp('2026-08-17 20:30', tz='UTC'), [stale]), 0)
check('samedi -> silence', run(pd.Timestamp('2026-08-15 14:00', tz='UTC'), [stale]), 0)
check('ferie US (Labor Day 2026-09-07, 18:00 UTC) -> silence',
      run(pd.Timestamp('2026-09-07 18:00', tz='UTC'), [stale]), 0)

print('\n=== 2. le seuil suit l UT (age normal = 0..UT) ===')
now = pd.Timestamp('2026-08-17 16:27', tz='UTC')
check('M15 age 12 min -> silence', run(now, [Sleeve(108, 15, pd.Timestamp('2026-08-17 16:00', tz='UTC'))]), 0)
check('M15 age 42 min -> alerte', run(now, [Sleeve(108, 15, pd.Timestamp('2026-08-17 15:30', tz='UTC'))]), 1)
check('M5 age 2 min -> silence', run(now, [Sleeve(109, 5, pd.Timestamp('2026-08-17 16:20', tz='UTC'))]), 0)
check('H1 age 55 min -> silence (seuil 65)',
      run(now, [Sleeve(107, 60, pd.Timestamp('2026-08-17 15:15', tz='UTC'))]), 0)
check('H1 age 132 min -> alerte',
      run(now, [Sleeve(107, 60, pd.Timestamp('2026-08-17 13:15', tz='UTC'))]), 1)

print('\n=== 3. REGRESSION 2026-08-17 : une sleeve EN POSITION ne scanne pas ===')
# cas exact du deploiement: HMASTO porte le short de 16:30, _acted_bar jamais pose
held = Sleeve(108, 15, None)
check('en position + jamais scanne -> silence',
      run(now, [held], broker=FakeBroker([108])), 0)
check('en position + tres en retard -> silence',
      run(now, [Sleeve(108, 15, pd.Timestamp('2026-08-17 12:00', tz='UTC'))],
          broker=FakeBroker([108])), 0)
check('LA MEME sleeve a plat -> alerte (le controle n est pas neutralise)',
      run(now, [Sleeve(108, 15, pd.Timestamp('2026-08-17 12:00', tz='UTC'))],
          broker=FakeBroker([])), 1)
check('une en position, une a plat en retard -> alerte sur celle a plat',
      run(now, [Sleeve(108, 15, None), Sleeve(109, 5, pd.Timestamp('2026-08-17 12:00', tz='UTC'))],
          broker=FakeBroker([108])), 1)
check('un broker qui leve ne fait pas taire l alerte',
      run(now, [Sleeve(108, 15, pd.Timestamp('2026-08-17 12:00', tz='UTC'))],
          broker=BrokenBroker()), 1)

print('\n=== 4. REGRESSION 2026-08-17 : la grace se compte depuis LE DEMARRAGE ===')
# 19:02 CEST = 17:02 UTC = 13:02 ET, soit 212 min apres l ouverture -> l ancienne version
# alertait instantanement sur une relance parfaitement saine.
R._STARTED_AT = pd.Timestamp('2026-08-17 17:02', tz='UTC')
check('relance 212 min apres l ouverture, 0 min apres le demarrage -> silence',
      run(pd.Timestamp('2026-08-17 17:02:30', tz='UTC'), [Sleeve(108, 15, None)]), 0)
check('10 min apres le demarrage -> silence (dans la grace)',
      run(pd.Timestamp('2026-08-17 17:12', tz='UTC'), [Sleeve(108, 15, None)]), 0)
check('45 min apres le demarrage, toujours rien scanne -> alerte',
      run(pd.Timestamp('2026-08-17 17:47', tz='UTC'), [Sleeve(108, 15, None)]), 1)
R._STARTED_AT = None
check('_STARTED_AT non pose -> silence (pas d ancre, pas de jugement)',
      run(now, [Sleeve(108, 15, None)]), 0)
R._STARTED_AT = pd.Timestamp('2026-08-17 12:00', tz='UTC')

print('\n=== 5. sleeve non scannante ===')
check('sleeve sans bar_minutes -> jamais jugee', run(now, [Rollover(105), Rollover(102)]), 0)

print('\n=== 6. cooldown: une seule alerte par heure ===')
R._LAST_LIVENESS_ALERT = None
s = [Sleeve(108, 15, pd.Timestamp('2026-08-17 15:00', tz='UTC'))]
n1 = run(pd.Timestamp('2026-08-17 16:00', tz='UTC'), s, reset=False)
n2 = run(pd.Timestamp('2026-08-17 16:30', tz='UTC'), s, reset=False)
n3 = run(pd.Timestamp('2026-08-17 17:05', tz='UTC'), s, reset=False)
check('1re alerte', n1, 1)
check('2e a +30 min etouffee', n2, 0)
check('3e a +65 min repasse', n3, 1)

print('\n=== 7. _startup_alert : un trou nul n est pas un incident ===')
import pathlib
hb = pathlib.Path('edgelab/live/_out/heartbeat.txt')
saved = hb.read_text(encoding='utf-8') if hb.exists() else None
try:
    hb.parent.mkdir(parents=True, exist_ok=True)
    hb.write_text('2026-08-17T17:02:00+00:00\ncommit=x\n', encoding='utf-8')
    ALERTS.clear()
    R._startup_alert(CFG, pd.Timestamp('2026-08-17 17:02:30', tz='UTC'))   # trou 0.5 min
    check('relance immediate (0,5 min) -> pas de Discord', len(ALERTS), 0)
    ALERTS.clear()
    R._startup_alert(CFG, pd.Timestamp('2026-08-17 19:30', tz='UTC'))      # trou 148 min
    check('trou de 148 min -> Discord', len(ALERTS), 1)
    ALERTS.clear()
    R._startup_alert(CFG, pd.Timestamp('2026-08-17 22:30', tz='UTC'))      # hors seance
    check('hors seance -> silence', len(ALERTS), 0)
finally:
    if saved is not None:
        hb.write_text(saved, encoding='utf-8')

print('\n=== 8. le garde-fou auto_update ===')
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

print('\n=== 9. le superviseur exporte bien la variable ===')
ps1 = open('edgelab/live/run_forever.ps1', encoding='utf-8').read()
check('run_forever.ps1 pose EDGELAB_SUPERVISED', '$env:EDGELAB_SUPERVISED = "1"' in ps1, True)
check('elle est posee AVANT le lancement du runner',
      ps1.index('$env:EDGELAB_SUPERVISED') < ps1.index('launching runner'), True)

print()
if FAILS:
    print(f'{len(FAILS)} ECHEC(S): {FAILS}')
    sys.exit(1)
print('TOUS LES TESTS PASSENT')
