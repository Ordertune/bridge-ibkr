# TWS oder IB Gateway Setup

Die Bridge kann sowohl gegen die **Trader Workstation (TWS)** als auch gegen das schlankere **IB Gateway** connecten. Für 24/7 Auto-Trading-Setups ist IB Gateway die bessere Wahl (weniger Ressourcenverbrauch, keine GUI-Overheads).

## Download

- TWS: https://www.interactivebrokers.com/en/trading/tws.php
- IB Gateway: https://www.interactivebrokers.com/en/trading/ibgateway-stable.php

## Erst-Setup TWS/Gateway

1. Installieren und starten
2. Mit IBKR-Account einloggen
3. Menu → **Global Configuration** → **API** → **Settings**
   - **Enable ActiveX and Socket Clients**: aktivieren
   - **Read-Only API**: **deaktivieren** (Bridge muss Orders senden können)
   - **Socket Port**: hängt von Programm UND Kontoart ab:

     | Programm | Konto | Port |
     |---|---|---|
     | TWS | Paper | 7497 |
     | TWS | Live | 7496 |
     | IB Gateway | Paper | 4002 |
     | IB Gateway | Live | 4001 |
   - **Master API Client ID**: leer lassen (jeder Client-ID erlaubt)
   - **Trusted IPs**: `127.0.0.1` hinzufügen
   - **Bypass Order Precautions for API Orders**: aktivieren (verhindert Popup-Warnings die die Bridge blockieren)
4. **OK** → TWS/Gateway neu starten

Verifizieren: Socket-Port sollte lokal offen sein.

```powershell
Test-NetConnection -ComputerName 127.0.0.1 -Port 7497
```

## Paper vs. Live

- **Paper**: Fantasie-Konto mit fiktivem Geld — perfekt für erste Bridge-Tests. TWS 7497, Gateway 4002
- **Live**: **ACHTUNG**, echte Trades mit echtem Geld. TWS 7496, Gateway 4001

Der Port in `bridge.env` muss mit dem in TWS/Gateway eingestellten übereinstimmen. Stimmen sie nicht überein, läuft die Bridge in einen Verbindungs-Timeout — die Meldung sagt nicht, welche der beiden Zahlen falsch ist.

In der `bridge.env`:
```
IBKR_GATEWAY_PORT=7497
IBKR_TRADING_MODE=paper
```

## Force-Logout um 05:00 CET (wichtig)

IBKR forced Gateway und TWS **täglich gegen 05:00 CET** zu einem Logout. Ohne Auto-Login-Mechanismus (**IBC**, siehe [SETUP_IBC.md](SETUP_IBC.md)) müssen Sie jeden Morgen manuell neu einloggen — sonst schlagen alle Trades am US-Open fehl.

IBC ist Community-Standard, kostenlos, open-source: https://github.com/IbcAlpha/IBC

## Troubleshooting

- **`ib_insync` connect timeout**: TWS/Gateway läuft nicht, oder der Socket-Port stimmt nicht überein (Tabelle oben)
- **Konto-Werte bleiben 0**: die Bridge liest ausschliesslich USD-Kontowerte. Läuft das Konto in einer anderen Währung, meldet sie das seit 0.2.2 als Warnung im Protokoll — die Werte gehen dann als 0 an Ordertune und es kann keine Order dimensioniert werden
- **Order Precaution Popups**: "Bypass Order Precautions for API Orders" nicht aktiviert
- **Client-ID collision**: eine andere Anwendung nutzt bereits die Client-ID 17 → im `bridge.env` einen anderen Wert setzen (`IBKR_CLIENT_ID=42`)
