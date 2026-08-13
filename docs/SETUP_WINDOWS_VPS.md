# Windows-VPS Setup

## Empfohlene VPS-Provider (DACH)

- [Hetzner Cloud](https://www.hetzner.com/cloud) — CX21 Windows (~15 €/Monat, 2 vCPU, 4 GB RAM)
- [Contabo](https://contabo.com/) — VPS-M Windows (~10 €/Monat)
- [IONOS](https://www.ionos.de/) — Enterprise-Cloud-Instanzen mit Windows Server

Empfehlung: mindestens 2 vCPU, 4 GB RAM, 40 GB SSD. Standort Frankfurt oder Amsterdam für gute Latenz zu IBKR.

## Basiseinrichtung

1. Windows-VPS anlegen (Windows Server 2019 oder Windows 11)
2. Per RDP verbinden
3. Windows-Updates einspielen
4. Firewall-Regeln:
   - **Ausgehend**: HTTPS zu `t1.ordertune.com` (443), IBKR-Server (typisch 4001/4002)
   - **Eingehend**: nur RDP (3389) für Admin-Zugang, sonst zu
5. Optional: TeamViewer oder AnyDesk statt RDP für bequemeren Remote-Zugang

## Bridge-Installation

1. Herunterladen der aktuellen Version: https://github.com/ordertune/bridge-ibkr/releases/latest
2. Zip entpacken (z.B. nach `C:\ordertune-bridge\`)
3. `bridge.env` aus dem Ordertune-Setup-Wizard herunterladen und in den gleichen Ordner legen
4. Doppelklick auf `ordertune-bridge-ibkr.exe` — die Bridge startet in einem Konsolenfenster
5. Bei erfolgreichem Handshake steht in der Konsole: `Handshake successful — Bridge is active.`

## Dauerbetrieb: nicht an Ihre Anmeldung binden

Das Wichtigste zuerst, weil es die häufigste Fehlbedienung ist: **ein Konsolenfenster und eine TWS-Instanz gehören zu Ihrer Windows-Sitzung.** Melden Sie sich ab, sind beide weg — und die Bridge verpasst die US-Eröffnung, ohne dass irgendwo eine Fehlermeldung steht.

### RDP: trennen, nicht abmelden

- Das **X** am RDP-Fenster *trennt* die Sitzung. Programme laufen weiter.
- **Abmelden / Sign out** beendet alles.

Viele Windows-Server-Images melden getrennte Sitzungen zusätzlich nach einigen Minuten automatisch ab. Das abschalten:

`gpedit.msc` → Computerkonfiguration → Administrative Vorlagen → Windows-Komponenten → Remotedesktopdienste → Remotedesktopsitzungs-Host → **Sitzungszeitlimits** → „Zeitlimit für getrennte Sitzungen festlegen" → **Deaktiviert**.

### TWS: Auto-Restart statt Auto-Logoff

In TWS unter Configuration → **Lock and Exit** gibt es beide Varianten. Auf **Auto restart** stellen: TWS kommt nach IBKRs täglicher Zwangsabmeldung (~05:00 MEZ) von selbst zurück, ohne erneute Eingabe der Zugangsdaten. Für vollautomatischen Login siehe [SETUP_IBC.md](SETUP_IBC.md).

### Bridge als Windows-Dienst (empfohlen)

Der robusteste Weg, weil er von keiner Anmeldung abhängt. Mit [NSSM](https://nssm.cc/):

```powershell
nssm install OrdertuneBridge C:\ordertune-bridge\ordertune-bridge-ibkr.exe
nssm set OrdertuneBridge AppDirectory C:\ordertune-bridge
nssm set OrdertuneBridge Start SERVICE_AUTO_START
nssm start OrdertuneBridge
```

Das Protokoll finden Sie dann nicht mehr im Konsolenfenster, sondern im `logs/`-Ordner neben der EXE.

### Alternative: geplanter Task beim Systemstart

Wenn Sie keinen Dienst wollen — Task Scheduler, aber mit den richtigen Optionen:

- Trigger: **Beim Systemstart** (nicht „Bei Anmeldung")
- **Unabhängig von der Benutzeranmeldung ausführen** ankreuzen
- **Mit höchsten Privilegien ausführen**

Ein Task mit Trigger „Bei Anmeldung" stirbt mit der Sitzung und ist für Dauerbetrieb ungeeignet. Frühere Fassungen dieser Anleitung haben genau das empfohlen; das war falsch.

## Update-Prozedur

Beim Bridge-Start wird die GitHub-Release-API geprüft. Wenn eine neuere Version verfügbar ist, zeigt die Konsole:

```
[WARN] A newer Bridge version is available: v0.2.0 (you have v0.1.0)
[WARN] Download: https://github.com/ordertune/bridge-ibkr/releases/latest
```

Update = Bridge stoppen, neue EXE herunterladen, alte überschreiben, neu starten. Ihre `bridge.env` bleibt unverändert.
