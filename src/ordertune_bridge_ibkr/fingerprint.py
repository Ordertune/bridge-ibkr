"""Hardware-Fingerprint für Bridge-Handshake.

SHA-256(hostname + cpu_id + first_mac) — stabil über Restarts hinweg, aber
gebunden an die konkrete VPS-Hardware. Server-side lock-once via T1-15b
Option-C — Bridge kann ohne Token-Rotation nicht auf einer anderen Hardware
starten (409 fingerprint_already_set).
"""
from __future__ import annotations

import hashlib
import platform
import subprocess
import uuid


def _read_cpu_id_windows() -> str:
    """Read CPU-ProcessorId via wmic (Windows-only)."""
    try:
        result = subprocess.run(
            ["wmic", "cpu", "get", "ProcessorId", "/value"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""

    for line in result.stdout.splitlines():
        line = line.strip()
        if line.startswith("ProcessorId="):
            return line.split("=", 1)[1].strip()
    return ""


def _read_cpu_id_unix() -> str:
    """Fallback for Linux/macOS — read from /proc/cpuinfo or sysctl."""
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as f:
            for line in f:
                if line.startswith("Serial") or line.startswith("processor"):
                    parts = line.split(":", 1)
                    if len(parts) == 2:
                        return parts[1].strip()
    except FileNotFoundError:
        pass
    return ""


def read_cpu_id() -> str:
    if platform.system() == "Windows":
        return _read_cpu_id_windows()
    return _read_cpu_id_unix()


def compute_fingerprint() -> str:
    """Return the SHA-256 hex-fingerprint used in `X-Bridge-Fingerprint` header."""
    hostname = platform.node() or "unknown-host"
    mac = uuid.getnode()  # first available MAC as 48-bit int
    cpu_id = read_cpu_id()
    material = f"{hostname}|{cpu_id}|{mac:012x}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()
