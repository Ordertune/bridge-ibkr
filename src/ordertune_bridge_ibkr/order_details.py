"""T1-416 — eine Auftragszeile, die ein Mensch nachvollziehen kann.

Owner 2026-11-16: das Cockpit zeigte je Auftrag nur Symbol, Seite, Menge und
Zustand. Wozu er gehoert, zu welchem Preis und unter welcher Bedingung er
steht, war nur in TWS zu sehen.

Alles hier kommt aus dem, was IBKR ueber den Auftrag selbst fuehrt (`Order`,
`OrderStatus`), plus zwei Angaben der Plattform, wenn sie mitkamen: der volle
Strategiename und ob es ein Ein- oder Ausstieg ist. Fehlen sie — nach einem
Neustart der Bridge, oder bei einer Plattform ohne das Feld —, steht die
Strategie aus dem Auftragsvermerk da (T1-109, gekuerzt auf dessen Platz).

Rein und ohne ib_insync, damit die Zusicherungen ohne TWS laufen.
"""

from __future__ import annotations

import threading
from datetime import datetime
from typing import Any

from .order_reference import ORDER_REF_PREFIX, dispatch_id_from_order_ref

#: IBKRs Wert fuer „nicht gesetzt" bei Preisfeldern (`UNSET_DOUBLE`).
_UNSET_GRENZE = 1e300

_ORDER_TYPES = {
    "LMT": "Limit",
    "MKT": "Market",
    "MOC": "Market on close",
    "LOC": "Limit on close",
    "MOO": "Market on open",
    "LOO": "Limit on open",
    "STP": "Stop",
    "STP LMT": "Stop limit",
}

_TIF = {
    "DAY": "Day order",
    "GTC": "Good till cancelled",
    "GTD": "Good till date",
    "OPG": "Opening auction",
    "IOC": "Immediate or cancel",
}

_PURPOSE = {"entry": "Entry", "exit": "Exit"}

_LOCK = threading.Lock()
_FROM_PLATFORM: dict[str, dict[str, str]] = {}


def remember(dispatch_id: str, intent: dict[str, Any]) -> None:
    """Haelt fest, was die Plattform zu diesem Auftrag gesagt hat."""
    angaben: dict[str, str] = {}
    name = intent.get("strategyName")
    if isinstance(name, str) and name.strip():
        angaben["strategy"] = name.strip()
    zweck = _PURPOSE.get(str(intent.get("intent") or ""))
    if zweck:
        angaben["purpose"] = zweck
    if angaben:
        with _LOCK:
            _FROM_PLATFORM[dispatch_id] = angaben


def clear() -> None:
    with _LOCK:
        _FROM_PLATFORM.clear()


def strategy_from_order_ref(order_ref: object) -> str | None:
    """Der Strategieteil aus `ot-<SYMBOL>-<SIGNAL>-<Strategie>-<uuid>`."""
    if not isinstance(order_ref, str):
        return None
    dispatch_id = dispatch_id_from_order_ref(order_ref)
    if dispatch_id is None:
        return None
    etikett = order_ref.strip()[len(ORDER_REF_PREFIX) : -len(dispatch_id)].strip("-")
    teile = etikett.split("-", 2)
    if len(teile) < 3 or not teile[2]:
        return None
    return teile[2].replace("_", " ")


def _preis(wert: object) -> float | None:
    try:
        zahl = float(wert)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if zahl != zahl or zahl <= 0 or zahl >= _UNSET_GRENZE:
        return None
    return zahl


def _text(wert: object) -> str | None:
    s = str(wert).strip() if wert is not None else ""
    return s or None


def _price_text(order_type: str, lmt: float | None, aux: float | None) -> str:
    teile = []
    if aux is not None and order_type in ("STP", "STP LMT"):
        teile.append(f"Stop {aux:.2f}")
    if lmt is not None and order_type not in ("MKT", "MOC", "MOO", "STP"):
        teile.append(f"Limit {lmt:.2f}")
    return " · ".join(teile) if teile else "At market"


_MONATE = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
_NEW_YORK = {"US/Eastern", "America/New_York", "EST", "EST5EDT"}


def _zeitpunkt(wert: str) -> str:
    """`20261112 15:59:00 US/Eastern` → `12 Nov 15:59 ET`; Unbekanntes bleibt roh."""
    teile = wert.split()
    if len(teile) < 2 or len(teile[0]) != 8 or not teile[0].isdigit():
        return wert
    tag, zeit = teile[0], teile[1]
    try:
        monat = _MONATE[int(tag[4:6]) - 1]
    except (ValueError, IndexError):
        return wert
    zone = teile[2] if len(teile) > 2 else ""
    zone = "ET" if zone in _NEW_YORK else zone
    return f"{int(tag[6:8])} {monat} {zeit[:5]} {zone}".strip()


def _conditions(order: Any) -> list[str]:
    bedingungen = []
    tif = _text(getattr(order, "tif", None))
    if tif:
        bedingungen.append(_TIF.get(tif, tif))
    after = _text(getattr(order, "goodAfterTime", None))
    if after:
        bedingungen.append(f"Active from {_zeitpunkt(after)}")
    until = _text(getattr(order, "goodTillDate", None))
    if until:
        bedingungen.append(f"Valid until {_zeitpunkt(until)}")
    if _text(getattr(order, "ocaGroup", None)):
        bedingungen.append("One-cancels-all group")
    if getattr(order, "outsideRth", False) is True:
        bedingungen.append("Outside regular hours")
    return bedingungen


def _placed_at(trade: Any) -> str | None:
    for eintrag in getattr(trade, "log", None) or []:
        zeit = getattr(eintrag, "time", None)
        if isinstance(zeit, datetime):
            return zeit.isoformat()
    return None


def describe(dispatch_id: str, trade: Any) -> dict[str, Any]:
    """Die lesbaren Angaben zu einem Auftrag, fuer die Zeile im Cockpit."""
    order = getattr(trade, "order", None)
    status = getattr(trade, "orderStatus", None)
    with _LOCK:
        von_plattform = dict(_FROM_PLATFORM.get(dispatch_id, {}))

    order_type = str(getattr(order, "orderType", "") or "").upper()
    lmt = _preis(getattr(order, "lmtPrice", None))
    aux = _preis(getattr(order, "auxPrice", None))

    gefuellt = _preis(getattr(status, "filled", None))
    durchschnitt = _preis(getattr(status, "avgFillPrice", None))
    filled = None
    if gefuellt is not None:
        menge = f"{gefuellt:g}"
        filled = f"{menge} @ {durchschnitt:.2f}" if durchschnitt is not None else menge

    return {
        "strategy": von_plattform.get("strategy")
        or strategy_from_order_ref(getattr(order, "orderRef", None)),
        "purpose": von_plattform.get("purpose"),
        "orderType": _ORDER_TYPES.get(order_type, order_type or None),
        "price": _price_text(order_type, lmt, aux),
        "conditions": _conditions(order),
        "filled": filled,
        "placedAt": _placed_at(trade),
    }
