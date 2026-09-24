"""Hardware-Fingerprint für Bridge-Handshake.

SHA-256(hostname + Maschinenkennung + first_mac) — stabil über Restarts hinweg, aber
gebunden an die konkrete VPS-Hardware. Server-side lock-once via T1-15b
Option-C — Bridge kann ohne Token-Rotation nicht auf einer anderen Hardware
starten (409 fingerprint_already_set).

Die mittlere Zutat heisst auf Windows weiterhin ProcessorId und auf Linux seit
T1-206 D die Maschinenkennung des Systems. Die **Form** des Hashs ist auf
beiden Seiten dieselbe geblieben; die Plattform sieht keinen Unterschied und
braucht keinen.
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


#: Die Maschinenkennung, die systemd bei der Installation einmal wuerfelt. Sie
#: ueberlebt Neustarts und Kernel-Wechsel und ist bei einer Neuinstallation neu
#: — genau die Haltbarkeit, die dieser Hash braucht.
#:
#: Zwei Orte, in dieser Reihenfolge: `/etc/machine-id` ist der heutige, der
#: zweite ist der aeltere Platz aus D-Bus-Zeiten. Auf den drei zugesagten
#: Systemen liegt die Datei am ersten Ort; der zweite kostet nichts und faengt
#: die schlanken Abbilder, die ihn noch fuehren.
_MACHINE_ID_PFADE = ("/etc/machine-id", "/var/lib/dbus/machine-id")


def _read_machine_id() -> str:
    """Die Maschinenkennung, oder nichts."""
    for pfad in _MACHINE_ID_PFADE:
        try:
            with open(pfad, encoding="utf-8") as f:
                wert = f.read().strip()
        except OSError:
            continue
        if wert:
            return wert
    return ""


def _read_cpu_id_unix() -> str:
    """Die mittlere Zutat auf Nicht-Windows-Systemen.

    ## Der Befund (T1-206 D)

    Hier stand ausschliesslich der `/proc/cpuinfo`-Weg unten, und er liefert auf
    **jeder** x86-Maschine konstant `"0"`. Der Grund ist die Reihenfolge der
    Datei: gesucht wird die erste Zeile, die mit `Serial` ODER `processor`
    beginnt, und `processor` steht ganz oben — mit dem Wert `0`, der Nummer des
    ersten Kerns. Eine `Serial`-Zeile gibt es auf x86 ueberhaupt nicht; sie ist
    eine Eigenheit der ARM-Portierung, fuer die diese Abfrage einmal gedacht war.

    Die mittlere Stelle des Hashs trug damit auf Linux **nichts** bei. Es blieben
    Hostname und MAC-Adresse — und zwei frisch bestellte Server desselben
    Anbieters unterscheiden sich in beidem manchmal kaum. Aufgefallen ist es nie,
    weil Linux nie ausgeliefert wurde; der Riegel war also nicht kaputt, er war
    nur nie unter Last.

    ## Was jetzt gilt

    Zuerst die Maschinenkennung des Systems, dann erst der alte Weg. Die
    **Zutatenliste des Hashs bleibt unveraendert** — Hostname, mittlere Zutat,
    MAC —, es steht nur etwas Echtes an der mittleren Stelle. Deshalb aendert
    sich auf der Plattform nichts: kein Vertrag, keine Spalte, keine Migration.

    Was sich aendert, ist der **Wert**. Jede bestehende Nicht-Windows-Kopplung
    bekaeme damit einen anderen Fingerprint und liefe in die Auto-Suspend-Stufe
    der Auth-Kette. Im Echtbetrieb betrifft das niemanden, weil Linux nie
    ausgeliefert wurde — in die Release-Notiz gehoert es trotzdem.

    Der `/proc/cpuinfo`-Weg bleibt als Rueckfall stehen, statt ersatzlos zu
    verschwinden. Auf einem ARM-Board mit `Serial`-Zeile und ohne
    Maschinenkennung ist er die richtige Antwort, und `"0"` ist immer noch
    besser als ein Abbruch: der Hash wird dadurch nicht falsch, nur schwaecher.
    """
    kennung = _read_machine_id()
    if kennung:
        return kennung

    try:
        with open("/proc/cpuinfo", encoding="utf-8") as f:
            for line in f:
                if line.startswith("Serial") or line.startswith("processor"):
                    parts = line.split(":", 1)
                    if len(parts) == 2:
                        return parts[1].strip()
    except OSError:
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
