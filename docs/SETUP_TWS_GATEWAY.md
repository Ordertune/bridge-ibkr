# TWS Setup

Die Bridge verlangt die **Trader Workstation (TWS)**. Das IB Gateway wird ab
Fassung 0.25.0 **nicht mehr unterstützt**.

## Warum nicht mehr das Gateway

Das Gateway hat keine Berichtsfunktion. Sein Konfigurationsbaum endet bei
`Orders → Smart Routing` — es gibt dort weder `Export Reports` noch ein
Trade-Log-Fenster, das einen Bericht befüllen könnte.

Das ist keine Geschmacksfrage. Ist die Bridge im Moment einer Ausführung nicht
verbunden, kann sie IBKR hinterher nicht mehr danach fragen: `reqExecutions`
verlässt den laufenden Tag nicht, auch nicht mit Zeitfilter. Die einzige Quelle,
die den Tageswechsel überlebt, ist die Datei, die die TWS selbst schreibt. Ein
Gateway-Setup kann eine verpasste Füllung deshalb nicht nachtragen — die Position
bleibt ohne Strategie im Depot stehen, und ein Modell-Ausstieg fasst sie nie an.

TWS braucht mehr Arbeitsspeicher als das Gateway. Auf einem VPS mit 2 GB sollte
vor der Umstellung nachgesehen werden; 4 GB sind unkritisch.

## Download

- TWS: https://www.interactivebrokers.com/en/trading/tws.php

## 1. API freigeben

1. Installieren, starten, mit dem IBKR-Konto einloggen
2. Menü → **Global Configuration** → **API** → **Settings**
   - **Enable ActiveX and Socket Clients**: aktivieren
   - **Read-Only API**: **deaktivieren** (die Bridge muss Orders senden können)
   - **Socket Port**: TWS Paper `7497`, TWS Live `7496`
   - **Master API Client ID**: leer lassen
   - **Trusted IPs**: `127.0.0.1` hinzufügen
   - **Bypass Order Precautions for API Orders**: aktivieren
3. **OK** → TWS neu starten

Verifizieren:

```powershell
Test-NetConnection -ComputerName 127.0.0.1 -Port 7497
```

Der Port in `bridge.env` (`IBKR_GATEWAY_PORT`) muss mit dem hier eingestellten
übereinstimmen. Stimmen sie nicht überein, läuft die Bridge in einen
Verbindungs-Timeout — die Meldung sagt nicht, welche der beiden Zahlen falsch
ist.

## 2. Handelsberichte einschalten (wichtig)

Hier entsteht das Netz, das eine Füllung rettet, wenn die Bridge gerade aus war.

Menü → **Global Configuration** → **Export Reports** (deutsch: **Berichte
exportieren**):

| Einstellung | Wert |
|---|---|
| Handelsberichte regelmäßig exportieren | **an** |
| Startzeit | `00:00` |
| Endzeit | `23:59` |
| Intervall (Min.) | `1` |
| Exportverzeichnis | `C:\IBExport` |
| **Name der Exportdatei** | **leer lassen** |
| Spaltenauswahl | **Benutzerdefinierte Spalten**, siehe unten |
| Für die Uhrzeiten der Trades die lokale Zeitzone verwenden | **an** |
| Trennzeichen zwischen Feldern | `;` |

**Das Feld „Name der Exportdatei" muss leer bleiben.** Steht dort ein Name,
schreibt die TWS in jedem Intervall dieselbe Datei — der Inhalt ist dann immer
nur der zuletzt geschriebene Tag, und mit dem nächsten Export ist der vorige
weg. Genau die Sackgasse, wegen der die API-Abfrage nicht reicht. Nur bei leerem
Feld vergibt die TWS einen datierten Standardnamen, und nur dann entsteht das
Archiv, auf das die Bridge zugreifen kann.

