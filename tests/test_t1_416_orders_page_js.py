"""T1-416 — die Auftragsliste im Cockpit, im echten Skript ausgefuehrt.

Gehaertet gegen das, was eine Betriebsflaeche aushalten muss: fremder Text aus
IBKR (Ablehnungsgruende) wird nie als HTML gelesen, fehlende Felder erzeugen
kein `undefined`, und eine lange Liste wird gekappt statt die Seite zu fluten.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from ordertune_bridge_ibkr.cockpit.page import PAGE_HTML


def _lauf(orders: object, tmp_path: Path) -> str:
    skript = PAGE_HTML.split("<script>", 1)[1].rsplit("</script>", 1)[0]
    teile = []
    for name in ("esc", "fmtTime", "renderOrders", "orderGroup", "orderRow"):
        treffer = re.search(r"^function " + name + r"\(.*?^\}", skript, re.S | re.M)
        assert treffer, f"{name}() nicht gefunden"
        teile.append(treffer.group(0))
    grenze = re.search(r"const ORDER_ROWS_MAX = \d+;", skript)
    assert grenze
    teile.append(grenze.group(0))
    datei = tmp_path / "orders.js"
    datei.write_text(
        "const box = {className: '', textContent: '', innerHTML: ''};\n"
        "function q() { return box; }\n"
        + "\n".join(teile)
        + f"\nrenderOrders({{orders: {json.dumps(orders)}}});\n"
        "console.log(box.innerHTML || box.textContent);\n",
        encoding="utf-8",
    )
    ergebnis = subprocess.run(["node", str(datei)], capture_output=True, text=True)
    assert ergebnis.returncode == 0, ergebnis.stderr
    return ergebnis.stdout


ZEILE = {
    "dispatchId": "d1",
    "open": True,
    "symbol": "SNDK",
    "action": "BUY",
    "qty": 15,
    "status": "At broker",
    "reason": None,
    "strategy": "S&P 500 Fear Shield",
    "purpose": "Exit",
    "orderType": "Limit",
    "price": "Limit 709.80",
    "conditions": ["Day order", "Active from 12 Nov 15:59 ET"],
    "filled": None,
    "placedAt": "2026-11-12T20:59:00+00:00",
}

braucht_node = pytest.mark.skipif(shutil.which("node") is None, reason="node fehlt")


@braucht_node
def test_zeile_traegt_strategie_preis_und_bedingungen(tmp_path: Path) -> None:
    html = _lauf([ZEILE], tmp_path)
    assert "Pending at IBKR" in html
    assert "S&amp;P 500 Fear Shield &middot; Exit" in html
    assert "Limit 709.80" in html
    assert "sent " in html
    assert "Active from 12 Nov 15:59 ET" in html
    assert "Done today" not in html


@braucht_node
def test_ibkr_text_wird_nie_als_html_gelesen(tmp_path: Path) -> None:
    boese = {**ZEILE, "open": False, "status": "Rejected", "reason": "<img src=x onerror=alert(1)>"}
    html = _lauf([boese], tmp_path)
    assert "<img" not in html
    assert "&lt;img" in html
    assert "Done today" in html


@braucht_node
def test_fehlende_felder_ergeben_kein_undefined(tmp_path: Path) -> None:
    html = _lauf([{"dispatchId": "d2"}], tmp_path)
    assert "undefined" not in html
    assert "null" not in html
    assert "Strategy unknown" in html


@braucht_node
def test_lange_liste_wird_gekappt(tmp_path: Path) -> None:
    viele = [{**ZEILE, "dispatchId": f"d{i}"} for i in range(75)]
    html = _lauf(viele, tmp_path)
    assert html.count("<li class='or'>") == 60
    assert "15 older not shown." in html


@braucht_node
def test_keine_auskunft_und_leere_liste_sind_verschieden(tmp_path: Path) -> None:
    assert "No order data yet." in _lauf(None, tmp_path)
    assert "No orders from Ordertune at IBKR today." in _lauf([], tmp_path)
