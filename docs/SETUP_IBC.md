# IBC (Interactive Brokers Controller) — Auto-Login

IBC automatisiert den täglichen Login in TWS oder Gateway. Ohne IBC müssen Sie jeden Morgen manuell einloggen, sonst schlagen alle Trades fehl (IBKR zwingt Gateway/TWS um 05:00 CET zu einem Force-Logout).

## Installation

1. IBC herunterladen: https://github.com/IbcAlpha/IBC/releases/latest (Windows-Zip)
2. Nach `C:\IBC\` entpacken
3. `C:\IBC\config.ini` editieren:
   - `IbLoginId=your-ibkr-username`
   - `IbPassword=your-ibkr-password`
   - `TradingMode=paper` (oder `live`)
4. IBC via `StartGateway.bat` oder `StartTWS.bat` starten

## Auto-Start bei Windows-Login

Windows Task Scheduler → Basic Task → **At log on** → `C:\IBC\StartGateway.bat`

## Sicherheit

- `config.ini` enthält Ihr IBKR-Passwort im Klartext. Setzen Sie NTFS-Permissions auf `Nur Ihr User-Account darf lesen`
- Alternative: Windows Credential Manager (IBC unterstützt das via `SettingsPasswordFromCredentialsFile`)

## Verifikation

Nach IBC-Start sollte das Gateway/TWS-Fenster automatisch erscheinen und eingeloggt sein. In den IBC-Logs (`C:\IBC\logs\`) steht der Login-Status.

Nach dem Login: Bridge starten. Sie sollte den Socket-Connect erfolgreich abschließen.
