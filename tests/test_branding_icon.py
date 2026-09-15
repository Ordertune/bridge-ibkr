"""T1-182 — die EXE traegt die Marke, nicht die Programmiersprache.

## Was hier bewacht wird

Jede Fassung bis einschliesslich 0.23.2 lieferte mit dem **Python-Symbol**
aus. Der Grund stand in `build.py`:

    icon = root / "assets" / "icon.ico"
    if icon.exists():
        cmd.extend(["--icon", str(icon)])

`assets/` war ein leeres Verzeichnis. Die Bedingung war also immer falsch, der
Schritt fiel weg, und PyInstaller nahm seine Voreinstellung — sein eigenes
Python-Symbol. Es hat sieben Monate niemand gemerkt, weil ein uebersprungener
Schritt nichts sagt und kein Test je in die gebaute Datei gesehen hat.

Die Tests hier decken beide Haelften ab: dass die Datei da ist **und** dass
ihr Fehlen kuenftig laut waere. Die zweite Haelfte ist die wichtigere — eine
Datei kann wieder verschwinden, eine stille Bedingung bringt sie nicht zurueck.
"""
from __future__ import annotations

import base64
import importlib.util
import io
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ICON = ROOT / "assets" / "icon.ico"

# Aus dem Design-System: Tinte und der eine Akzent. Gleiche Werte wie im
# Cockpit-Glyph, aus dem die Datei erzeugt wird.
CHARTREUSE = (193, 255, 62)
INK = (9, 9, 9)

ERWARTETE_GROESSEN = {16, 24, 32, 48, 64, 128, 256}


def ico_eintraege(raw: bytes) -> list[tuple[int, bytes]]:
    """(Kantenlaenge, Nutzlast) je Rahmen — ohne Bildbibliothek."""
    assert raw[:4] == b"\0\0\1\0", "keine ICO-Datei"
    count = int.from_bytes(raw[4:6], "little")
    out = []
    for i in range(count):
        e = 6 + i * 16
        breite = raw[e] or 256          # 0 bedeutet 256
        laenge = int.from_bytes(raw[e + 8:e + 12], "little")
        offset = int.from_bytes(raw[e + 12:e + 16], "little")
        out.append((breite, raw[offset:offset + laenge]))
    return out


def test_das_symbol_ist_ueberhaupt_da() -> None:
    """Die Datei, deren Fehlen das Python-Symbol ausgeliefert hat."""
    assert ICON.exists(), (
        "assets/icon.ico fehlt. Ohne sie baut PyInstaller mit dem "
        "Python-Symbol. Wiederherstellen: python tools/make_icon.py"
    )


def test_alle_windows_groessen_sind_drin() -> None:
    """Fehlt eine Groesse, skaliert Windows selbst — sichtbar schlechter."""
    groessen = {n for n, _ in ico_eintraege(ICON.read_bytes())}

    assert groessen == ERWARTETE_GROESSEN, (
        f"Groessen im ICO: {sorted(groessen)}, erwartet "
        f"{sorted(ERWARTETE_GROESSEN)}"
    )


def test_die_kleinen_groessen_sind_unkomprimiert() -> None:
    """Bis 128 als DIB, nur 256 als PNG.

    Der Kunde bedient den VPS ueber RDP, und dort ist die PNG-Ikonenschiene
    fuer kleine Groessen die unzuverlaessige — ein leerer Rahmen in der
    entfernten Sitzung waere derselbe Befund wie das Python-Symbol, nur
    schwerer zu finden.
    """
    for groesse, nutzlast in ico_eintraege(ICON.read_bytes()):
        ist_png = nutzlast[:8] == b"\x89PNG\r\n\x1a\n"
        if groesse == 256:
            assert ist_png, "256 sollte PNG sein — als DIB waere es 256 KB"
        else:
            assert not ist_png, (
                f"{groesse}px liegt als PNG vor; unter RDP kann dieser Rahmen "
                "leer bleiben. `PNG_FROM` in tools/make_icon.py pruefen."
            )


