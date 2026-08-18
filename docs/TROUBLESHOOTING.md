# Troubleshooting

## `bridge.env invalid` beim Start

Fehlende oder ungültige Felder. Prüfen Sie:
- `ORDERTUNE_BRIDGE_TOKEN` ist mindestens 32 Zeichen lang
- `ORDERTUNE_BRIDGE_CONNECTION_ID` ist gesetzt (aus dem Setup-Wizard kopiert)
- `IBKR_GATEWAY_PORT` ist eine gültige Portnummer

## `Failed to connect to IBKR TWS/Gateway`

- TWS oder Gateway ist nicht gestartet, oder auf einem anderen Port
- API in TWS/Gateway-Settings nicht aktiviert
- Socket-Port stimmt nicht überein (7497 Paper / 7496 Live Gateway)
- Trusted-IP `127.0.0.1` nicht in der TWS-Whitelist

## `Handshake failed: 409 fingerprint_already_set`

Ihre VPS-Hardware hat sich geändert (Provider-Migration, VM-Rebuild, MAC-Ändderung).

Lösung: Im Ordertune-Settings-UI den bestehenden Bridge-Token widerrufen und einen neuen erzeugen. Neue `bridge.env` herunterladen und die Bridge neu starten. Der neue Handshake registriert die aktuelle Hardware.

## `Handshake failed: 401`

Der Token wurde widerrufen oder ist abgelaufen. Neuen Token in den Ordertune-Settings erstellen.

## `Handshake failed: 403 ip_mismatch`

Die Verbindung war auf eine andere Source-IP registriert als die, aus der die Bridge jetzt kommt. Typische Ursachen: VPS-Migration, eine wechselnde Ausgangs-IP beim Provider, oder ein Proxy dazwischen.

Lösung: Im Ordertune-Settings-UI einen neuen Bridge-Token erzeugen, neue `bridge.env` herunterladen, Bridge neu starten. Damit die Verbindung dauerhaft stabil bleibt, sollte der VPS eine feste Ausgangs-IP haben.

## Sizing-Drift-Rejects

Wenn die Konsole viele `Sizing drift for dispatch X` zeigt:
- Ihr IBKR-Account-Equity hat sich seit dem letzten Server-Snapshot stark verändert (>5%)
- Kann bei Margin-Calls, großen Fills anderer Trader oder starken Intraday-Kursbewegungen passieren
- Lösung: Signal in der Ordertune-UI neu freigeben (der Server verwendet dann den frischen Equity-Snapshot)

## Log-Files

Rolling-Logs unter `logs/bridge.log`. Retention: 30 Tage.

Für Support-Anfragen bitte die letzten 200 Zeilen aus `logs/bridge.log` mitsenden (Token vorher schwärzen).

## Support

- E-Mail: helpdesk@ordertune.com
- GitHub Issues: https://github.com/ordertune/bridge-ibkr/issues
