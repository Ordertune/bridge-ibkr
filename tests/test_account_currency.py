"""T1-85: die Waehrung, in der das Konto seinen Depotwert meldet.

## Woher der Test kommt

Am 2026-08-12 lief die erste Bridge vollstaendig durch — Handshake, Heartbeat,
Auftragsabruf, alles 200 — und der Depotwert kam als 0 an. Das Konto des Owners
ist EUR-basiert, was bei einem deutschen IBKR-Konto der Normalfall ist. Der
Client suchte ausschliesslich nach USD-Zeilen, fand keine, und meldete 0.

Der naheliegende Fehler waere gewesen, den EUR-Betrag einfach in das Feld
`equityUsd` zu schreiben. Die Mengenrechnung teilt durch einen Einstiegspreis
in USD; jede Stueckzahl waere dann um den Wechselkurs daneben gewesen — bei
~0,92 rund 8 % zu klein, ohne Absturz, ohne Meldung, ohne Protokollzeile.

Deshalb pruefen diese Zusicherungen vor allem eines: dass hier nicht geraten
wird. Eine falsche Waehrung ist ein stiller Faktor auf jede einzelne Order.
"""
from __future__ import annotations

from dataclasses import dataclass

from ordertune_bridge_ibkr.ibkr_client import resolve_account_currency


@dataclass
class FakeAccountValue:
    """Nur die drei Felder, die die Aufloesung liest."""

    tag: str
    value: str
    currency: str


def _nlv(currency: str, value: str = "1000.00") -> FakeAccountValue:
    return FakeAccountValue(tag="NetLiquidation", value=value, currency=currency)


def test_single_currency_is_the_answer() -> None:
    assert resolve_account_currency([_nlv("USD")]) == "USD"
    assert resolve_account_currency([_nlv("EUR")]) == "EUR"


def test_base_aggregate_row_is_not_a_currency() -> None:
    """IBKR fuehrt neben den Segmenten eine Sammelzeile mit der Kennung BASE.

    Sie benennt keine Waehrung. Zaehlte sie mit, waere jedes Konto
    mehrdeutig und damit dauerhaft blockiert.
    """
    assert resolve_account_currency([_nlv("EUR"), _nlv("BASE")]) == "EUR"
    assert resolve_account_currency([_nlv("USD"), _nlv("")]) == "USD"


def test_lowercase_is_not_a_second_currency() -> None:
    assert resolve_account_currency([_nlv("usd"), _nlv("USD")]) == "USD"


def test_several_currencies_yield_no_answer() -> None:
    """Kein Rateschritt.

    Welche der Zeilen der Depotwert des Kontos ist und welche ein Segment
    darin, laesst sich hier nicht entscheiden. USD zu bevorzugen, weil die
    Plattform in USD rechnet, waere genau der Fehlgriff, den dieser Spec
    verhindern soll: er sieht richtig aus und meldet ein Teilsegment als
    Gesamtwert.
    """
    assert resolve_account_currency([_nlv("EUR"), _nlv("USD")]) is None
    assert resolve_account_currency([_nlv("EUR"), _nlv("USD"), _nlv("BASE")]) is None


def test_no_account_values_yield_no_answer() -> None:
    """Die Subskription hat noch nichts geliefert. Das ist nicht USD."""
    assert resolve_account_currency([]) is None
    assert resolve_account_currency([_nlv("BASE")]) is None


def test_other_tags_do_not_decide_the_currency() -> None:
    """Nur NetLiquidation zaehlt.

    Ein Konto haelt oft Barmittel in mehreren Waehrungen, ohne dass das etwas
    ueber seine Basiswaehrung sagt. Zoege `TotalCashValue` mit, waere ein
    EUR-Konto mit etwas USD-Cash ploetzlich mehrdeutig.
    """
    values = [
        _nlv("EUR"),
        FakeAccountValue(tag="TotalCashValue", value="500", currency="USD"),
        FakeAccountValue(tag="TotalCashValue", value="700", currency="EUR"),
    ]
    assert resolve_account_currency(values) == "EUR"
