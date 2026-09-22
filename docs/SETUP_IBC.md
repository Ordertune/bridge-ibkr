# IBC (Interactive Brokers Controller) — Auto-Login

IBC automatisiert den täglichen Login in die TWS. Ohne IBC müssen Sie jeden Morgen manuell einloggen, sonst schlagen alle Trades fehl (IBKR zwingt die TWS um 05:00 CET zu einem Force-Logout).

**Nur TWS.** Seit Fassung 0.25.0 verlangt die Bridge die TWS — das IB Gateway hat keine Berichtsfunktion und kann eine verpasste Füllung nicht nachtragen. Siehe [SETUP_TWS_GATEWAY.md](SETUP_TWS_GATEWAY.md).

## Installation

1. IBC herunterladen: https://github.com/IbcAlpha/IBC/releases/latest (Windows-Zip)
2. Nach `C:\IBC\` entpacken
3. `C:\IBC\config.ini` editieren:
   - `IbLoginId=your-ibkr-username`
   - `IbPassword=your-ibkr-password`
   - `TradingMode=paper` (oder `live`)
4. IBC via `StartTWS.bat` starten

## Auto-Start bei Windows-Login

Windows Task Scheduler → Basic Task → **At log on** → `C:\IBC\StartTWS.bat`

## Sicherheit

- `config.ini` enthält Ihr IBKR-Passwort im Klartext. Setzen Sie NTFS-Permissions auf `Nur Ihr User-Account darf lesen`
- Alternative: Windows Credential Manager (IBC unterstützt das via `SettingsPasswordFromCredentialsFile`)

## Verifikation

Nach IBC-Start sollte das TWS-Fenster automatisch erscheinen und eingeloggt sein. In den IBC-Logs (`C:\IBC\logs\`) steht der Login-Status.

Nach dem Login: Bridge starten. Sie sollte den Socket-Connect erfolgreich abschließen.
