"""Temoins des 5 correctifs du 2026-08-19 (journal + surveillance du runner).

POURQUOI CE FICHIER EXISTE. Les quatre defauts corriges ce jour-la partagent un trait :
aucun ne se voit dans un P&L ni dans une exception. Un journal desaligne se lit sans
erreur, une ligne `enter` en double ressemble a un trade de plus, une alerte de liveness
qui crie sur un runner sain ressemble a une alerte, et une throttle qui ne throttle plus
ressemble a du log. Ils ne peuvent donc etre tenus que par des temoins.

Le scenario de reference est REEL et date : le 2026-08-18 le runner a redemarre a
16:09:19Z (auto_update) alors que TLF/NAS100 portait un short ouvert a 15:35:28Z ; la
position s'est fermee sur l'aplat de seance a 19:55:19.548Z et l'alerte de liveness est
partie 179 ms plus tard en annoncant « pas scanne depuis 226 min », soit l'age exact du
processus. Voir wiki/log.md.
"""
import csv

import pandas as pd
import pytest

from edgelab.live import runner as R
from edgelab.live.broker import Broker, Position, migrate_trade_log

FIELDS = Broker.LOG_FIELDS
ET = "America/New_York"


# --------------------------------------------------------------------------- outillage
class _FakeBroker:
    """Ne repond qu'a `open_position` : c'est tout ce que lit l'alerte de liveness."""

    def __init__(self, in_position: dict):
        self._in = in_position

    def open_position(self, magic):
        return object() if self._in.get(magic) else None


class _Win:
    tz = ET

    def __init__(self, o="09:30", c="15:30"):
        self.session_open, self.entry_cutoff = o, c


def _sleeve(cls_name, magic, bar_minutes, acted_et, window=True):
    s = type(cls_name, (object,), {})()
    s.magic, s.bar_minutes = magic, bar_minutes
    s._acted_bar = None if acted_et is None else pd.Timestamp(acted_et, tz=ET).tz_convert("UTC")
    if window:
        s.p = _Win()
    return s


def _liveness(now_et, sleeve, in_position, started_et="2026-08-18 12:09"):
    """Une passe du controle. Rend True si l'alerte est partie."""
    R._LAST_LIVENESS_ALERT = None
    R._STARTED_AT = pd.Timestamp(started_et, tz=ET).tz_convert("UTC")
    now = pd.Timestamp(now_et, tz=ET).tz_convert("UTC")
    R._maybe_liveness_alert(_FakeBroker({sleeve.magic: in_position}), {}, [sleeve], now)
    return R._LAST_LIVENESS_ALERT is not None


def _position(ticket):
    return Position(magic=109, symbol="NAS100", direction=-1, lots=2.9,
                    entry_price=29492.4, sl=29580.0, tp=None, sl_dist=87.6,
                    open_time=pd.Timestamp("2026-08-18T15:35:28Z"),
                    comment="tlf_two_leg_fade", ticket=ticket)


def _legacy_journal(path):
    """Un journal a l'en-tete de 10 colonnes du 2026-07-29, avec les 6 dispositions.

    Les largeurs et les ordres viennent de `git show 7ce79cf^:edgelab/live/broker.py`,
    pas d'une supposition : avant ce commit `_log_trade` prenait ses colonnes de
    `list(row.keys())`, donc chaque type de ligne avait la sienne.
    """
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["time", "event", "symbol", "dir", "lots", "price", "sl", "tp",
                    "reason", "ticket"])
        w.writerow(["2026-07-29T16:29:08+00:00", "enter", "BTCUSD", "-1", "0.03",
                    "63955.72", "67242.53", "59025.49", "brick3_macd_rsi_short", "81405353"])
        w.writerow(["2026-07-30T14:00:00+00:00", "enter", "NAS100", "-1", "1.0", "20000.0",
                    "20100.0", "", "brick1_breakout_short"])
        w.writerow(["2026-08-10T15:35:08+00:00", "stop_order", "NAS100", "-1", "2.9",
                    "29492.4", "29580.0", "", "tlf_two_leg_fade", "83515343"])
        w.writerow(["2026-08-10T15:40:00+00:00", "cancel", "NAS100", "one_bar_expiry",
                    "83515343"])
        w.writerow(["2026-08-10T19:55:00+00:00", "exit", "NAS100", "-1", "2.9", "29500.0",
                    "", "", "tlf:time_exit", "-0.321", "1.234"])
        w.writerow(["2026-08-18T19:55:19+00:00", "exit", "NAS100", "-1", "2.9", "29493.7",
                    "", "", "tlf:time_exit", "-0.011", "2.500", "83515343"])