def test_es_ist_die_marke_und_kein_platzhalter() -> None:
    """Chartreuse auf Tinte — sonst ist es irgendein Bild, nur nicht unseres.

    Geprueft wird am 32er-Rahmen, weil der als DIB vorliegt und sich ohne
    Bildbibliothek lesen laesst: 40 Byte Kopf, danach BGRA von unten nach oben.
    """
    rahmen = dict(ico_eintraege(ICON.read_bytes()))
    pixel = rahmen[32][40:]

    # BGRA -> (R, G, B)
    farben = {tuple(pixel[i:i + 3][::-1]) for i in range(0, len(pixel), 4)}

    assert INK in farben, "die schwarze Kachel fehlt"
    assert any(
        abs(r - CHARTREUSE[0]) < 12 and abs(g - CHARTREUSE[1]) < 12
        and abs(b - CHARTREUSE[2]) < 12
        for r, g, b in farben
    ), "kein Chartreuse (#C1FF3E) im Symbol gefunden — Marke stimmt nicht"


def test_ein_fehlendes_symbol_ist_ein_baufehler() -> None:
    """Der eigentliche Befund: der Rueckfall darf nicht mehr still sein.

    Das ist die Haelfte, die den Fehler wiederholbar verhindert. Eine
    committete Datei kann wieder verschwinden; eine Bedingung, die ihr Fehlen
    stillschweigend hinnimmt, liefert dann erneut das Python-Symbol aus.
    """
    quelle = (ROOT / "build.py").read_text(encoding="utf-8")

    assert "if icon.exists():" not in quelle, (
        "build.py ueberspringt das Symbol wieder stillschweigend — genau die "
        "Bedingung, die das Python-Symbol bis 0.23.2 ausgeliefert hat"
    )
    assert "if not icon.exists():" in quelle, (
        "build.py muss bei fehlendem Symbol abbrechen, nicht weiterbauen"
    )
    assert "verify_icon" in quelle, (
        "`--icon` mitzugeben ist kein Beleg — die gebaute EXE muss gelesen "
        "werden"
    )


def test_das_symbol_stammt_aus_dem_design_system() -> None:
    """Regenerieren muss dieselbe Datei ergeben.

    Damit kann das ICO nicht unbemerkt von `cockpit/assets.py:ICON_PNG`
    wegdriften — das ist laut Design-System das einzige erlaubte Marken-Glyph,
    und zwei Marken-Bilder mit getrennter Herkunft waeren die zweite Stelle,
    an der die Marke falsch werden kann.
    """
    pytest.importorskip(
        "PIL", reason="Pillow ist ein Werkzeug fuer tools/, keine Laufzeit-Abhaengigkeit"
    )
    from PIL import Image

    spec = importlib.util.spec_from_file_location(
        "_ot_assets",
        ROOT / "src" / "ordertune_bridge_ibkr" / "cockpit" / "assets.py",
    )
    assets = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(assets)

    quelle = Image.open(io.BytesIO(base64.b64decode(assets.ICON_PNG))).convert("RGBA")
    erwartet = dict(ico_eintraege(ICON.read_bytes()))

    for groesse, nutzlast in erwartet.items():
        if groesse == 256:
            continue  # PNG-Kodierung ist nicht Byte-für-Byte reproduzierbar
        neu = quelle.resize((groesse, groesse), Image.LANCZOS)
        buf = io.BytesIO()
        neu.save(buf, format="ICO", sizes=[(groesse, groesse)], bitmap_format="bmp")
        frisch = dict(ico_eintraege(buf.getvalue()))[groesse]

        assert frisch == nutzlast, (
            f"der {groesse}px-Rahmen weicht vom Design-System ab. "
            "python tools/make_icon.py ausfuehren und das Ergebnis committen."
        )
