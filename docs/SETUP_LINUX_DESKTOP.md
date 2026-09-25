# Linux-Desktop Setup

Für eine Linux-Maschine **mit grafischer Oberfläche** — Debian, Ubuntu, egal ob
lokal, per VNC oder per RDP bedient. Trader Workstation läuft dort in einem
Fenster, so wie auf Windows, und die Bridge daneben.

Das ist der Weg für den Kunden, den dieser Vorgang meint: jemand, der sich die
Windows-Lizenz spart und sonst nichts anders machen will. Für eine Maschine
ohne Desktop siehe [SETUP_LINUX_SERVER.md](SETUP_LINUX_SERVER.md).

## Warum das der einfachere Weg ist

**Weil die Bridge ihn schon kann, ohne eine Zeile Sonderbehandlung.**
`cockpit/window.py` überspringt auf Nicht-Windows nur Edge und ruft dann
`webbrowser.open()`. Auf einem Desktop geht damit genau dasselbe
Einrichtungsfenster auf wie unter Windows — derselbe Assistent, derselbe
Kopplungscode, danach dasselbe Cockpit.

Es entfällt damit alles, was den Serverweg ausmacht:

| | Server | Desktop |
|---|---|---|
| `sudo` | überall | **nirgends** |
| Dienstnutzer | `ordertune-bridge` | dein Anmeldenutzer |
| Ablageort | `/opt/ordertune-bridge` | ein Ordner im Heimverzeichnis |
| Kopplung | `--pair` in der Konsole | Fenster im Browser, wie Windows |
| Dauerbetrieb | systemd-Unit | Autostart der Sitzung |
| Berichtsverzeichnis | `/home/ordertune-bridge/IBExport` | dein `~/IBExport` |

Die letzte Zeile ist der Grund, warum die beiden Wege sich nicht mischen
lassen: TWS und Bridge müssen unter **derselben** Kennung laufen. Auf dem
Desktop ist das deine, und ein Dienstnutzer daneben zerreisst genau das.

## 1 — Trader Workstation