# ------------------------------------------------------- 5. schema du journal de trades
def test_migration_realigne_chaque_disposition(tmp_path):
    jl = tmp_path / "trades.csv"
    _legacy_journal(jl)
    assert migrate_trade_log(jl, FIELDS) is not None
    rows = list(csv.DictReader(open(jl, newline="", encoding="utf-8")))
    assert tuple(next(csv.reader(open(jl, encoding="utf-8")))) == tuple(FIELDS)
    assert len(rows) == 6
    assert rows[0]["ticket"] == "81405353" and rows[0]["R"] == ""
    assert rows[1]["reason"] == "brick1_breakout_short" and rows[1]["ticket"] == ""
    assert rows[2]["ticket"] == "83515343"
    assert (rows[3]["symbol"], rows[3]["reason"], rows[3]["ticket"]) == \
           ("NAS100", "one_bar_expiry", "83515343")
    # LE DEFAUT DE PRODUCTION : le R d'une sortie etait lu dans la colonne `ticket`
    assert rows[4]["R"] == "-0.321" and rows[4]["cumR"] == "1.234" and rows[4]["ticket"] == ""
    assert rows[5]["R"] == "-0.011" and rows[5]["ticket"] == "83515343"


def test_migration_idempotente(tmp_path):
    jl = tmp_path / "trades.csv"
    _legacy_journal(jl)
    migrate_trade_log(jl, FIELDS)
    assert migrate_trade_log(jl, FIELDS) is None


def test_summary_lit_toujours_reason_en_8_et_R_en_9():
    """`summary` lit le journal par POSITION : la migration ne doit pas la casser."""
    assert FIELDS.index("reason") == 8 and FIELDS.index("R") == 9


def test_ligne_illisible_abandonne_sans_toucher_au_fichier(tmp_path):
    bad = tmp_path / "bad.csv"
    with open(bad, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["time", "event", "symbol"])
        w.writerow(["2026-01-01T00:00:00+00:00", "wat", "X", "1", "2", "3", "4"])
    before = bad.read_text(encoding="utf-8")
    with pytest.raises(ValueError):
        migrate_trade_log(bad, FIELDS)
    assert bad.read_text(encoding="utf-8") == before


# ------------------------------------------- 3. idempotence de journal_fill au redemarrage
def test_journal_fill_ne_redouble_pas_apres_un_redemarrage(tmp_path):
    jl = tmp_path / "j.csv"
    cfg = {"live_trading": False, "trade_log_csv": str(jl)}

    def n_enter():
        return sum(1 for r in csv.DictReader(open(jl, newline="", encoding="utf-8"))
                   if r["event"] == "enter")

    Broker(cfg).journal_fill(_position(83515343), pd.Timestamp("2026-08-18T15:35:28Z"))
    assert n_enter() == 1
    # LE REDEMARRAGE : nouveau processus, donc nouveau Broker et `_filled_logged` neuf.
    assert Broker(cfg).journal_fill(_position(83515343),
                                    pd.Timestamp("2026-08-18T16:09:43Z")) is False
    assert n_enter() == 1
    Broker(cfg).journal_fill(_position(99999999), pd.Timestamp("2026-08-18T17:00:00Z"))
    assert n_enter() == 2


