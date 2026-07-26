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
   - **Socket Port**: 7497 (Paper) oder 7496 (Live)
   - **Master API Client ID**: leer lassen (jeder Client-ID erlaubt)
   - **Trusted IPs**: `127.0.0.1` hinzufügen
   - **Bypass Order Precautions for API Orders**: aktivieren (verhindert Popup-Warnings die die Bridge blockieren)
4. **OK** → TWS/Gateway neu starten

Verifizieren: Socket-Port sollte lokal offen sein.

```powershell
Test-NetConnection -ComputerName 127.0.0.1 -Port 7497
```

## Paper vs. Live

- **Paper**: Port 7497. Fantasie-Konto mit fiktivem Geld — perfekt für erste Bridge-Tests
- **Live**: Port 7496 (Gateway) oder ebenfalls 7497 im Live-TWS. **ACHTUNG**: Live führt zu echten Trades mit echtem Geld

In der `bridge.env`:
```
IBKR_GATEWAY_PORT=7497
IBKR_TRADING_MODE=paper
```

## Force-Logout um 05:00 CET (wichtig)

IBKR forced Gateway und TWS **täglich gegen 05:00 CET** zu einem Logout. Ohne Auto-Login-Mechanismus (**IBC**, siehe [SETUP_IBC.md](SETUP_IBC.md)) müssen Sie jeden Morgen manuell neu einloggen — sonst schlagen alle Trades am US-Open fehl.

IBC ist Community-Standard, kostenlos, open-source: https://github.com/IbcAlpha/IBC

## Troubleshooting

- **`ib_insync` connect timeout**: TWS/Gateway läuft nicht oder Socket-Port stimmt nicht überein
- **Order Precaution Popups**: "Bypass Order Precautions for API Orders" nicht aktiviert
- **Client-ID collision**: eine andere Anwendung nutzt bereits die Client-ID 17 → im `bridge.env` einen anderen Wert setzen (`IBKR_CLIENT_ID=42`)