IBKR liefert für Linux einen grafischen Installer, und zwar selbst als `.sh`.
Von der [TWS-Downloadseite](https://www.interactivebrokers.com/en/trading/tws.php)
holen, dann:

```bash
chmod +x tws-latest-standalone-linux-x64.sh
./tws-latest-standalone-linux-x64.sh
```

Ohne `sudo`. Installiert nach `~/Jts` und legt einen Menüeintrag an. Starten,
mit dem **Paper-Konto** anmelden.

## 2 — Trader Workstation einstellen

Identisch zu Windows — dieselben Dialoge, dieselbe Reihenfolge. Es gilt
[SETUP_TWS.md](SETUP_TWS.md) Wort für Wort, mit genau einer Abweichung:

```
Global Configuration -> Export Reports
  Directory        /home/<dein-nutzer>/IBExport
  Export filename  LEER LASSEN
  Field separator  semicolon
  Export trade reports periodically: on
```

Ordner vorher anlegen:

```bash
mkdir -p ~/IBExport
```

Das ist zugleich der Vorschlag, den die Bridge macht, wenn nichts konfiguriert
ist (`trade_reports.standard_verzeichnis()` → `~/IBExport`). Ein Wert weniger,
der an zwei Stellen übereinstimmen muss.

## 3 — Die Bridge ablegen

```bash
mkdir -p ~/ordertune-bridge && cd ~/ordertune-bridge

wget https://github.com/Ordertune/bridge-ibkr/releases/latest/download/ordertune-bridge-ibkr-linux-x86_64.tar.gz
wget https://github.com/Ordertune/bridge-ibkr/releases/latest/download/ordertune-bridge-ibkr-linux-x86_64.tar.gz.sha256
sha256sum -c <<< "$(cat ordertune-bridge-ibkr-linux-x86_64.tar.gz.sha256)  ordertune-bridge-ibkr-linux-x86_64.tar.gz"

tar -xzf ordertune-bridge-ibkr-linux-x86_64.tar.gz --strip-components=1 ordertune-bridge-ibkr
rm ordertune-bridge-ibkr-linux-x86_64.tar.gz*
```

`--strip-components=1` zieht den Inhalt des Programmordners eine Ebene hoch.
Danach liegen `ordertune-bridge-ibkr` und `_internal` direkt in
`~/ordertune-bridge` — dasselbe Bild wie der Ordner auf dem Windows-Desktop,
und `bridge.env` kommt später daneben.

**Der Installer aus dem Release ist hier ausdrücklich nicht gemeint.** Er baut
die Server-Variante und fragt auf einer grafischen Maschine nach, bevor er das
tut.

## 4 — Starten und koppeln

```bash
cd ~/ordertune-bridge && ./ordertune-bridge-ibkr
```

### Und der Doppelklick?

Von unserer Seite ja: seit T1-206 sucht die Bridge `bridge.env` **neben dem
Programm** und nicht mehr im Arbeitsverzeichnis, also ist es gleichgültig, von
wo sie gestartet wird. Das Ausführbar-Bit überlebt das Archiv auch.

Ob der Dateimanager eine nackte ausführbare Datei per Doppelklick **startet**,
entscheidet aber der Desktop, nicht wir:

| Dateimanager | Doppelklick auf das Binary |
|---|---|
| GNOME Files (Debians Standard) | meist **nicht** — GNOME führt ELF-Dateien bewusst nicht aus |
| KDE Dolphin | fragt nach, dann läuft es |
| XFCE Thunar | fragt meist nach, dann läuft es |

Das ist eine Sicherheitsentscheidung der jeweiligen Oberfläche. Das
verlässliche Gegenstück zum Windows-Doppelklick ist deshalb ein **Menü-Eintrag**
— siehe Schritt 5.

Der Browser geht auf, der Assistent zeigt den Kopplungscode, du tippst ihn in
t1 unter **Settings → Broker** ein und bestätigst. Vergleiche vorher Rechnername
und Fingerabdruck auf beiden Seiten — sie stehen dort für genau diesen
Vergleich.

Ab hier ist alles identisch zu Windows, das Cockpit eingeschlossen.

## 5 — Ins Menü legen, und bei der Anmeldung mitstarten

Zwei `.desktop`-Dateien, gleicher Inhalt, zwei Orte und zwei Zwecke. Das
verwechselt man leicht, deshalb beide ausgeschrieben.

### Menü-Eintrag — das Gegenstück zum Doppelklick

```bash
mkdir -p ~/.local/share/applications
cat > ~/.local/share/applications/ordertune-bridge.desktop <<EOF
[Desktop Entry]
Type=Application
Name=Ordertune Bridge
Comment=Connects Trader Workstation with Ordertune
Exec=$HOME/ordertune-bridge/ordertune-bridge-ibkr
Path=$HOME/ordertune-bridge
Icon=$HOME/ordertune-bridge/ordertune-bridge.png
Terminal=false
Categories=Office;Finance;
EOF
```

Danach steht „Ordertune Bridge" im Anwendungsmenü und lässt sich in die
Favoritenleiste ziehen — ein Symbol zum Anklicken, wie die `.exe` auf dem
Windows-Desktop.

Das Symbol liegt seit T1-206 im Programmordner (`ordertune-bridge.png`, das
Marken-Glyph). Es wird beim Bauen aus `cockpit/assets.py:ICON_PNG` erzeugt, also
aus derselben Quelle wie das Windows-Symbol — es gibt kein zweites Markenbild,
das auseinanderlaufen könnte.

### Autostart — mit der Anmeldung hochkommen

Dasselbe noch einmal, an einem anderen Ort:

```bash
mkdir -p ~/.config/autostart
cat > ~/.config/autostart/ordertune-bridge.desktop <<EOF
[Desktop Entry]
Type=Application
Name=Ordertune Bridge
Exec=$HOME/ordertune-bridge/ordertune-bridge-ibkr
Path=$HOME/ordertune-bridge
Terminal=false
X-GNOME-Autostart-enabled=true
EOF
```

`Path=` setzt das Arbeitsverzeichnis. Nötig ist es seit T1-206 nicht mehr, aber
es kostet nichts und hält die Protokolle dort, wo man sie sucht.

**Beide Dateien anlegen ist kein Fehler**, sondern der Normalfall: die eine
macht das Programm anklickbar, die andere startet es ohne Klick.

**Keine systemd-Unit.** Sie liefe ohne Anzeigesitzung, und dann gäbe es weder
Cockpit noch eine TWS, mit der zu reden wäre. Auf dem Desktop hängen beide an
der Sitzung — das ist dieselbe Bauweise wie unter Windows und kein Rückschritt.

TWS genauso: sie bringt ihren eigenen Autostart-Eintrag mit. Für den täglichen
Zwangs-Logout um 05:00 CET ist IBC zuständig, auf Linux mit `twsstart.sh`.

## 6 — Nachprüfen

```bash
cd ~/ordertune-bridge && ./ordertune-bridge-ibkr --check-reports
```

Sagt in einer Zeile, ob die Bridge liest, was die TWS schreibt. Braucht weder
eine laufende TWS noch eine Verbindung. Ausgangscode 0 heisst: taugt als Quelle.

Direkt nach der Einrichtung ist `no_file` erwartbar — die TWS exportiert im
Intervall. Am nächsten Morgen ist es ein Befund.

## Fallen

| Symptom | Ursache |
|---|---|
| TWS startet nicht | Kein Display. Auf einem Desktop unüblich; per RDP prüfen, ob die Sitzung wirklich steht. |
| Kryptischer Ladefehler der Bridge | glibc zu alt. `ldd --version`; gebaut wird gegen Ubuntu 22.04. |
| `unreadable` beim Berichtsverzeichnis | TWS und Bridge laufen unter verschiedenen Kennungen. Auf dem Desktop heisst das meist: jemand hat doch den Server-Installer benutzt. |
| Nach dem Abmelden ist die Bridge weg | Erwartbar. Sie hängt an der Sitzung, wie unter Windows. Wer das nicht will, braucht den Serverweg. |
