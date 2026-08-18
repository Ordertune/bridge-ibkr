# ordertune-bridge-ibkr

Windows-Native Bridge-Client für Interactive Brokers. Holt vom User freigegebene Signale aus `t1.ordertune.com`, führt Orders im privaten IBKR-Depot aus, meldet Depot-State und Order-Results zurück.

**Der Bridge-Client läuft auf einem privaten Virtual Private Server des Nutzers.** Ordertune führt keine Orders im Namen des Nutzers aus. Der Nutzer muss jede Order (oder jede Strategy für maximal 24 Stunden) über die Ordertune-Weboberfläche explizit freigeben, bevor die Bridge sie abholen und in IBKR platzieren darf.

## Voraussetzungen

- Windows-VPS (Windows Server 2019+ oder Windows 10/11 Pro)
- Interactive Brokers Pro Individual Account (Retail-OAuth wird von IBKR nicht angeboten — Bridge ist der einzige Weg)
- Installiertes Trader Workstation (TWS) **oder** IB Gateway
- Empfohlen: IBC (Interactive Brokers Controller) für tägliche Auto-Login nach 05:00 CET Force-Logout
- Ordertune-Advanced- oder Institutional-Alpha-Subscription mit `allows_ibkr_bridge=true` (im aktuellen Tier-Setting)

## Installation

1. Download der aktuellen Version aus [Releases](https://github.com/ordertune/bridge-ibkr/releases/latest)
2. Zip entpacken auf dem Windows-VPS
3. `bridge.env`-Datei (aus dem Ordertune-Settings-Wizard heruntergeladen) daneben legen
4. TWS oder IB Gateway starten und einloggen (API aktiviert, Read-Only-API deaktiviert, Trusted-IP `127.0.0.1` erlaubt)
5. Doppelklick auf `ordertune-bridge-ibkr.exe`

## Konfiguration (`bridge.env`)

Der Setup-Wizard in Ordertune generiert die Datei automatisch. Manuell editierbar für Fortgeschrittene:

```
ORDERTUNE_API_BASE=https://t1.ordertune.com
ORDERTUNE_BRIDGE_TOKEN=ot_bridge_<hex>
ORDERTUNE_BRIDGE_CONNECTION_ID=<uuid>

IBKR_GATEWAY_HOST=127.0.0.1
IBKR_GATEWAY_PORT=7497
IBKR_TRADING_MODE=paper
IBKR_CLIENT_ID=17

ORDER_SUBMIT_DELAY_MS=100
LOG_LEVEL=INFO
UPDATE_CHECK_ENABLED=true
```

## Laufverhalten

- **Heartbeat** alle 60 Sekunden: Cash, Equity, Positions + Gateway-Status an Ordertune
- **Pending-Poll** alle 5 Sekunden während US-Marktzeit (60s off-hours): holt freigegebene Signale
- **Position-Sizing-Recompute**: Bridge recomputet die Qty gegen die Live-Equity aus TWS. Bei >5% Drift zur Server-Berechnung wird die Order automatisch abgelehnt (der User muss dann neu freigeben)
- **Order-Result-Push**: nach jedem Fill/Cancel/Reject wird ein Result-Event an Ordertune gesendet
- **Update-Check** beim Start: prüft GitHub Latest Release und zeigt Warning bei neuerer Version

## Diagnose: `--probe-foreign`

```
ordertune-bridge-ibkr.exe --probe-foreign
```

Verbindet sich, fragt IBKR dreimal — offene Aufträge über alle Clients,
abgeschlossene des Tages einschliesslich der von Hand in TWS gestellten, sowie
die Ausführungen des Tages —, schreibt auf, was zurückkommt, und beendet sich.

**Es geht dabei kein Auftrag hinaus und keiner wird verändert.** Der Schalter
beantwortet eine einzige Frage: sieht diese Verbindung überhaupt etwas von
Aufträgen, die nicht von der Bridge stammen? Jede Zeile ist als `OURS` oder
`FOREIGN` gekennzeichnet.

## Sicherheit

- Der Access-Token wird nur lokal in `bridge.env` gespeichert. Er kann jederzeit über die Ordertune-Settings widerrufen werden.
- Die Verbindung ist an die VPS-Instanz gebunden: an ihre Hardware (SHA-256-Fingerprint aus Hostname, CPU-ID, MAC-Adresse) und an die Source-IP, unter der sie sich registriert hat. Beides schreibt der Server beim ersten Handshake fest. Läuft die Bridge danach auf anderer Hardware oder aus einem anderen Netz, verweigert der Server die Verbindung, bis der Token rotiert wurde. Die Bridge sollte deshalb auf einem VPS mit fester Ausgangs-IP laufen.
- VPS-Wechsel: alten Token in Ordertune widerrufen, neuen erzeugen, `bridge.env` austauschen, Bridge starten. Der alte Fingerprint wird beim Rotate gecleart, der neue Handshake registriert die neue Hardware.

## Docs

- [Windows-VPS-Setup](docs/SETUP_WINDOWS_VPS.md)
- [TWS / IB Gateway Setup](docs/SETUP_TWS_GATEWAY.md)
- [IBC (Auto-Login)](docs/SETUP_IBC.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)

## Development

```bash
python -m venv .venv
source .venv/bin/activate   # or .venv\Scripts\activate on Windows
pip install -e ".[dev]"
pytest
```

## Build

```bash
python build.py
```

Erzeugt `dist/ordertune-bridge-ibkr.exe` (single-file, ~40 MB).

## Lizenz

MIT (siehe [LICENSE](LICENSE)). Wichtig: IBKR Trader Workstation und IB Gateway sind **nicht** in dieser Distribution enthalten — sie müssen vom Nutzer separat von Interactive Brokers bezogen und installiert werden (IBKR-Lizenzbedingungen).
