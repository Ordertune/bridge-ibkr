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

    # Build `launcher.py`, NOT `src/ordertune_bridge_ibkr/main.py`.
    #
    # Pointing PyInstaller at a module inside the package makes that module the
    # `__main__` script, and a `__main__` script has no parent package. The
    # first relative import then fails with
    #
    #     ImportError: attempted relative import with no known parent package
    #
    # which is exactly how every build since 0.1.0 died on startup. `--paths`
    # puts `src` on the analysis path so the launcher can import the package
    # by name and PyInstaller bundles it as a package.
    cmd = [
        "pyinstaller",
        "--onefile",
        "--name",
        "ordertune-bridge-ibkr",
        "--console",
        "--clean",
        "--noconfirm",
        "--paths",
        str(root / "src"),
        str(root / "launcher.py"),
    ]
    icon = root / "assets" / "icon.ico"
    if icon.exists():
        cmd.extend(["--icon", str(icon)])

    proc = subprocess.run(cmd, check=False)
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
