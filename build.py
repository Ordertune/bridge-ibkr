"""PyInstaller build-script.

Baut single-file EXE für Windows:
  dist/ordertune-bridge-ibkr.exe

Nach dem Build sollte die EXE mit einem EV-Code-Signing-Cert signiert
werden (siehe .github/workflows/release.yml — dort passiert das automatisch
wenn CERT_PFX_BASE64 + CERT_PW als GitHub-Secrets gesetzt sind).
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).parent
    dist = root / "dist"
    build = root / "build"

    if dist.exists():
        shutil.rmtree(dist)
    if build.exists():
        shutil.rmtree(build)

    cmd = [
        "pyinstaller",
        "--onefile",
        "--name",
        "ordertune-bridge-ibkr",
        "--console",
        "--clean",
        "--noconfirm",
        str(root / "src" / "ordertune_bridge_ibkr" / "main.py"),
    ]
    icon = root / "assets" / "icon.ico"
    if icon.exists():
        cmd.extend(["--icon", str(icon)])

    proc = subprocess.run(cmd, check=False)
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
