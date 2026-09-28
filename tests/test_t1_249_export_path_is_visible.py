r"""T1-249 (Nachtrag) — der Pfad steht da, wo ein Mensch ihn vergleichen kann.

## Der gemessene Fall, 2026-09-28

Auf dem VPS des Owners lag ein vollstaendiger Export. Die Bridge las ihn nicht,
und die Suche nach dem Grund ging ueber drei Ecken — weil **niemand sehen
konnte, welchen Pfad die Bridge ueberhaupt liest.**

Die Ursachenkette, in der Reihenfolge, in der sie aufgefallen ist:

  1. `bridge.env` trug keine Zeile `TWS_EXPORT_DIR`. Die Vorlage schrieb sie
     nicht.
  2. Also galt die Vorgabe aus `config.py` — und die kennt nur der Quelltext.
  3. Der Owner pflegte die Zeile von Hand nach. Auch dann blieb die Frage
     offen, ob sein Wert derselbe ist, den die TWS beschreibt.

Der Vergleich zwischen dem Feld in der TWS und dem Pfad in der Bridge ist der
eine Handgriff, den wir dem Kunden nicht abnehmen koennen: die TWS entscheidet,
wohin sie schreibt, die Bridge entscheidet, wo sie liest, und keine Seite sieht
die andere. Ein Pfad, der nur im Programm steht, macht diesen Vergleich
unmoeglich.

**Ein Vorgabewert, den niemand sieht, ist ein Vorgabewert, den niemand
berichtigen kann.** Das ist die Regel, die hier gepruefte wird.
"""
from __future__ import annotations

from pathlib import Path

from ordertune_bridge_ibkr import pairing, trade_reports
from ordertune_bridge_ibkr.cockpit import setup as setup_mod
from ordertune_bridge_ibkr.cockpit.page import PAGE_HTML


# ── 1) Die Vorlage schreibt die Zeile ────────────────────────────────────────


def test_die_vorlage_nennt_den_exportpfad(tmp_path: Path) -> None:
    """Der Kern des Befundes: die Zeile fehlte ueberhaupt."""
    ziel = tmp_path / "bridge.env"

    ergebnis = pairing.write_credentials(
        ziel,
        api_base="https://t1.ordertune.com",
        token="tok",
        connection_id="conn",
    )

    assert ergebnis["ok"] is True
    text = ziel.read_text(encoding="utf-8")
    assert f"TWS_EXPORT_DIR={trade_reports.standard_verzeichnis()}" in text


def test_die_vorlage_erklaert_den_leeren_dateinamen(tmp_path: Path) -> None:
    """Die Falle, die den Befund erzeugt hat, steht als Anleitung daneben.

    Die TWS schreibt ohne Dateiendung, WEIL wir den leeren Dateinamen
    verlangen. Wer die Zeile spaeter liest, soll beides zusammen sehen.
    """
    ziel = tmp_path / "bridge.env"
    pairing.write_credentials(
        ziel, api_base="https://x", token="t", connection_id="c"
    )

    text = ziel.read_text(encoding="utf-8")
    assert "Export Reports" in text
    assert "Export filename" in text


def test_die_geschriebene_datei_laedt_sich_selbst(tmp_path: Path) -> None:
    """Die Vorlage muss gueltig bleiben — sonst startet die Bridge nicht.

    Eine Vorlage mit einem Formatierungsfehler faellt erst beim Kunden auf, und
    zwar an einer Bridge, die gar nicht mehr hochkommt.
    """
    from ordertune_bridge_ibkr import env_file

    ziel = tmp_path / "bridge.env"
    pairing.write_credentials(
        ziel, api_base="https://x", token="t", connection_id="c"
    )

    werte = env_file.parse(ziel.read_text(encoding="utf-8"))
    assert werte["ORDERTUNE_BRIDGE_TOKEN"] == "t"
    assert werte["IBKR_TWS_PORT"] == "7497"
    assert "TWS_EXPORT_DIR" in werte
    assert "{" not in ziel.read_text(encoding="utf-8")


# ── 2) Eine vorhandene Datei bekommt die Zeile nachgetragen ──────────────────


def test_eine_alte_datei_bekommt_die_zeile_nachgetragen(tmp_path: Path) -> None:
    """Der Fall des Owners: gekoppelt mit einer Fassung vor 0.29.2.

    Eine erneute Kopplung ersetzt sonst nur die drei Identitaetszeilen — und
    der Exportpfad bliebe fuer immer unsichtbar.
    """
    ziel = tmp_path / "bridge.env"
    ziel.write_text(
        "ORDERTUNE_API_BASE=https://alt\n"
        "ORDERTUNE_BRIDGE_TOKEN=alt\n"
        "ORDERTUNE_BRIDGE_CONNECTION_ID=alt\n"
        "IBKR_TWS_PORT=7496\n",
        encoding="utf-8",
    )

    pairing.write_credentials(
        ziel, api_base="https://neu", token="neu", connection_id="neu"
    )

    text = ziel.read_text(encoding="utf-8")
    assert f"TWS_EXPORT_DIR={trade_reports.standard_verzeichnis()}" in text
    # Und der Port des Nutzers bleibt, wie er war.
    assert "IBKR_TWS_PORT=7496" in text


