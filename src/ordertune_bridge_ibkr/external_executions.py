"""T1-94 — was im Depot geschieht, ohne dass wir es angeordnet haben.

## Warum gefragt und nicht gehorcht wird

Am 2026-08-15 und 2026-08-17 an echten fremden Ausfuehrungen gemessen: bei
laufender Bridge kommt zu einem manuell in TWS gestellten Auftrag **weder
`openOrder` noch `orderStatus` noch `execDetails`**. Zweimal geprueft, Kauf und
Verkauf, bei offenem Markt und gesetzter Master API client ID. Live kommen
ausschliesslich `position` und `updatePortfolio`.

Der erste Zuschnitt des Specs wollte den Rueckruf umbauen. Es gibt keinen
Rueckruf. Also fragt die Bridge im Heartbeat-Takt nach — der Takt existiert
ohnehin, und ein Abruf pro Minute ist der billigste Ausloeser, den es gibt.

Bewusst NICHT an eine Positionsaenderung gekoppelt: Kauf und Verkauf zwischen
zwei Takten heben sich im Bestand auf, und beide Zeilen waeren verloren.

## Die drei Angaben, an denen alles haengt

  execId    identifiziert die Ausfuehrung. Der Entdopplungsschluessel.
  permId    identifiziert den Auftrag. Klammert Teilausfuehrungen zusammen.
  orderRef  sagt, ob sie uns gehoert. Bei fremden leer.

`orderId` ist wertlos: fremde Auftraege tragen dort 0, gemessen. Jede fremde
Zeile truege dieselbe Zahl.
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

ORDER_REF_PREFIX = "ot-"

# IBKRs Seitenkennung auf unser Vokabular. Was nicht darin steht, wird nicht
# gemeldet — die Richtung eines Handels zu raten ist die eine Sache, die man
# hier auf keinen Fall tun darf.
_SIDE_MAP = {"BOT": "buy", "SLD": "sell"}

# Was gemeldet wird, wenn sich der Ordertyp nicht ermitteln laesst. IBKR sagt
# das nie — der Wert ist damit eindeutig als "wir wussten es nicht" lesbar und
# nicht als Messung. Die Plattform bildet ihn auf `market` ab.
UNKNOWN_ORDER_TYPE = "UNKNOWN"


def is_ours(order_ref: Any) -> bool:
    """Traegt die Ausfuehrung unseren Auftragsvermerk?"""
    return bool(order_ref) and str(order_ref).startswith(ORDER_REF_PREFIX)


def order_types_by_perm_id(trades: list[Any]) -> dict[str, str]:
    """`permId` → roher Ordertyp, aus offenen und abgeschlossenen Auftraegen.

    Die Ausfuehrung selbst traegt den Ordertyp nicht; IBKR fuehrt ihn am
    Auftrag. Ueber die `permId` laesst er sich dazuholen.
    """
    out: dict[str, str] = {}
    for trade in trades:
        order = getattr(trade, "order", None)
        perm_id = getattr(order, "permId", None)
        order_type = getattr(order, "orderType", None)
        if perm_id and order_type:
            out[str(perm_id)] = str(order_type)
    return out


def has_commission_report(fill: Any) -> bool:
    """Ist die Gebuehrenabrechnung schon eingetroffen?

    `CommissionReport()` wird beim Anlegen des Fills mit Vorgabewerten
    erzeugt — `commission = 0.0` und `execId = ''`. Die 0.0 ist deshalb KEIN
    Messwert, sondern der Vorgabewert; genau darauf ist die Diagnose-Sonde am
    2026-08-17 hereingefallen.

    Unterscheidbar ist es allein an der `execId`: sie bleibt leer, bis
    `wrapper.commissionReport` den Bericht nachtraeglich einschreibt.
    """
    report = getattr(fill, "commissionReport", None)
    return bool(getattr(report, "execId", ""))


def external_execution_bodies(
    fills: list[Any],
    order_types: dict[str, str],
    already_reported: set[str],
) -> list[dict[str, Any]]:
    """Waehlt die fremden Ausfuehrungen aus und formt die Meldekoerper.

    Rein: keine Netzwerk-, keine IBKR-Zugriffe. Damit ist die Auswahl — die
    Stelle, an der ein Fehler doppelten Bestand erzeugen wuerde — ohne TWS
    pruefbar.
    """
    bodies: list[dict[str, Any]] = []
    for fill in fills:
        ex = getattr(fill, "execution", None)
        if ex is None:
            continue

        exec_id = str(getattr(ex, "execId", "") or "")
        if not exec_id or exec_id in already_reported:
            continue

        # Der Riegel gegen doppelten Bestand: was unseren Vermerk traegt, hat
        # seinen eigenen Weg ueber /orders/{id}/result. Hier zusaetzlich
        # gemeldet, stuende es zweimal in den Buechern.
        if is_ours(getattr(ex, "orderRef", None)):
            continue

        side = _SIDE_MAP.get(str(getattr(ex, "side", "")).upper())
        if side is None:
            log.warning(
                "Execution %s has an unknown side %r — not reported. Please "
                "report this, the side table is incomplete.",
                exec_id,
                getattr(ex, "side", None),
            )
            continue

        try:
            qty = float(getattr(ex, "shares", 0) or 0)
            price = float(getattr(ex, "price", 0) or 0)
        except (TypeError, ValueError):
            continue
        if qty <= 0 or price <= 0:
            continue

        executed_at = getattr(ex, "time", None)
        if executed_at is None:
            continue

        perm_id = str(getattr(ex, "permId", "") or "")
        if not perm_id:
            continue

        body: dict[str, Any] = {
            "brokerExecId": exec_id,
            "brokerPermId": perm_id,
            "symbol": str(getattr(getattr(fill, "contract", None), "symbol", "")),
            "side": side,
            "qty": qty,
            "price": price,
            "executedAt": _wire_time(executed_at),
            "orderType": order_types.get(perm_id, UNKNOWN_ORDER_TYPE),
            "orderRef": str(getattr(ex, "orderRef", "") or ""),
        }
        if not body["symbol"]:
            continue

        # Die Gebuehr wird nur mitgeschickt, wenn sie wirklich vorliegt. Fehlt
        # sie, bleibt die Spalte auf der Plattform NULL — eine gebuchte 0 waere
        # eine Behauptung ueber geflossenes Geld.
        if has_commission_report(fill):
            try:
                body["commissionUsd"] = float(
                    getattr(fill.commissionReport, "commission", 0.0)
                )
            except (TypeError, ValueError):
                pass

        bodies.append(body)

    return bodies


def _wire_time(value: Any) -> str:
    """Zeitstempel in die kanonische Z-Form, wie der Rest des Drahtformats.

    Python liefert `+00:00`, die Plattform validiert gegen `Z` und wiese den
    Offset mit 422 ab — derselbe Fallstrick, den T1-78 an Ack und Ergebnis
    schon einmal gefunden hat.
    """
    try:
        text = value.isoformat()
    except AttributeError:
        text = str(value)
    return text.replace("+00:00", "Z")
