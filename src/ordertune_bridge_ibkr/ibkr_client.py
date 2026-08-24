"""ib_insync-Wrapper für TWS/Gateway.

Async-first, aber gewrappt in sync-Interface für den Scheduler-basierten
Poll-Loop. ib_insync erlaubt beides via internem util.run().
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from ib_insync import IB, AccountValue, Contract, Order, PortfolioItem

from .write_access import (
    CONFIRMED as READ_ONLY_CONFIRMED,
    SUSPECTED as READ_ONLY_SUSPECTED,
    VALIDATION_ERROR_CODE,
    WriteAccess,
    classify as classify_write_access,
)

log = logging.getLogger(__name__)

# T1-101 B-2: wie lange auf die Antwort des Auftragskanals gewartet wird. Auf
# einer gesunden Verbindung kommt sie in Millisekunden; unter Schreibschutz
# kommt sie nie. Drei Sekunden sind reichlich Reserve und halten den Start
# kurz, wenn es schiefgeht — bei ib_insync selbst sind es vier.
WRITE_ACCESS_TIMEOUT_S = 3.0


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
    #: T1-99: `None` heisst „ich weiss es gerade nicht", eine leere Liste
    #: heisst „das Konto haelt nichts". Bis 0.5.x gab es nur die leere Liste
    #: fuer beides — und die Plattform las sie als Aussage. Am 2026-08-18
    #: wurden daraus zwei echte Positionen als extern verkauft gebucht.
    positions: list[dict[str, Any]] | None
    gateway_status: str
    # T1-103 O — auf WELCHEM Konto das hier alles passiert.
    #
    # Am 2026-08-19 hat der Owner zwischen Live- (7496) und Papierkonto (7497)
    # gewechselt. Weder das Cockpit noch t1 haben irgendwo gezeigt, welches
    # Konto gerade am Draht haengt — die Zahlen aenderten sich, und man musste
    # aus dem Depotwert raten. Bei einem Werkzeug, das Echtauftraege schickt,
    # ist das die wichtigste Angabe ueberhaupt.
    #
    # `None` heisst „nicht eindeutig bestimmbar" — ein Login mit mehreren
    # Konten. Das ist eine Aussage und keine Vermutung.
    account: str | None = None


# Sammelzeilen des Kontos, die keine echte Waehrung benennen.
_AGGREGATE_CURRENCY_MARKERS = {"BASE", ""}

# T1-99: wie lange auf die Antwort der Positionsabfrage gewartet wird. Grosszuegig
# gegenueber dem Verbindungs-Zeitueberlauf von ib_insync (4 s), weil TWS beim
# Start unter Last steht — aber endlich, weil ein haengender Client fuer den
# Nutzer aussieht wie ein abgestuerzter.
POSITIONS_TIMEOUT_S = 20.0


def _opt(value: Any) -> float | None:
    """Eine Zahl, oder nichts — aber nie eine erfundene Null.

    IBKR liefert fuer nicht abonnierte Marktdaten `nan` oder `None`. Beides als
    0 zu melden waere eine Aussage ueber einen Marktwert, den niemand kennt.
    """
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return None if f != f else f  # NaN faellt raus


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
        # T1-99: hat die Positionsabfrage in DIESER Sitzung je geantwortet?
        # Nicht „sind Zeilen angekommen" — ein leeres Depot liefert keine
        # Zeilen und ist trotzdem eine gueltige Auskunft. Es zaehlt, dass die
        # Abfrage abgeschlossen wurde.
        self._positions_known = False
        self._multi_account_warned = False
        # T1-101 B-2: die 321er aus dem Verbindungsfenster, mit ihrem Text.
        self._validation_errors: list[str] = []
        self._write_access = WriteAccess()

    def _on_error(self, reqId: int, errorCode: int, errorString: str, *_: Any) -> None:
        """Sammelt die Fehler, die TWS von sich aus schickt.

        Nur die 321er, und nur zur Diagnose. Alles andere haengt bereits an
        anderen Wegen — dieser Rueckruf darf nichts entscheiden.
        """
        if errorCode == VALIDATION_ERROR_CODE:
            self._validation_errors.append(str(errorString or "").strip())

    def connect(self) -> None:
        log.info("Connecting to IBKR TWS/Gateway at %s:%d (client-id=%d)",
                 self._host, self._port, self._client_id)
        # VOR dem Verbinden angehaengt: der 321er kommt rund eine Zehntel-
        # sekunde nach den Positionen, also mitten im Verbindungsvorgang.
        # Danach angehaengt waere er schon durch.
        self._ib.errorEvent += self._on_error
        self._ib.connect(self._host, self._port, clientId=self._client_id)
        log.info("Connected to IBKR TWS/Gateway.")
        self._confirm_positions_subscription()
        self._confirm_write_access()

    def _confirm_write_access(self) -> None:
        """T1-101 B-2 — antwortet der Auftragskanal ueberhaupt?

        Das sprachunabhaengige Signal. Unter Schreibschutz beantwortet TWS die
        Auftragsanfrage nicht; `ib_insync` laesst sie beim Verbinden deshalb
        ganz aus, wenn man ihm `readonly=True` mitgibt. Hier wird sie
        ausdruecklich gestellt und ihr Ausbleiben gemessen.

        **Es ist eine reine Leseanfrage.** Es geht kein Auftrag hinaus und
        keiner wird veraendert. Auf einer gesunden Verbindung antwortet sie in
        Millisekunden, auch wenn gar kein Auftrag offen ist.

        ## Es muss `reqOpenOrders` sein, NICHT `reqAllOpenOrders`

        Am 2026-08-19 gemessen, an einer TWS mit eingeschaltetem Schreibschutz:

          * `reqOpenOrders` — die eigenen Auftraege — wird **verweigert**.
          * `reqAllOpenOrders` — alle Clients — **antwortet weiterhin** und
            liefert sogar die von Hand gestellte Order.

        Wer das hier auf `reqAllOpenOrders` umstellt, weil es „dasselbe" tut,
        schaltet die Erkennung ab: sie wuerde nie wieder ausloesen, und zwar
        stumm. Und stumm ist hier das Schlimmste, was passieren kann — unter
        Schreibschutz sieht die Bridge kerngesund aus, meldet Herzschlaege und
        laesst jeden Auftrag abprallen.

        Die Frist ist ebenfalls tragend: `IB.reqCompletedOrders` und
        `IB.reqAllOpenOrders` laufen ueber `_run()` **ohne** Frist, und unter
        Schreibschutz haengt der erste davon endlos (Fehler 321 kommt mit
        `reqId -1` und loest die wartende Anfrage nicht auf). Siehe T1-103.
        """
        beantwortet = True
        try:
            self._ib.run(
                self._ib.reqOpenOrdersAsync(), timeout=WRITE_ACCESS_TIMEOUT_S
            )
        except Exception:
            beantwortet = False

        self._write_access = classify_write_access(
            validation_errors=list(self._validation_errors),
            open_orders_answered=beantwortet,
        )

        if self._write_access.state == READ_ONLY_CONFIRMED:
            log.error(
                "TWS is running with Read-Only API. Everything else looks "
                "healthy — positions arrive, heartbeats go out — but every "
                "order will be rejected. Turn off 'Read-Only API' in the API "
                "settings and restart TWS. IBKR said: %s",
                self._write_access.detail,
            )
        elif self._write_access.state == READ_ONLY_SUSPECTED:
            log.warning(
                "TWS did not answer the open-orders request within %.0fs. "
                "Read-Only API is the usual cause; orders would be rejected.",
                WRITE_ACCESS_TIMEOUT_S,
            )

    def write_access(self) -> WriteAccess:
        return self._write_access

    def _confirm_positions_subscription(self) -> None:
        """T1-99 — die Positionsabfrage ausdruecklich abwarten.

        ## Warum das nicht schon durch `connect()` erledigt ist

        ib_insync fragt beim Verbinden Positionen UND Kontodaten an und
        schluckt einen Zeitueberlauf bei beidem. Am 2026-08-18 lief genau das
        Konto-Abo in einen Zeitueberlauf (`account updates for U... request
        timed out`), waehrend die Positionen ankamen — sichtbar im Protokoll,
        unsichtbar im Code. Danach war `portfolio()` leer und `positions()`
        gefuellt, und die Bridge las ausgerechnet das leere.

        Hier wird die Abfrage deshalb ein zweites Mal gestellt und ihr
        Abschluss abgewartet. Antwortet sie, ist die Auskunft belastbar — auch
        wenn sie leer ist. Antwortet sie nicht, schweigt der Heartbeat lieber,
        als ein leeres Depot zu behaupten.

        Der Zeitueberlauf ist hart begrenzt: ein Warten ohne Grenze wuerde die
        Bridge beim Start haengen lassen, und ein haengender Client meldet
        keinen Herzschlag — fuer den Nutzer nicht von einem Absturz zu
        unterscheiden.
        """
        try:
            self._ib.run(
                self._ib.reqPositionsAsync(), timeout=POSITIONS_TIMEOUT_S
            )
        except Exception as exc:
            self._positions_known = False
            log.warning(
                "IBKR did not answer the positions request within %.0fs (%s). "
                "Ordertune will be told that the portfolio is unknown rather "
                "than empty, so no position gets booked as sold. Model exits "
                "stay blocked until the answer arrives.",
                POSITIONS_TIMEOUT_S,
                exc,
            )
            return
        self._positions_known = True
        log.info(
            "Portfolio subscription confirmed — %d position(s) reported.",
            len(self._ib.positions()),
        )

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

        positions = self._positions()

        return AccountSnapshot(
            cash=cash,
            equity=equity,
            currency=currency,
            positions=positions,
            gateway_status="connected" if self._ib.isConnected() else "disconnected",
            account=self._trading_account(),
        )


    def _positions(self) -> list[dict[str, Any]] | None:
        """T1-99 — der Depotbestand, aus der Quelle, die nicht schweigt.

        ## Zwei Wege, und der bisher benutzte ist der schwaechere

        IBKR liefert Positionen ueber zwei getrennte Kanaele:

          - `positions()`  — gespeist aus `reqPositions`. Symbol, Menge,
                             Einstand. Kommt frueh und zuverlaessig.
          - `portfolio()`  — gespeist aus dem Konto-Abo. Zusaetzlich Kurs,
                             Marktwert und unrealisiertes Ergebnis. Genau
                             dieses Abo lief am 2026-08-18 in einen
                             Zeitueberlauf, und `portfolio()` blieb leer.

        Bis 0.5.x las diese Methode ausschliesslich den zweiten. Das Ergebnis
        war eine leere Positionsliste bei vollem Depot — und die Plattform
        buchte daraufhin zwei Positionen als extern verkauft.

        Ab hier ist `positions()` die Wahrheit ueber Bestand und Menge;
        `portfolio()` reichert nur noch an und darf fehlen.

        ## Warum fehlende Anreicherung `None` ergibt und nicht 0

        Eine Null ist eine Aussage. Ein Marktwert von 0 fuer eine Position,
        die es gibt, waere schlicht falsch, und die Plattform zieht aus diesen
        Zahlen Schluesse. Der Vertrag laesst beide Felder ausdruecklich leer.
        """
        if not self._positions_known:
            return None

        # BUG-99-1 — auf das Handelskonto begrenzen.
        #
        # `portfolio()` wurde von `reqAccountUpdates` gespeist, und ib_insync
        # fragt das ausschliesslich fuer ein EINZELNES verwaltetes Konto an
        # (`connectAsync`: `if not account and len(accounts) == 1`).
        # `positions()` liefert dagegen alle Konten des Logins.
        #
        # Ohne diese Grenze summierte die Plattform bei einem Login mit mehreren
        # Konten die Mengen je Symbol — die gemeldete Brokerzahl waere groesser
        # als das, was das Handelskonto haelt, und `exitBudgetAllows` gaebe ein
        # zu grosses Budget frei. Am Ende steht die Leerposition auf einem
        # Long-Konto, gegen die T1-95 angetreten ist.
        account = self._trading_account()
        # Einmal je Sitzung. Der Heartbeat kommt jede Minute, und eine Warnung
        # je Schlag ist dasselbe Rauschen, das BUG-99-2 im Protokoll der
        # Plattform abgestellt hat — nur eine Ebene tiefer.
        if account is None and not self._multi_account_warned:
            self._multi_account_warned = True
            log.warning(
                "This login manages several accounts and Ordertune cannot tell "
                "which one it trades. Portfolio quantities are reported across "
                "all of them, which can overstate what any single account "
                "holds. Please report this."
            )

        # Anreicherung ueber die Kontraktkennung, nicht ueber das Symbol: bei
        # Optionen und mehreren Boersen ist das Symbol nicht eindeutig.
        enrichment: dict[int, PortfolioItem] = {}
        try:
            for item in self._ib.portfolio():
                enrichment[item.contract.conId] = item
        except Exception as exc:  # pragma: no cover - defensiv
            log.debug("portfolio() unavailable for enrichment: %s", exc)

        rows: list[dict[str, Any]] = []
        for p in self._ib.positions(account) if account else self._ib.positions():
            extra = enrichment.get(p.contract.conId)
            rows.append(
                {
                    "symbol": p.contract.symbol,
                    "qty": float(p.position),
                    "avg_cost": float(p.avgCost),
                    # T1-107: an WELCHEM Konto diese Menge haengt.
                    #
                    # `Position` traegt das Konto als erstes Feld, und bis
                    # hierher wurde es gelesen und weggeworfen. Ohne diese
                    # Angabe ist eine Positionsliste nicht als die eines
                    # bestimmten Depots erkennbar — und wer zwischen zwei
                    # Konten wechselt, schickt zwei Listen, die sich nicht
                    # auseinanderhalten lassen.
                    #
                    # Zusammen mit der Kennung im Snapshot macht sie auch den
                    # Mehrkonten-Fall aus BUG-99-1 aufloesbar: statt Mengen
                    # ueber Konten hinweg zu summieren, laesst sich je Zeile
                    # zuordnen.
                    "account": p.account,
                    "market_price": _opt(extra.marketPrice) if extra else None,
                    "market_value": _opt(extra.marketValue) if extra else None,
                    "unrealized_pnl": (
                        _opt(extra.unrealizedPNL) if extra else None
                    ),
                }
            )
        return rows

    def trading_account(self) -> str | None:
        """T1-119 — die Kennung des Depots, mit dem diese Sitzung verbunden ist.

        Duenner Aufsatz auf `_trading_account`, damit der Abgleich sie lesen
        kann, ohne an einem privaten Namen zu haengen. Dieselbe Quelle wie im
        Herzschlag: was die Plattform als `bridge_last_account_id` fuehrt, ist
        genau dieser Wert.
        """
        return self._trading_account()

    def _trading_account(self) -> str | None:
        """Das eine Konto, auf dem gehandelt wird — oder `None` bei mehreren.

        Dieselbe Regel wie in ib_insync selbst: bei genau einem verwalteten
        Konto ist es dieses, sonst laesst sich die Frage nicht entscheiden.
        Nicht zu entscheiden ist hier die ehrlichere Antwort als das erste zu
        nehmen — eine falsche Kontowahl waere ein stiller Faktor auf jede
        Bestandszahl, und niemand saehe es an den Zahlen. Dieselbe Ueberlegung
        wie bei der Waehrungsaufloesung in T1-85.
        """
        try:
            accounts = [a for a in self._ib.managedAccounts() if a]
        except Exception:  # pragma: no cover - defensiv
            return None
        return accounts[0] if len(accounts) == 1 else None

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
        Storno und Verfall trennt sie NICHT — am 2026-08-14 nach
        Handelsschluss gemessen, beide senden dieselbe Warnung 202 mit
        leerem Grund. Diese Unterscheidung faellt seit T1-96 B-1 auf der
        Plattform, ueber den Zeitpunkt gegen den Sitzungsschluss.
        """
        self._ib.cancelOrder(order)

    def all_open_trades(self) -> list[Any]:
        """T1-94-Sonde: alle offenen Auftraege, ueber alle Clients hinweg.

        Dasselbe wie `open_trades`, nur mit anderem Zweck — dort geht es um
        unsere eigenen nach einem Neustart, hier um die Frage, ob fremde
        ueberhaupt sichtbar sind. Als eigene Methode, damit die Absicht am
        Aufrufer ablesbar bleibt.
        """
        return list(self._ib.reqAllOpenOrders())

    def completed_trades(self, api_only: bool = False) -> list[Any]:
        """T1-94-Sonde: abgeschlossene Auftraege des laufenden Tages.

        `api_only=False` schliesst die von Hand in TWS gestellten ausdruecklich
        ein — so steht es im Parameter von ib_insync. IBKR haelt nur den
        laufenden Tag vor.
        """
        return list(self._ib.reqCompletedOrders(apiOnly=api_only))

    def executions(self) -> list[Any]:
        """T1-94-Sonde: die Ausfuehrungen des laufenden Tages.

        Loest den Abruf aus. Die Gebuehr steht danach noch NICHT daran — sie
        kommt als eigenes Ereignis hinterher. Dafuer `fills()`.
        """
        return list(self._ib.reqExecutions())

    def fills(self) -> list[Any]:
        """Die Ausfuehrungen aus dem Speicher von ib_insync, mit Gebuehr.

        `wrapper.commissionReport` schreibt die Gebuehr nachtraeglich in
        dasselbe Fill-Objekt (`dataclassUpdate(fill.commissionReport, ...)`).
        Wer direkt nach `reqExecutions()` liest, sieht deshalb den Feld-Default
        0.0 und haelt ihn fuer eine Messung.
        """
        return list(self._ib.fills())

    def open_trades(self) -> list[Any]:
        """Alle bei IBKR offenen Auftraege, frisch erfragt.

        `reqAllOpenOrders` fragt TWS, statt einen lokalen Zwischenspeicher zu
        lesen — nach einem Neustart der Bridge ist der leer, und genau dann
        wird diese Methode gebraucht.
        """
        return list(self._ib.reqAllOpenOrders())

    def subscribe_order_status_callback(self, cb: Any) -> None:
        """Meldet Zustandsaenderungen von Auftraegen. Ein Argument: der Auftrag.

        ## Warum hier NICHT auch `execDetailsEvent` haengt

        Bis 0.4.1 stand hier zusaetzlich `self._ib.execDetailsEvent += cb`, und
        das hat nie funktioniert: `execDetailsEvent` emittiert `(trade, fill)`,
        der Rueckruf nimmt ein Argument. eventkit faengt den TypeError ab und
        schreibt ihn samt Traceback ins Protokoll — bei **jeder** Ausfuehrung,
        seit es diese Zeile gibt.

        Der naheliegende Fix waere, den Rueckruf `*args` nehmen zu lassen. Das
        waere schlimmer als der Fehler, den er behebt:

        `execDetails` trifft ein, sobald die Ausfuehrung vorliegt — die
        Gebuehrenabrechnung kommt als eigenes, spaeteres Ereignis. Der Rueckruf
        wuerde also `filled` melden, waehrend `_sum_commission` noch nichts
        findet, und die spaetere `orderStatus`-Meldung mit derselben Aussage
        faellt in `should_report` heraus. Ergebnis: die Gebuehr, an der die
        Kostenbasis aus T1-78 haengt, ginge dauerhaft verloren.

        `orderStatusEvent` allein traegt ohnehin alles: ib_insync vergleicht
        dort den gesamten Auftragszustand, eine geaenderte Fuellmenge loest also
        ein Ereignis aus. Genau darueber sind alle Ausfuehrungen bisher
        gemeldet worden — der zweite Weg war seit jeher tot.
        """
        self._ib.orderStatusEvent += cb  # type: ignore[operator]

    def sleep(self, seconds: float) -> None:
        """ib_insync-native sleep that keeps event-loop running."""
        self._ib.sleep(seconds)
