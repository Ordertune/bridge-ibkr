"""T1-233 — storniert IBKR die Kinder einer Klammer von sich aus gegenseitig?

## Die Frage, die dieses Skript beantwortet

Eine Intraday-Klammer besteht aus einem Einstieg und ZWEI Ausstiegen: einem
Stop und einem Schlussauktions-Auftrag auf dieselbe Position. Fuellt der Stop
um 11:00, MUSS der MOC verschwinden — sonst wird dieselbe Position zweimal
verkauft.

Ob IBKR das von sich aus tut, sobald zwei Kinder an demselben `parentId`
haengen, oder ob beide zusaetzlich einen gemeinsamen OCA-Gruppennamen
brauchen, steht in keiner Zeile dieses Hauses. Der Referenzentwurf des Owners
setzt **keine** Gruppe.

Solange die Antwort fehlt, setzt die Plattform die Gruppe — fail-closed. Eine
doppelte Verknuepfung ist unschoen; eine fehlende verkauft zweimal.

## Wie gemessen wird

Zwei Durchgaenge, und der Unterschied ist die ganze Antwort:

    Durchgang A   OHNE eigene Gruppe   -> meldet IBKR selbst eine zurueck?
    Durchgang B   MIT  eigener Gruppe  -> die Gegenprobe

Gelesen wird, was IBKR ueber `openOrder` zurueckmeldet. Traegt Durchgang A
eine Gruppe, die wir nicht gesetzt haben, dann verknuepft IBKR selbst.

## Es fuellt nichts

Der Einstieg ist ein Kauflimit weit UNTER dem Markt — er wird nicht
marktgaengig, also werden die Kinder nie scharf. Damit laesst sich die
Verknuepfung pruefen, ohne einen einzigen Handel auszuloesen. Am Ende wird
alles storniert.

## Nur gegen ein Papierkonto

Port 7497 (TWS) oder 4002 (Gateway). Alles andere lehnt das Skript ab — ein
Echtgeldkonto ist kein Messgeraet.

## Aufruf auf dem Rechner, auf dem die TWS laeuft

    python3 tools/bracket_oca_probe.py
    python3 tools/bracket_oca_probe.py --symbol F --quantity 1
    python3 tools/bracket_oca_probe.py --port 4002      # Papier-Gateway

Es braucht nichts ausser `ib_insync` — dieselbe Bibliothek, die die Bridge
ohnehin benutzt. Damit misst die Sonde mit demselben Client wie der Ernstfall.
"""
from __future__ import annotations

import argparse
import time

from ib_insync import IB, Contract, Order, Trade

TWS_HOST = "127.0.0.1"
# Papier-TWS und Papier-Gateway. Alles andere ist ein Echtgeldkonto.
PAPIER_PORTS = {7497: "Papier-TWS", 4002: "Papier-Gateway"}
# Eine Kennung, die sonst niemand benutzt: die Bridge faehrt 101, das
# Owner-Testskript 994. Zwei Clients mit derselben Kennung werfen sich
# gegenseitig aus der TWS (Fehler 326).
CLIENT_ID = 993

# Weit vom Markt. Der Einstieg fuellt nicht, also werden die Kinder nie scharf.
ENTRY_LIMIT = 1.00
STOP_TRIGGER = 0.50


def kontrakt(symbol: str) -> Contract:
    c = Contract()
    c.symbol = symbol
    c.secType = "STK"
    c.exchange = "SMART"
    c.currency = "USD"
    return c


def order(
    action: str,
    order_type: str,
    qty: int,
    *,
    lmt: float = 0.0,
    aux: float = 0.0,
    transmit: bool,
    oca: str = "",
) -> Order:
    o = Order()
    o.action = action
    o.totalQuantity = float(qty)
    o.orderType = order_type
    o.tif = "DAY"
    o.lmtPrice = lmt
    o.auxPrice = aux
    o.transmit = transmit
    # Ohne diese beiden lehnt IBKR einen API-Auftrag auf manchen Konten ab.
    o.eTradeOnly = False
    o.firmQuoteOnly = False
    if oca:
        o.ocaGroup = oca
        # 3 = „reduce, non-block". Die Begruendung steht in T1-106: auf einem
        # Cash-Konto sind zwei Verkaeufe ueber je die volle Menge gegen eine
        # gehaltene Position ein moeglicher Leerverkauf, und Typ 1 laesst beide
        # in voller Groesse stehen.
        o.ocaType = 3
    return o