**Trennzeichen Semikolon.** Zur Auswahl stehen Komma und Semikolon. Die TWS
schreibt Zahlen mit Punkt (`244.21`), also spricht nichts für das Komma — und
gegen es spricht, dass die Datei kein Quoting kennt: ein Komma in einem frei
getippten Kommentar verschiebt alle folgenden Spalten der Zeile. Die Bridge
erkennt beides an der Kopfzeile und liest auch ein Komma-Setup, aber Semikolon
ist die sichere Wahl.

### Spalten

Klick auf **Auswählen…** und alle Spalten aktivieren. Zwingend nötig sind:

`Account`, `Order Ref.`, `ID`, `Symbol`, `Action`, `Quantity`, `Price`, `Date`,
`Time`, `Commission`, `Exch.`

Fehlt eine der ersten sieben, lehnt die Bridge die Datei ab und nennt im
Protokoll die fehlende Spalte. Sie liest keine Datei halb.

### Anderer Ordner

Wer nicht `C:\IBExport` nutzen will, trägt den Pfad in `bridge.env` ein:

```
TWS_EXPORT_DIR=D:\Ordertune\Exports
```

Die Bridge liest diesen Ordner nur. Sie schreibt nichts hinein und lädt die
Dateien nicht hoch — übertragen werden ausschließlich die daraus abgeleiteten
Füllungen, genau wie bei einer Füllung im laufenden Betrieb.

### Prüfen, ob es wirkt

Nach dem ersten Handelstag liegen in `C:\IBExport` Dateien mit einem Datum im
Namen, je Handelstag eine. Liegt dort nur **eine** Datei ohne Datum im Namen,
ist das Namensfeld noch gesetzt.

Die Bridge sagt es auch selbst: sie prüft den Ordner beim Start und bei jeder
neuen Sitzung und benennt im Protokoll und im Bridge-Fenster, **was** fehlt —
Ordner nicht da, keine Datei, fester Dateiname, oder Archiv veraltet.

## 3. Paper vs. Live

- **Paper**: Fantasiekonto, perfekt für erste Tests. Port 7497
- **Live**: echte Trades mit echtem Geld. Port 7496

```
IBKR_GATEWAY_PORT=7497
IBKR_TRADING_MODE=paper
```

Laufen Papier- und Echtkonto auf derselben Maschine und schreiben in denselben
Exportordner, ist das unkritisch: die Bridge liest nur Zeilen ihres eigenen
Kontos.

## 4. Force-Logout um 05:00 CET

IBKR zwingt die TWS **täglich gegen 05:00 CET** zu einem Logout. Ohne
Auto-Login-Mechanismus (**IBC**, siehe [SETUP_IBC.md](SETUP_IBC.md)) müssen Sie
jeden Morgen manuell neu einloggen — sonst schlagen alle Trades am US-Open fehl.

Alternativ trägt `Global Configuration → Lock and Exit → Auto restart` die
Sitzung über mehrere Tage. IBC ist trotzdem die robustere Wahl, weil es auch
einen echten Neustart der Maschine abfängt.

IBC ist Community-Standard, kostenlos, open-source: https://github.com/IbcAlpha/IBC

## Troubleshooting

- **`ib_insync` connect timeout**: TWS läuft nicht, oder der Socket-Port stimmt
  nicht überein
- **Konto-Werte bleiben 0**: die Bridge liest ausschliesslich USD-Kontowerte.
  Läuft das Konto in einer anderen Währung, meldet sie das seit 0.2.2 als
  Warnung im Protokoll
- **Order Precaution Popups**: „Bypass Order Precautions for API Orders" nicht
  aktiviert
- **Client-ID collision**: eine andere Anwendung nutzt bereits die Client-ID 17
  → im `bridge.env` einen anderen Wert setzen (`IBKR_CLIENT_ID=42`)
- **„TWS is not writing trade reports"** im Bridge-Fenster: Abschnitt 2 oben.
  Der Handel läuft weiter; was nicht läuft, ist das Nachtragen einer Füllung,
  die während einer Auszeit der Bridge passiert ist
