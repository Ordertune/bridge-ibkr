"""ib_insync-Wrapper für TWS/Gateway.

Async-first, aber gewrappt in sync-Interface für den Scheduler-basierten
Poll-Loop. ib_insync erlaubt beides via internem util.run().
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from ib_insync import IB, AccountValue, Contract, Order, PortfolioItem

log = logging.getLogger(__name__)


@dataclass
class AccountSnapshot:
    """T1-85 — Betrag und Einheit gehoeren zusammen.

    Bis 0.2.x hiessen diese Felder `cash_usd` und `equity_usd`. Der Name trug
    eine Behauptung ueber die Einheit, die der Client gar nicht pruefen konnte,
    und die bei einem deutschen IBKR-Konto — EUR-basiert, der Normalfall —
    schlicht falsch war. Der einzige Ausweg war, 0 zu melden und zu warnen.

    Jetzt reist die Einheit mit. `currency` ist `None`, wenn der Client sie
    nicht eindeutig bestimmen konnte; das ist eine Aussage und keine Vermutung.
    """

    cash: float
    equity: float
    currency: str | None
    positions: list[dict[str, Any]]
    gateway_status: str


# Sammelzeilen des Kontos, die keine echte Waehrung benennen.
_AGGREGATE_CURRENCY_MARKERS = {"BASE", ""}


def resolve_account_currency(acct_values: list[AccountValue]) -> str | None:
    """Die Waehrung, in der das Konto seinen Depotwert meldet.

    IBKR fuehrt zu `NetLiquidation` eine Zeile je Waehrungssegment plus eine
    Sammelzeile mit der Kennung `BASE`. Die Sammelzeile benennt keine Waehrung
    und faellt deshalb raus.

    Bleibt genau eine Waehrung uebrig, ist sie die Antwort. Bleiben mehrere,
    gibt es hier bewusst **keine** Antwort: welche davon der Depotwert des
    Kontos ist und welche ein Segment darin, laesst sich aus diesen Zeilen
    nicht entscheiden. Ein Fehlgriff waere ein stiller Faktor auf jede
    Stueckzahl — genau die Fehlerklasse, gegen die T1-78 angetreten ist.
    Lieber `None`, das die Plattform laut blockiert.
    """
    currencies = {
        v.currency.upper()
        for v in acct_values
        if v.tag == "NetLiquidation"
        and v.currency
        and v.currency.upper() not in _AGGREGATE_CURRENCY_MARKERS
    }
    if len(currencies) == 1:
        return next(iter(currencies))
    return None


class IbkrClient:
    def __init__(self, host: str, port: int, client_id: int) -> None:
        self._host = host
        self._port = port
        self._client_id = client_id
        self._ib = IB()

    def connect(self) -> None:
        log.info("Connecting to IBKR TWS/Gateway at %s:%d (client-id=%d)",
                 self._host, self._port, self._client_id)
        self._ib.connect(self._host, self._port, clientId=self._client_id)
        log.info("Connected to IBKR TWS/Gateway.")

    def disconnect(self) -> None:
        if self._ib.isConnected():
            self._ib.disconnect()

    def is_connected(self) -> bool:
        return self._ib.isConnected()

    def account_snapshot(self) -> AccountSnapshot:
        """Read cash, equity, currency and positions from IBKR.

        T1-85: bis 0.2.x hat diese Methode ausschliesslich nach USD-Zeilen
        gesucht und bei einem EUR-Konto 0 gemeldet — laut, aber unbrauchbar.
        Sie meldet jetzt den tatsaechlichen Depotwert **samt** Waehrung und
        ueberlaesst der Plattform die Entscheidung, ob daraus eine Stueckzahl
        werden darf.

        Beide Betraege stammen aus **derselben** Waehrung. Cash aus einem
        Segment und Depotwert aus einem anderen zu mischen ergaebe ein Paar,
        das zueinander nicht passt, und niemand saehe es an den Zahlen.
        """
        acct_values: list[AccountValue] = self._ib.accountValues()
        currency = resolve_account_currency(acct_values)

        cash = 0.0
        equity = 0.0
        if currency is not None:
            for v in acct_values:
                if v.currency.upper() != currency:
                    continue
                if v.tag == "TotalCashValue":
                    cash = float(v.value)
                elif v.tag == "NetLiquidation":
                    equity = float(v.value)

        self._log_account_currency(acct_values, currency, equity)

        portfolio: list[PortfolioItem] = self._ib.portfolio()
        positions = [
            {
                "symbol": p.contract.symbol,
                "qty": float(p.position),
                "avg_cost": float(p.averageCost),
                "market_price": float(p.marketPrice or 0),
                "market_value": float(p.marketValue or 0),
                "unrealized_pnl": float(p.unrealizedPNL or 0),
            }
            for p in portfolio
        ]

        return AccountSnapshot(
            cash=cash,
            equity=equity,
            currency=currency,
            positions=positions,
            gateway_status="connected" if self._ib.isConnected() else "disconnected",
        )


    def _log_account_currency(
        self,
        acct_values: list[AccountValue],
        currency: str | None,
        equity: float,
    ) -> None:
        """Sag, was da war — vier Lagen, die sehr Verschiedenes bedeuten.

          - keine Kontowerte           → die Subskription hat noch nicht geliefert
          - Waehrung nicht eindeutig   → mehrere Segmente, keine Entscheidung
          - Waehrung nicht USD         → das Konto laeuft in fremder Waehrung
          - USD und Depotwert 0        → das Konto ist wirklich leer

        Ein blosses "equity is 0" kann sie nicht auseinanderhalten, und der
        Nutzer sieht in allen vier Faellen eine gesunde Verbindung.
        """
        if not acct_values:
            log.warning(
                "No account values received from TWS yet. The account "
                "subscription may not have delivered; Ordertune cannot size "
                "any order until it does."
            )
            return

        if currency is None:
            seen = sorted(
                {
                    v.currency.upper()
                    for v in acct_values
                    if v.tag == "NetLiquidation" and v.currency
                }
            )
            log.warning(
                "Could not determine the account currency unambiguously. "
                "NetLiquidation is reported for: %s. Ordertune will block "
                "order sizing rather than guess. Please report this.",
                ", ".join(seen) if seen else "nothing",
            )
            return

        if currency != "USD":
            log.warning(
                "This account is denominated in %s, not USD. The value is "
                "reported to Ordertune as %s %.2f. Ordertune sizes positions "
                "against USD entry prices and does not convert yet, so order "
                "sizing stays blocked in full-equity mode. A fixed base "
                "amount in USD works in the meantime.",
                currency,
                currency,
                equity,
            )
            return

        if equity == 0.0:
            log.warning(
                "NetLiquidation in USD is 0. If the account is funded, check "
                "that TWS is logged in to the intended account."
            )

    def get_live_equity(self) -> float:
        """Depotwert in USD fuer den Sizing-Abgleich — sonst 0.

        T1-85: der Abgleich haelt die serverseitig gerechnete Menge gegen eine
        hier neu gerechnete. Beide Rechnungen teilen durch einen Einstiegspreis
        in USD. Ein Depotwert in EUR wuerde die Gegenrechnung um den Wechselkurs
        verschieben und die Order als `sizing_drift` ablehnen — mit einer
        Begruendung, die nach einem Mengenfehler klingt und in Wahrheit ein
        Einheitenfehler waere.

        Deshalb 0 bei fremder Waehrung: der Aufrufer ueberspringt den Abgleich
        (`live_equity > 0`) statt falsch zu urteilen. Stillschweigend ist das
        nicht — der Heartbeat warnt im Minutentakt, und in `full_equity` laesst
        die Plattform es gar nicht erst bis hierher kommen.
        """
        acct_values: list[AccountValue] = self._ib.accountValues()
        if resolve_account_currency(acct_values) != "USD":
            return 0.0
        for v in acct_values:
            if v.tag == "NetLiquidation" and v.currency.upper() == "USD":
                return float(v.value)
        return 0.0

    def place_order(self, contract: Contract, order: Order) -> Any:
        """Submit an order via ib_insync. Returns Trade object."""
        trade = self._ib.placeOrder(contract, order)
        return trade

    def cancel_order(self, order: Order) -> None:
        """T1-88c — Storno an IBKR schicken.

        Meldet NICHTS zurueck. Ob aus der Anfrage eine Stornierung wird,
        entscheidet IBKR, und die Antwort kommt als Zustandsereignis — dort,
        wo `cancel_is_genuine` sie prueft. Diese Methode hier einen Erfolg
        behaupten zu lassen waere derselbe Fehler wie der Phantom-Storno aus
        T1-88b, nur mit umgekehrtem Vorzeichen.

        T1-96 — Berichtigung: bis hierher stand hier "als Zustandsereignis mit
        Fehlercode 202". Das stimmt nicht. ib_insync fuehrt 202 unter den
        Warnungen (wrapper.py:1097) und haengt Warnungen keinen
        Protokolleintrag an den Auftrag. In `trade.log` steht die Bestaetigung
        als gewoehnlicher Zustandswechsel mit `errorCode = 0`; die 202 kommt
        ausschliesslich ueber `errorEvent` (siehe `subscribe_error_callback`).
        `cancel_is_genuine` traegt trotzdem, weil die 0 genau das bedeutet,
        worauf es ankommt: IBKR hat den Zustand gesetzt, nicht ib_insync.
        """
        self._ib.cancelOrder(order)

    def open_trades(self) -> list[Any]:
        """Alle bei IBKR offenen Auftraege, frisch erfragt.

        `reqAllOpenOrders` fragt TWS, statt einen lokalen Zwischenspeicher zu
        lesen — nach einem Neustart der Bridge ist der leer, und genau dann
        wird diese Methode gebraucht.
        """
        return list(self._ib.reqAllOpenOrders())

    def subscribe_execution_callback(self, cb: Any) -> None:
        """Register callback for order status updates."""
        self._ib.execDetailsEvent += cb  # type: ignore[operator]
        self._ib.orderStatusEvent += cb  # type: ignore[operator]

    def subscribe_error_callback(self, cb: Any) -> None:
        """T1-96 — Mitschnitt der Meldungen, die `trade.log` nie erreichen.

        ib_insync fuehrt 202 in `warningCodes` (wrapper.py:1097). Warnungen
        werden dort ausschliesslich geloggt: kein Protokolleintrag am Auftrag,
        keine Zustandsaenderung. In `trade.log` steht bei einer Stornierung
        durch IBKR deshalb ein Eintrag mit `errorCode = 0` — dem Feld-Default
        aus `orderStatus` (wrapper.py:438) — und nie die 202.

        Ueber `errorEvent` kommt sie an (wrapper.py:1173, fuer jeden Code,
        auch fuer Warnungen), mitsamt Meldungstext. Das ist der einzige Kanal,
        auf dem sich ein Storno in TWS von einem Verfall zum Boersenschluss
        unterscheiden koennte — beide erzeugen sonst dasselbe Datum.

        Registriert wird nur, was IBKR selbst sagt. Bewertet wird hier nichts.
        """
        self._ib.errorEvent += cb  # type: ignore[operator]

    def sleep(self, seconds: float) -> None:
        """ib_insync-native sleep that keeps event-loop running."""
        self._ib.sleep(seconds)
