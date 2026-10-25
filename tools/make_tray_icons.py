"""Erzeugt `cockpit/tray_icons.py`: das Marken-Glyph mit einem Statuspunkt.

## Warum es diese Bilder gibt

Das Tray-Symbol ist die einzige Stelle, an der man der fensterlosen Bridge
ansieht, dass sie laeuft — und wie es ihr geht. Ein Punkt in der Ecke traegt
den Zustand; die Farben sind dieselben wie im Cockpit (`--success`, `--warn`),
damit Fenster und Symbol nicht verschieden ueber dieselbe Lage reden.

## Warum als Python-Modul und nicht als `.ico`-Dateien

Die EXE ist eine einzelne Datei. Ein `.ico` neben dem Code hiesse
`--add-data` im Build und einen Pfad, der im entpackten Verzeichnis gesucht
werden muss. Als Konstante reist das Bild mit dem Code, und Windows baut das
Symbol direkt aus den Bytes (`CreateIconFromResourceEx`) — derselbe Weg, auf
dem `cockpit/assets.py` das Glyph ins Fenster bringt.

Quelle ist wie bei `make_icon.py` das Glyph aus `cockpit/assets.py:ICON_PNG`.

Aufruf (Pillow wird nur hier gebraucht, nicht im Build):

    pip install Pillow
    python tools/make_tray_icons.py
"""
from __future__ import annotations

import base64
import importlib.util
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS_MODULE = ROOT / "src" / "ordertune_bridge_ibkr" / "cockpit" / "assets.py"
OUT = ROOT / "src" / "ordertune_bridge_ibkr" / "cockpit" / "tray_icons.py"

# Die Groessen, die der Infobereich je nach Skalierung abruft: 16 px bei 100 %,
# 20 bei 125 %, 24 bei 150 %, 32 bei 200 %, 40 bei 250 %, 48 bei 300 %.
# Alle als DIB — PNG-Rahmen bleiben in RDP-Sitzungen belegt leer (siehe
# `make_icon.py`), und genau dort laeuft die Bridge oft.
SIZES = (16, 20, 24, 32, 40, 48)

# Zustand -> Farbe des Punkts. `None` heisst: kein Punkt.
STATES = {
    "running": (0x16, 0xA3, 0x4A),    # --success
    "attention": (0xD9, 0x77, 0x06),  # --warn
    "stopping": (0x9C, 0xA3, 0xAF),   # neutral grau: es endet, nichts ist kaputt
}

# Geometrie auf der 512er-Vorlage: Punkt unten rechts, mit einem Ring in der
# Kachelfarbe, damit er sich bei 16 px vom Glyph abhebt.
DOT_CENTER = 372
DOT_RADIUS = 124
RING = 30
TILE = (0x0A, 0x0A, 0x0A, 0xFF)


def _load_glyph():
    from PIL import Image

    spec = importlib.util.spec_from_file_location("_ot_assets", ASSETS_MODULE)
    assets = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(assets)
    return Image.open(io.BytesIO(base64.b64decode(assets.ICON_PNG))).convert("RGBA")


def _with_dot(src, colour):
    from PIL import ImageDraw

    img = src.copy()
    draw = ImageDraw.Draw(img)
    c, r = DOT_CENTER, DOT_RADIUS
    draw.ellipse((c - r - RING, c - r - RING, c + r + RING, c + r + RING), fill=TILE)
    draw.ellipse((c - r, c - r, c + r, c + r), fill=(*colour, 0xFF))
    return img


def _frame(img, size: int) -> bytes:
    """Ein DIB-Rahmen, so wie er im ICO steht (wie in `make_icon.py`)."""
    buf = io.BytesIO()
    img.save(buf, format="ICO", sizes=[(size, size)], bitmap_format="bmp")
    raw = buf.getvalue()
    length = int.from_bytes(raw[14:18], "little")
    offset = int.from_bytes(raw[18:22], "little")
    return raw[offset:offset + length]


def build(preview_dir: Path | None = None) -> dict[str, bytes]:
    from PIL import Image

    sys.path.insert(0, str(ROOT / "tools"))
    from make_icon import write_ico

    src = _load_glyph()
    out: dict[str, bytes] = {}
    for state, colour in STATES.items():
        big = _with_dot(src, colour)
        frames = [(n, _frame(big.resize((n, n), Image.LANCZOS), n)) for n in SIZES]
        out[state] = write_ico(frames)
        if preview_dir is not None:
            big.resize((64, 64), Image.LANCZOS).save(preview_dir / f"tray-{state}.png")
    return out


def main() -> int:
    try:
        import PIL  # noqa: F401
    except ModuleNotFoundError:
        print("Pillow fehlt. `pip install Pillow`, dann erneut.", file=sys.stderr)
        return 2

    preview = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    icons = build(preview)
    lines = [
        '"""Erzeugt von `tools/make_tray_icons.py` — nicht von Hand aendern.',
        "",
        "Je Zustand ein ICO (16-48 px, DIB) des Marken-Glyphs mit Statuspunkt.",
        '"""',
        "",
    ]
    for state, data in icons.items():
        b64 = base64.b64encode(data).decode("ascii")
        chunks = [b64[i:i + 76] for i in range(0, len(b64), 76)]
        lines.append(f"{state.upper()} = (")
        lines.extend(f'    "{chunk}"' for chunk in chunks)
        lines.append(")")
        lines.append("")
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"{OUT.relative_to(ROOT)} — {OUT.stat().st_size} Bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