# ----------------------------------------------------------- 1+2. alerte de liveness
def test_pas_d_alerte_quand_la_position_se_ferme():
    """Le scenario du 2026-08-18, celui qui a produit le « 226 min »."""
    R._SEEN_IN_POSITION.clear()
    tlf = _sleeve("TwoLegFadeStrategy", 109, 5, None)      # redemarrage en position
    for hhmm in ("12:15", "13:00", "14:00", "15:00", "15:50"):
        assert not _liveness(f"2026-08-18 {hhmm}", tlf, True)
    assert not _liveness("2026-08-18 15:55", tlf, False)   # l'aplat de seance ferme


def test_pas_d_alerte_hors_de_la_fenetre_de_signal():
    """TLF ne scanne plus apres 15:35 ET ; la porte de seance, elle, court jusqu'a 15:55."""
    R._SEEN_IN_POSITION.clear()
    tlf = _sleeve("TwoLegFadeStrategy", 109, 5, "2026-08-18 15:30")
    assert not _liveness("2026-08-18 15:55:30", tlf, False)


def test_pas_d_alerte_a_la_sortie_d_un_trade_H4():
    """RSKEW tient 5 barres H4 = 20 h ; sans le correctif : « 965 min »."""
    R._SEEN_IN_POSITION.clear()
    rskew = _sleeve("ResearchSleeveStrategy", 112, 240, None, window=False)
    assert not _liveness("2026-08-18 13:00", rskew, True)
    assert not _liveness("2026-08-18 13:05", rskew, False)


def test_un_vrai_gel_alerte_toujours():
    R._SEEN_IN_POSITION.clear()
    gele = _sleeve("TwoLegFadeStrategy", 109, 5, "2026-08-18 11:00")
    assert _liveness("2026-08-18 13:00", gele, False)


def test_une_sleeve_qui_n_a_jamais_scanne_alerte_apres_la_grace():
    R._SEEN_IN_POSITION.clear()
    jamais = _sleeve("TwoLegFadeStrategy", 110, 5, None)
    assert _liveness("2026-08-18 15:00", jamais, False, started_et="2026-08-18 12:00")
    R._SEEN_IN_POSITION.clear()
    jeune = _sleeve("TwoLegFadeStrategy", 110, 5, None)
    assert not _liveness("2026-08-18 14:10", jeune, False, started_et="2026-08-18 14:00")


def test_gel_apres_une_sortie_de_position_alerte():
    """L'exclusion « en position » ne doit pas devenir une amnistie permanente."""
    R._SEEN_IN_POSITION.clear()
    s = _sleeve("TwoLegFadeStrategy", 109, 5, None)
    _liveness("2026-08-18 12:30", s, True)
    assert _liveness("2026-08-18 14:30", s, False)


# ------------------------------------------------------ 4. throttle indexee sur le magic
def test_la_throttle_survit_au_succes_de_la_sleeve_jumelle():
    class _Risk:
        initial_balance, risk_per_trade, failed = 100000.0, 0.01, False

        def on_equity(self, *a):
            pass

    class _Brk:
        orders_sent, live, realized_R = 0, False, 0.0

        def open_position(self, magic):
            return None

    class _Base:
        def __init__(self, magic, boom):
            self.magic, self.boom = magic, boom

        def step(self, *a):
            if self.boom:
                raise RuntimeError("no bars for NAS100 M5")

    Twin = type("TwoLegFadeStrategy", (_Base,), {})      # LA MEME classe pour les deux
    R._LAST_FAILURE.clear()
    strategies = [Twin(109, True), Twin(110, False)]
    for _ in range(3):
        R.one_pass(_Brk(), _Risk(), strategies, pd.Timestamp("2026-08-18T16:00:00Z"))
    assert sorted(R._LAST_FAILURE) == ["TwoLegFadeStrategy/109"]
