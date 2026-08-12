"""PyInstaller entry point.

## Why this file exists

PyInstaller was pointed at `src/ordertune_bridge_ibkr/main.py` directly. That
makes the module the `__main__` script, and a `__main__` script has no parent
package — so the very first import in it, `from . import __version__`, raised

    ImportError: attempted relative import with no known parent package

before a single line of the Bridge ran. Every build since 0.1.0 was affected.
It was never noticed because nothing in CI ever started the packaged
executable; the test suite imports the package the normal way, where relative
imports are correct and work fine.

The fix is not to rewrite the package's imports. They are right. What was
wrong is that the package's own module was used as a launch script. This file
is the launch script: it is not part of the package, so it can import the
package by name, and the package's internals keep working the way Python
expects.

Keeping the launcher separate also means `python -m ordertune_bridge_ibkr.main`
and the `ordertune-bridge-ibkr` console script from `pyproject.toml` still
behave identically. There is one implementation of `main()`, and three ways in.
"""
from __future__ import annotations

import sys

from ordertune_bridge_ibkr.main import main

if __name__ == "__main__":
    sys.exit(main())
