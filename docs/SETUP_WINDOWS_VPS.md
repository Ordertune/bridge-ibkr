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

## Auto-Start bei Login (empfohlen)

Windows Task Scheduler:

1. Task Scheduler öffnen → **Create Basic Task**
2. Trigger: **When I log on**
3. Action: **Start a program** → `C:\ordertune-bridge\ordertune-bridge-ibkr.exe`
4. Start in: `C:\ordertune-bridge\`
5. Speichern

Alternativ als geplanter Task, der beim VPS-Boot startet — dann muss der VPS aber automatisches Login haben (Autologon), was Sicherheitsrisiko birgt.

## Update-Prozedur

Beim Bridge-Start wird die GitHub-Release-API geprüft. Wenn eine neuere Version verfügbar ist, zeigt die Konsole:

```
[WARN] A newer Bridge version is available: v0.2.0 (you have v0.1.0)
[WARN] Download: https://github.com/ordertune/bridge-ibkr/releases/latest
```

Update = Bridge stoppen, neue EXE herunterladen, alte überschreiben, neu starten. Ihre `bridge.env` bleibt unverändert.