def durchgang(ib: IB, symbol: str, qty: int, oca: str, warten: float) -> dict:
    """Stellt eine Klammer, liest zurueck, was IBKR meldet, und raeumt auf."""
    c = kontrakt(symbol)
    eltern = order("BUY", "LMT", qty, lmt=ENTRY_LIMIT, transmit=False)
    eltern_trade: Trade = ib.placeOrder(c, eltern)
    ib.sleep(1)

    eltern_id = eltern_trade.order.orderId
    stop = order("SELL", "STP", qty, aux=STOP_TRIGGER, transmit=False, oca=oca)
    stop.parentId = eltern_id
    stop_trade: Trade = ib.placeOrder(c, stop)

    # Nur das LETZTE Kind traegt `transmit=True` — erst dann uebertraegt TWS
    # die ganze Gruppe.
    moc = order("SELL", "MOC", qty, transmit=True, oca=oca)
    moc.parentId = eltern_id
    moc_trade: Trade = ib.placeOrder(c, moc)

    ib.sleep(warten)

    ergebnis = {
        "eltern": eltern_trade,
        "stop": stop_trade,
        "moc": moc_trade,
    }
    for t in (moc_trade, stop_trade, eltern_trade):
        try:
            ib.cancelOrder(t.order)
        except Exception as e:  # noqa: BLE001
            print(f"    (Storno von {t.order.orderId} schlug fehl: {e})")
    ib.sleep(2)
    return ergebnis


def zeige(titel: str, e: dict) -> None:
    print(f"\n  {titel}")
    for name in ("eltern", "stop", "moc"):
        t: Trade = e[name]
        o = t.order
        gruppe = getattr(o, "ocaGroup", "") or "(leer)"
        print(
            f"    {name:7} id={o.orderId:<6} {o.orderType:4} "
            f"parentId={getattr(o, 'parentId', 0):<6} "
            f"transmit={str(o.transmit):5} "
            f"ocaGroup={gruppe!r:34} ocaType={getattr(o, 'ocaType', 0)} "
            f"aux={o.auxPrice} status={t.orderStatus.status}"
        )
        for log in t.log[-2:]:
            if log.errorCode:
                print(f"            ! {log.errorCode}: {log.message}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--symbol", default="F")
    p.add_argument("--quantity", type=int, default=1)
    p.add_argument("--port", type=int, default=7497)
    p.add_argument("--host", default=TWS_HOST)
    p.add_argument("--wait", type=float, default=6.0)
    args = p.parse_args()

    if args.port not in PAPIER_PORTS:
        erlaubt = ", ".join(f"{k} ({v})" for k, v in sorted(PAPIER_PORTS.items()))
        print(
            f"Abbruch: Port {args.port} ist keiner der Papier-Ports.\n"
            f"Erlaubt: {erlaubt}.\n"
            "Ein Echtgeldkonto ist kein Messgeraet."
        )
        return

    ib = IB()
    try:
        ib.connect(args.host, args.port, clientId=CLIENT_ID, timeout=10)
    except Exception as e:  # noqa: BLE001
        print(f"Keine Verbindung zu {args.host}:{args.port} — laeuft die TWS? ({e})")
        return

    print(
        "T1-233 — storniert IBKR die Kinder einer Klammer von sich aus?\n"
        f"{PAPIER_PORTS[args.port]} auf {args.host}:{args.port}, "
        f"{args.symbol} x{args.quantity}.\n"
        f"Es fuellt nichts: der Einstieg ist ein Kauflimit zu {ENTRY_LIMIT:.2f}, "
        "weit unter dem Markt."
    )

    try:
        a = durchgang(ib, args.symbol, args.quantity, "", args.wait)
        zeige("Durchgang A — OHNE eigene OCA-Gruppe", a)

        name = f"OCA_PROBE_{int(time.time())}"
        b = durchgang(ib, args.symbol, args.quantity, name, args.wait)
        zeige(f"Durchgang B — MIT eigener Gruppe {name!r} (Gegenprobe)", b)

        stop_a = getattr(a["stop"].order, "ocaGroup", "") or ""
        moc_a = getattr(a["moc"].order, "ocaGroup", "") or ""

        print("\n--- Die Antwort ---")
        if stop_a and stop_a == moc_a:
            print(
                f"  IBKR verknuepft SELBST: beide Kinder melden {stop_a!r} zurueck,\n"
                "  obwohl Durchgang A keine Gruppe gesetzt hat.\n"
                "\n"
                "  -> Eine eigene Gruppe waere eine zweite Verknuepfung mit derselben\n"
                "     Bedeutung. T1-233 Entscheidung 8 kann auf 'nicht setzen' gehen,\n"
                "     und `legeKinderAn` verliert die Zeile mit dem Gruppennamen."
            )
        else:
            print(
                "  IBKR verknuepft NICHT von sich aus — Durchgang A meldet keine\n"
                "  gemeinsame Gruppe zurueck.\n"
                "\n"
                "  -> Beide Kinder BRAUCHEN den gemeinsamen Gruppennamen. Ohne ihn\n"
                "     verkauft ein um 11:00 gefuellter Stop die Position, und der MOC\n"
                "     verkauft sie in der Schlussauktion ein zweites Mal.\n"
                "     T1-233 Entscheidung 8 bleibt wie gebaut."
            )
        print(
            "\n  Durchgang B zeigt zur Gegenprobe, dass eine gesetzte Gruppe\n"
            "  ueberhaupt durchkommt — kaeme sie dort NICHT zurueck, waere das ein\n"
            "  eigener Befund."
        )
    finally:
        ib.disconnect()


if __name__ == "__main__":
    main()
