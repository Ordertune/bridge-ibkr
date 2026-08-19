"""T1-103 H — der Riegel gegen den zweiten Echtauftrag.

Der Fehler, den diese Datei festnagelt, war der teuerste im Sendeweg: zwischen
`place_order` und `ack_order` lag ein einziger try-Block, dessen except
`rejected` meldete. Ein Netzfehler beim Bestaetigen hatte damit zwei Wirkungen,
und beide waren falsch — die Plattform trug einen lebenden Auftrag als
abgelehnt ein, und `rejected` gab die Wiederfreigabe frei.

Die Zusicherungen hier pruefen beide Haelften der Reparatur:

  A) Ein gescheitertes ABSENDEN meldet weiterhin `rejected` — dann liegt
     nachweislich nichts beim Broker.
  B) Eine gescheiterte BESTAETIGUNG meldet gar nichts und wird nachgeholt.
  C) Derselbe Dispatch geht kein zweites Mal hinaus, auch nicht nach einem
     Neustart der Bridge.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from ordertune_bridge_ibkr import main as m
from ordertune_bridge_ibkr.submitted_store import SubmittedStore


class _FakeIbkr:
    """Nimmt Auftraege entgegen und zaehlt sie."""

    def __init__(self, *, fail_place: bool = False) -> None:
        self.platziert: list[Any] = []
        self.fail_place = fail_place

    def get_live_equity(self) -> float:
        return 0.0

    def place_order(self, contract: Any, order: Any) -> Any:
        if self.fail_place:
            raise RuntimeError("no route to broker")
        self.platziert.append(order)
        return SimpleNamespace(
            order=SimpleNamespace(orderId=4711 + len(self.platziert)),
            orderStatus=SimpleNamespace(status="PreSubmitted", filled=0),
            log=[],
        )


def _api(*, ack_faellt_aus: bool = False):
    """Eine Plattform-Attrappe, die mitschreibt, was sie zu hoeren bekommt."""
    acks: list[tuple[str, int]] = []
    results: list[dict[str, Any]] = []

    class Api:
        def get_pending(self):
            return SimpleNamespace(
                server_time="",
                pending=[
                    SimpleNamespace(
                        dispatch_id="disp-1",
                        order_intent={
                            "symbol": "NBIS",
                            "side": "buy",
                            "qty": 1,
                            "orderType": "day_limit",
                            "lmtPrice": 221.79,
                        },
                        expires_at=None,
                        cancel_requested=False,
                    )
                ],
                cancelling=[],
            )

        def ack_order(self, dispatch_id, *, broker_order_id, submitted_at):
            if ack_faellt_aus:
                raise RuntimeError("read timeout")
            acks.append((dispatch_id, broker_order_id))

        def result_order(self, dispatch_id, **kwargs):
            results.append({"dispatchId": dispatch_id, **kwargs})

    return Api(), acks, results


# ── A — ein gescheitertes Absenden bleibt eine Ablehnung ─────────────────────


def test_ein_gescheitertes_absenden_meldet_weiterhin_rejected(tmp_path) -> None:
    api, acks, results = _api()
    ibkr = _FakeIbkr(fail_place=True)
    store = SubmittedStore(tmp_path)

    m._handle_pending(api, ibkr, {}, store)

    assert acks == []
    assert len(results) == 1
    assert results[0]["status"] == "rejected"
    # Und der Vermerk ist zurueckgenommen: beim naechsten Abruf darf es einen
    # neuen Versuch geben, denn bei IBKR liegt nachweislich nichts.
    assert not store.bereits_abgeschickt("disp-1")


# ── B — eine gescheiterte Bestaetigung behauptet nichts ──────────────────────


def test_ein_gescheitertes_ack_meldet_die_order_nicht_als_abgelehnt(
    tmp_path,
) -> None:
    """Der gemessene Fall vom 2026-08-19, in seiner gefaehrlichsten Form.

    Der Auftrag liegt bei IBKR. Wuerde die Bridge hier `rejected` melden,
    stuende auf t1 „Rejected" ueber einer echten Position — und der Riegel
    gegen Doppelauftraege waere offen.
    """
    api, acks, results = _api(ack_faellt_aus=True)
    ibkr = _FakeIbkr()
    store = SubmittedStore(tmp_path)

    m._handle_pending(api, ibkr, {}, store)

    assert len(ibkr.platziert) == 1, "der Auftrag muss hinausgegangen sein"
    assert acks == [], "die Bestaetigung ist ja gescheitert"
    assert results == [], (
        "ueber einen Auftrag, der beim Broker liegt, darf die Bridge nichts "
        "behaupten, nur weil die eigene Leitung gestoert ist"
    )
    assert store.bereits_abgeschickt("disp-1")


# ── C — kein zweiter Auftrag, auch nicht nach einem Neustart ─────────────────


def test_derselbe_dispatch_geht_kein_zweites_mal_hinaus(tmp_path) -> None:
    api, acks, _ = _api(ack_faellt_aus=True)
    ibkr = _FakeIbkr()
    store = SubmittedStore(tmp_path)

    m._handle_pending(api, ibkr, {}, store)
    # Die Plattform liefert dieselbe Zeile erneut aus — sie hat ja keine
    # Bestaetigung bekommen.
    m._handle_pending(api, ibkr, {}, store)
    m._handle_pending(api, ibkr, {}, store)

    assert len(ibkr.platziert) == 1


def test_der_riegel_ueberlebt_einen_neustart(tmp_path) -> None:
    """Der Fall, den `_TRADES_BY_DISPATCH` nie abdecken konnte.

    IBKR meldet TWS taeglich gegen 05:00 MEZ zwangsweise ab. Ein Riegel, der
    dabei vergisst, ist keiner.
    """
    api, _, _ = _api(ack_faellt_aus=True)
    ibkr_vorher = _FakeIbkr()
    m._handle_pending(api, ibkr_vorher, {}, SubmittedStore(tmp_path))
    assert len(ibkr_vorher.platziert) == 1

    # Neue Sitzung: neuer Store aus derselben Ablage, leerer Speicher.
    ibkr_nachher = _FakeIbkr()
    m._handle_pending(api, ibkr_nachher, {}, SubmittedStore(tmp_path))
    assert ibkr_nachher.platziert == []


def test_die_bestaetigung_wird_nachgeholt(tmp_path) -> None:
    """Der Rueckweg schliesst sich, sobald die Leitung wieder steht."""
    store = SubmittedStore(tmp_path)

    api, acks, _ = _api(ack_faellt_aus=True)
    ibkr = _FakeIbkr()
    m._handle_pending(api, ibkr, {}, store)
    assert acks == []

    # Zweiter Durchgang, diesmal mit funktionierender Leitung.
    api_ok, acks_ok, results_ok = _api()
    m._handle_pending(api_ok, ibkr, {}, store)

    assert ibkr.platziert and len(ibkr.platziert) == 1, "kein zweiter Auftrag"
    assert acks_ok == [("disp-1", 4712)], (
        "die Bestaetigung muss mit der echten IBKR-Auftragsnummer nachkommen"
    )
    assert results_ok == []


def test_ein_unbeschreibbarer_ordner_haelt_den_handel_nicht_an(tmp_path) -> None:
    """Ein fehlender Riegel ist schlimm. Ein angehaltener Handel ist schlimmer.

    Der Nutzer erfaehrt es ueber `schreibbar` und das Protokoll.
    """
    datei = tmp_path / "run"
    datei.write_text("kein Verzeichnis", encoding="utf-8")

    store = SubmittedStore(datei)
    store.vermerken("disp-1")

    assert store.schreibbar is False
    api, acks, _ = _api()
    ibkr = _FakeIbkr()
    m._handle_pending(api, ibkr, {}, SubmittedStore(datei))
    assert len(ibkr.platziert) == 1


# ── Die Ablage fuer sich ─────────────────────────────────────────────────────


def test_die_ablage_haelt_und_vergisst(tmp_path) -> None:
    store = SubmittedStore(tmp_path)
    assert not store.bereits_abgeschickt("a")

    store.vermerken("a")
    assert store.bereits_abgeschickt("a")
    assert SubmittedStore(tmp_path).bereits_abgeschickt("a")

    store.vergessen("a")
    assert not store.bereits_abgeschickt("a")
    assert not SubmittedStore(tmp_path).bereits_abgeschickt("a")


def test_alte_eintraege_fallen_heraus(tmp_path) -> None:
    store = SubmittedStore(tmp_path)
    import time as _time

    store.vermerken("alt", jetzt=_time.time() - 31 * 24 * 60 * 60)
    store.vermerken("neu")

    frisch = SubmittedStore(tmp_path)
    assert frisch.bereits_abgeschickt("neu")
    assert not frisch.bereits_abgeschickt("alt")


def test_eine_kaputte_ablage_wird_nicht_geglaubt(tmp_path) -> None:
    (tmp_path / "submitted-dispatches.json").write_text("{kaputt", encoding="utf-8")
    store = SubmittedStore(tmp_path)
    assert not store.bereits_abgeschickt("irgendwas")
    # …und sie laesst sich danach wieder benutzen.
    store.vermerken("a")
    assert SubmittedStore(tmp_path).bereits_abgeschickt("a")


# ── A3 — eine Ablehnung von IBKR heisst „Rejected", nicht „Cancelled" ────────


class _Entry:
    def __init__(self, errorCode: int = 0, message: str = "") -> None:
        self.errorCode = errorCode
        self.message = message


def _trade(status: str, log: list[Any], filled: float = 0.0) -> Any:
    return SimpleNamespace(
        orderStatus=SimpleNamespace(status=status, filled=filled),
        log=log,
    )


def test_eine_unbekannte_ablehnung_wird_als_ablehnung_erkannt() -> None:
    """Der gemessene Fall NBIS vom 2026-08-19.

    TWS lehnte ab, der Code stand nicht in der Positivliste, und die Bridge
    meldete `cancelled`. Auf t1 stand danach „Cancelled" an einem Auftrag, den
    niemand storniert hatte.
    """
    grund = m.rejection_reason(
        _trade("Cancelled", [_Entry(0, ""), _Entry(203, "Security not available")])
    )
    assert grund == "Security not available"


def test_eine_warnung_bleibt_auch_am_toten_auftrag_keine_ablehnung() -> None:
    assert (
        m.rejection_reason(_trade("Cancelled", [_Entry(2109, "Outside RTH")]))
        is None
    )
    assert (
        m.rejection_reason(_trade("Cancelled", [_Entry(10349, "Gueltigkeitsdauer")]))
        is None
    )


def test_ein_lebender_auftrag_ist_nie_eine_ablehnung() -> None:
    """Der Verlauf des Vorfalls vom 2026-08-13, in einer Zusicherung."""
    assert (
        m.rejection_reason(_trade("Submitted", [_Entry(10349, "Gueltigkeitsdauer")]))
        is None
    )


def test_ein_gefuellter_auftrag_ist_nie_eine_ablehnung() -> None:
    assert (
        m.rejection_reason(
            _trade("Cancelled", [_Entry(399, "Order eingeschraenkt")], filled=1.0)
        )
        is None
    )


def test_eine_echte_stornierung_bleibt_eine_stornierung() -> None:
    assert (
        m.rejection_reason(_trade("Cancelled", [_Entry(202, "Order Canceled")]))
        is None
    )


@pytest.mark.parametrize("code", [201, 203, 321, 10318])
def test_die_ablehnung_traegt_immer_einen_grund(code: int) -> None:
    grund = m.rejection_reason(_trade("Cancelled", [_Entry(code, "")]))
    assert grund == "Rejected by IBKR."


# ── B1 — eine Freigabe gilt nur fuer ihre Sitzung ────────────────────────────


def _api_mit_frist(frist: str | None):
    class Api:
        def get_pending(self):
            return SimpleNamespace(
                server_time="",
                pending=[
                    SimpleNamespace(
                        dispatch_id="disp-alt",
                        order_intent={
                            "symbol": "INTC",
                            "side": "buy",
                            "qty": 1,
                            "orderType": "day_limit",
                            "lmtPrice": 95.77,
                        },
                        expires_at=frist,
                        cancel_requested=False,
                    )
                ],
                cancelling=[],
            )

        def ack_order(self, *a, **k):
            raise AssertionError("darf gar nicht erst dazu kommen")

        def result_order(self, *a, **k):
            raise AssertionError("darf gar nicht erst dazu kommen")

    return Api()


def test_eine_abgelaufene_freigabe_geht_nicht_hinaus(tmp_path) -> None:
    """Der gemessene Schaden: Rechner drei Tage aus, dann alles auf einmal."""
    ibkr = _FakeIbkr()
    m._handle_pending(
        _api_mit_frist("2026-08-15T20:30:00+00:00"),
        ibkr,
        {},
        SubmittedStore(tmp_path),
    )
    assert ibkr.platziert == []


def test_eine_gueltige_freigabe_geht_hinaus(tmp_path) -> None:
    ibkr = _FakeIbkr()
    m._handle_pending(
        _api_mit_frist("2099-01-01T20:30:00+00:00"),
        ibkr,
        {},
        SubmittedStore(tmp_path),
    )
    assert len(ibkr.platziert) == 1


def test_ohne_frist_wird_nichts_verschluckt(tmp_path) -> None:
    """Eine Plattform vor T1-103 sendet das Feld nicht."""
    ibkr = _FakeIbkr()
    m._handle_pending(_api_mit_frist(None), ibkr, {}, SubmittedStore(tmp_path))
    assert len(ibkr.platziert) == 1


# ── T1-103 O — welches Konto am Draht haengt ─────────────────────────────────


def test_die_kontokennung_wird_maskiert() -> None:
    """Live (U...) und Paper (D...) muessen unterscheidbar bleiben."""
    assert m.mask_account("U1234796") == "U***96"
    assert m.mask_account("DU1234797") == "D***97"
    assert m.mask_account(None) is None
    assert m.mask_account("") is None
    # Zu kurz zum Maskieren: dann lieber unveraendert als eine Maske, die
    # mehr verspricht als sie verbirgt.
    assert m.mask_account("U1") == "U1"


def test_die_volle_nummer_verlaesst_den_prozess_nicht() -> None:
    """Die Zusage aus T1-97, hier fuer das Cockpit festgenagelt."""
    voll = "U1234796"
    assert voll not in (m.mask_account(voll) or "")