def test_ein_selbst_gesetzter_pfad_wird_nicht_ueberschrieben(tmp_path: Path) -> None:
    """Eine erneute Kopplung darf keine Nutzerentscheidung zurueckdrehen.

    Der Owner hat die Zeile von Hand gepflegt. Haette die Kopplung sie auf die
    Vorgabe zurueckgesetzt, waere aus einem sichtbaren Pfad ein falscher
    geworden — schlimmer als gar keiner.
    """
    ziel = tmp_path / "bridge.env"
    ziel.write_text(
        "ORDERTUNE_API_BASE=https://alt\n"
        "ORDERTUNE_BRIDGE_TOKEN=alt\n"
        "ORDERTUNE_BRIDGE_CONNECTION_ID=alt\n"
        "TWS_EXPORT_DIR=D:\\eigener\\Ordner\n",
        encoding="utf-8",
    )

    pairing.write_credentials(
        ziel, api_base="https://neu", token="neu", connection_id="neu"
    )

    text = ziel.read_text(encoding="utf-8")
    assert "TWS_EXPORT_DIR=D:\\eigener\\Ordner" in text
    assert text.count("TWS_EXPORT_DIR") == 1


# ── 3) Die Auskunft unterscheidet Entscheidung von Vorgabe ───────────────────


def test_ohne_eintrag_gilt_die_vorgabe_und_sagt_es(tmp_path: Path) -> None:
    auskunft = setup_mod.export_auskunft({})

    assert auskunft["configured"] == ""
    assert auskunft["effective"] == trade_reports.standard_verzeichnis()
    assert auskunft["default"] == trade_reports.standard_verzeichnis()


def test_ein_eintrag_gilt_und_wird_als_eintrag_gefuehrt(tmp_path: Path) -> None:
    ordner = tmp_path / "IBExport"
    ordner.mkdir()
    (ordner / "trades.20260925").write_text("Symbol;\n", encoding="utf-8")

    auskunft = setup_mod.export_auskunft({"TWS_EXPORT_DIR": str(ordner)})

    assert auskunft["configured"] == str(ordner)
    assert auskunft["effective"] == str(ordner)


def test_die_auskunft_traegt_das_urteil_der_pruefung(tmp_path: Path) -> None:
    """Dasselbe Urteil wie im Protokoll, nicht ein zweites daneben."""
    fehlt = tmp_path / "gibt-es-nicht"

    auskunft = setup_mod.export_auskunft({"TWS_EXPORT_DIR": str(fehlt)})

    assert auskunft["state"] == "no_dir"
    assert str(fehlt) in auskunft["detail"]


def test_die_auskunft_nennt_den_pfad_auch_ohne_bridge_env(tmp_path: Path) -> None:
    """Im Assistenten gibt es noch keine Datei — den Pfad aber schon.

    Er dort zu zeigen ist der ganze Sinn: der Kunde traegt ihn in die TWS ein,
    BEVOR er zum ersten Mal auf eine fehlende Fuellung wartet.
    """
    werte = setup_mod.current_values(tmp_path / "gibt-es-nicht")

    assert werte["exists"] is False
    assert werte["export"]["effective"] == trade_reports.standard_verzeichnis()


def test_die_einstellungen_tragen_die_auskunft(tmp_path: Path) -> None:
    ziel = tmp_path / "bridge.env"
    ziel.write_text("TWS_EXPORT_DIR=C:\\IBExport\n", encoding="utf-8")

    werte = setup_mod.current_values(ziel)

    assert werte["export"]["configured"] == "C:\\IBExport"


# ── 4) Die Flaeche zeigt ihn an beiden Stellen ───────────────────────────────


def test_der_assistent_hat_einen_schritt_fuer_die_uebergabe() -> None:
    assert 's5dir' in PAGE_HTML
    assert "Hand the folder to TWS" in PAGE_HTML


def test_die_einstellungen_haben_ein_feld_fuer_den_pfad() -> None:
    assert 'id="f-expdir"' in PAGE_HTML
    assert "Trade reports from TWS" in PAGE_HTML


def test_die_flaeche_sagt_wo_der_pfad_geaendert_wird() -> None:
    """Ein angezeigter Pfad ohne den Ort zum Aendern ist eine halbe Auskunft."""
    assert "TWS_EXPORT_DIR in bridge.env" in PAGE_HTML


def test_der_leere_ordner_gilt_im_assistenten_als_bestanden() -> None:
    """T1-206, woertlich: ein leerer Ordner ist keine Anschuldigung.

    Direkt nach der Einrichtung hat noch nichts gefuellt, also gibt es nichts
    zu exportieren. Wer hier „Fehler" sagt, verbrennt die naechste Warnung mit.
    """
    assert 'e.state === "ok" || e.state === "no_file"' in PAGE_HTML
