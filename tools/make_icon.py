"""Erzeugt `assets/icon.ico` aus dem kanonischen Marken-Glyph.

## Warum ein Skript und nicht nur eine Binaerdatei

`assets/icon.ico` liegt als Datei im Repo, damit der Build kein Pillow
braucht — PyInstaller bekommt die fertige Datei. Eine committete Binaerdatei
ohne Herkunft driftet aber: in einem Jahr weiss niemand mehr, aus welchem PNG
sie stammt und ob sie noch dem Design-System entspricht.

Deshalb hat sie hier eine Quelle, und zwar **dieselbe**, aus der das Cockpit
sein Glyph nimmt: `cockpit/assets.py:ICON_PNG`. Das ist bereits im Repo, ist
bereits aus dem Design-System erzeugt, und ist bereits die Stelle, die das
Design-System als „einziges erlaubtes Marken-Glyph" benennt. Zwei Marken-
Bilder mit getrennter Herkunft waeren die zweite Stelle, an der die Marke
falsch werden kann.

Aufruf (Pillow wird nur hier gebraucht, nicht im Build):

    pip install Pillow
    python tools/make_icon.py

Danach `git diff --stat assets/icon.ico` — aendert sich nichts, war nichts zu
tun.
"""
from __future__ import annotations

import base64
import importlib.util
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS_MODULE = ROOT / "src" / "ordertune_bridge_ibkr" / "cockpit" / "assets.py"

# Die Groessen, die Windows tatsaechlich abruft. 16/32 sind Explorer-Liste und
# Titelleiste, 48 ist die Kachelansicht, 256 zieht der Datei-Dialog und die
# „Grosse Symbole"-Ansicht heran. Die Zwischenstufen kosten ein paar Kilobyte
# und verhindern, dass Windows selbst skaliert — das Ergebnis davon ist
# sichtbar schlechter als ein mitgeliefertes Bild.
SIZES = (16, 24, 32, 48, 64, 128, 256)

# Bis 128 als DIB (unkomprimiertes Bitmap), 256 als PNG.
#
# Ein ICO darf beides. Windows versteht PNG-Rahmen seit Vista, und Pillow
# schreibt per Voreinstellung *alle* Rahmen als PNG — das ist kleiner und auf
# einem normalen Desktop auch richtig. Die Bridge laeuft aber auf einem VPS,
# den der Kunde **ueber RDP** bedient, und genau dort ist die
# PNG-Ikonenschiene die unzuverlaessige: fuer die kleinen Groessen gibt es
# belegte Faelle, in denen ein PNG-Rahmen in der entfernten Sitzung leer
# bleibt. Ein leeres Symbol waere derselbe Befund wie das Python-Symbol, nur
# schwerer zu finden.
#
# 256 bleibt PNG, weil ein DIB in dieser Groesse allein 256 KB waere — ein
# Viertel Megabyte in der EXE fuer ein Bild, das nur der grosse Datei-Dialog
# abruft. Das ist die Groesse, bei der Windows PNG am zuverlaessigsten kann.
PNG_FROM = 256


def main() -> int:
    try:
        from PIL import Image
    except ModuleNotFoundError:
        print("Pillow fehlt. `pip install Pillow`, dann erneut.", file=sys.stderr)
        return 2

    # `assets.py` wird als einzelne Datei geladen, nicht ueber das Paket.
    # `cockpit/__init__.py` zieht `httpx` und den halben Bridge-Kern nach; ein
    # Werkzeug, das eine Konstante braucht, soll dafuer nicht die Laufzeit-
    # Abhaengigkeiten installiert haben muessen.
    spec = importlib.util.spec_from_file_location("_ot_assets", ASSETS_MODULE)
    assets = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(assets)

    src = Image.open(io.BytesIO(base64.b64decode(assets.ICON_PNG)))

    def frame_payload(img, size: int) -> bytes:
        """Der Rohinhalt *eines* Rahmens, so wie er im ICO steht.

        Pillow schreibt einen einzelnen Rahmen korrekt — inklusive der
        verdoppelten Hoehe im DIB-Kopf, ueber die eine Handimplementierung
        stolpert. Also: einrahmiges ICO speichern lassen, den Verzeichnis-
        eintrag lesen und die Nutzlast wieder herausschneiden. Das Zusammen-
        setzen uebernimmt danach `write_ico`, weil Pillow gemischte Formate in
        einem Durchgang nicht anbietet.
        """
        buf = io.BytesIO()
        kwargs = {"format": "ICO", "sizes": [(size, size)]}
        if size < PNG_FROM:
            kwargs["bitmap_format"] = "bmp"
        img.save(buf, **kwargs)
        raw = buf.getvalue()
        count = int.from_bytes(raw[4:6], "little")
        assert count == 1, f"{size}px: {count} Rahmen statt 1"
        length = int.from_bytes(raw[14:18], "little")
        offset = int.from_bytes(raw[18:22], "little")
        return raw[offset:offset + length]

    # Das Quell-PNG ist RGB ohne Alpha. Die Kachel ist absichtlich deckend
    # schwarz — das Design-System kennt das Glyph nur so. Der Alphakanal kommt
    # trotzdem dazu, weil das ICO-Format ihn ohnehin vorsieht und ein
    # fehlender Kanal bei manchen Windows-Versionen als schwarze Maske
    # missverstanden wird.
    src = src.convert("RGBA")

    # Jede Groesse einzeln mit LANCZOS aus dem 512er rechnen. Pillow sonst
    # `thumbnail`t sich die fehlenden Groessen selbst aus dem Basisbild
    # zusammen, und bei 16 px ist der Unterschied zwischen einem sauber
    # gerechneten und einem nebenbei skalierten Ring deutlich sichtbar.
    payloads = [(n, frame_payload(src.resize((n, n), Image.LANCZOS), n))
                for n in SIZES]

    out = ROOT / "assets" / "icon.ico"
    out.parent.mkdir(exist_ok=True)
    out.write_bytes(write_ico(payloads))

    kinds = ", ".join(f"{n}{'p' if n >= PNG_FROM else 'd'}" for n in SIZES)
    print(f"{out.relative_to(ROOT)} — {out.stat().st_size} Bytes, "
          f"{len(SIZES)} Rahmen ({kinds}; d=DIB, p=PNG)")
    return 0


def write_ico(payloads: list[tuple[int, bytes]]) -> bytes:
    """Baut das ICONDIR ueber fertige Rahmen-Nutzlasten."""
    count = len(payloads)
    head = b"\0\0" + (1).to_bytes(2, "little") + count.to_bytes(2, "little")
    offset = len(head) + count * 16
    directory, body = b"", b""
    for size, payload in payloads:
        directory += bytes((
            size if size < 256 else 0,   # bWidth — 0 bedeutet 256
            size if size < 256 else 0,   # bHeight
            0,                           # bColorCount — 0 bei Echtfarben
            0,                           # bReserved
        ))
        directory += (1).to_bytes(2, "little")   # wPlanes
        directory += (32).to_bytes(2, "little")  # wBitCount
        directory += len(payload).to_bytes(4, "little")
        directory += offset.to_bytes(4, "little")
        offset += len(payload)
        body += payload
    return head + directory + body


if __name__ == "__main__":
    sys.exit(main())
