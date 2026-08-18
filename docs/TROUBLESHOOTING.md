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

## `IBKR did not answer the positions request within 20s`

Ab 0.6.0. Die Bridge liest das Depot ueber `reqPositions` und wartet beim
Verbinden ausdruecklich auf die Antwort. Bleibt sie aus, meldet die Bridge
Ordertune **keine** Depotauskunft — statt einer leeren, die "das Konto haelt
nichts" bedeuten wuerde.

Was Sie in dieser Lage sehen:

- Der Heartbeat laeuft weiter, die Verbindung gilt als gesund.
- Im Order Management steht in der Spalte "At broker" ein Strich.
- Modell-Ausstiege gehen nicht hinaus, solange der Bestand ungeklaert ist.
- **Es wird keine Position als verkauft gebucht.** Das ist der Zweck.

Bis 0.5.x las die Bridge das Depot aus dem Konto-Abo. Lief dieses in einen
Zeitueberlauf — im Log als `account updates for U... request timed out` —,
meldete sie ein leeres Depot bei vollem Konto. Am 2026-08-18 wurden daraufhin
zwei echte Positionen als extern verkauft gebucht.

Abhilfe: TWS oder Gateway neu starten und pruefen, dass die API-Einstellungen
Lese-Zugriff auf Konto und Positionen erlauben. Haelt es an, bitte die letzten
200 Zeilen des Logs an den Support schicken.

## `This login manages several accounts`

Ihr IBKR-Login verwaltet mehr als ein Konto. Ordertune kann nicht entscheiden,
auf welchem gehandelt wird, und meldet die Positionen deshalb ueber alle
zusammen — die gemeldete Stueckzahl je Symbol kann dann groesser sein als das,
was ein einzelnes Konto haelt. Bitte melden Sie sich beim Support; der Fall ist
loesbar, aber nicht durch Raten.

## Log-Files

Rolling-Logs unter `logs/bridge.log`. Retention: 30 Tage.

Für Support-Anfragen bitte die letzten 200 Zeilen aus `logs/bridge.log` mitsenden (Token vorher schwärzen).

## Support

- E-Mail: helpdesk@ordertune.com
- GitHub Issues: https://github.com/ordertune/bridge-ibkr/issues
