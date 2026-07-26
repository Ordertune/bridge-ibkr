"""Pytest configuration — ensure src/ is on sys.path for local test runs.
CI uses `pip install -e .` before pytest, but local dev/QA benefits from
this shim so `pytest tests/` works without a manual install step.
"""
import sys
from pathlib import Path

SRC = Path(__file__).parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
