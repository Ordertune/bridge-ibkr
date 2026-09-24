# Linux-Server Setup (ohne Desktop)

> **Das ist einer von zwei Linux-Wegen, und wahrscheinlich nicht deiner.**
>
> Dieser hier ist für eine Maschine, an der niemand angemeldet ist: Dienstnutzer,
> systemd, Kopplung über die Konsole. Den anderen — **Linux mit grafischer
> Oberfläche**, TWS im Fenster, Bridge wie unter Windows — beschreibt
> [SETUP_LINUX_DESKTOP.md](SETUP_LINUX_DESKTOP.md), und er ist der einfachere.
>
> Wer den Desktop-Fall hier hineinzwingt, bekommt den teuersten aller
> Fehlzustände: der Dienstnutzer liest `/home/ordertune-bridge/IBExport`,
> während die TWS unter der Kennung des Menschen nach dessen `~/IBExport`
> schreibt. Zwei Orte, keine Meldung, kein Sicherungsnetz.

Technisches Gegenstück zu [SETUP_WINDOWS_VPS.md](SETUP_WINDOWS_VPS.md) — für
Support und Entwicklung. **Das Kundenhandbuch ist
<https://docs.ordertune.com/brokers/>** (DOCS-12) und die einzige Anleitung, die
dem Kunden genannt wird; DOCS-9 heisst „Ein Installationsweg, eine Quelle", und
diese Datei darf das nicht aufweichen.

Zugesagt sind **Ubuntu 22.04 LTS, Ubuntu 24.04 LTS und Debian 12 auf x86_64**.
Anderes läuft vermutlich, ohne Zusage.

## Was Linux spart — und was nicht

Es spart die **Windows-Lizenz**. Es spart seit T1-207 **keinen Arbeitsspeicher
mehr**: die Bridge verlangt die TWS (das IB Gateway hat keine Berichtsfunktion),
und die TWS ist ein Java-Swing-Programm, das zwingend ein Display braucht. Wer
das anders verkauft, verkauft etwas, das der Kunde nachmisst.

## Der schnelle Weg

```
wget https://github.com/Ordertune/bridge-ibkr/releases/latest/download/ordertune-bridge-ibkr-linux-installer.sh
chmod +x ordertune-bridge-ibkr-linux-installer.sh
sudo ./ordertune-bridge-ibkr-linux-installer.sh
```

Das Skript erledigt genau die Handgriffe, die unten einzeln stehen. Es ist
lesbarer Text und kein selbstentpackendes Archiv — siehe „Warum kein makeself".

## Der Handweg

Er ist nicht zweitklassig; das Skript führt ihn aus, mehr nicht.

```bash
# 1. Nutzlast holen und nachrechnen
wget https://github.com/Ordertune/bridge-ibkr/releases/latest/download/ordertune-bridge-ibkr-linux-x86_64.tar.gz
wget https://github.com/Ordertune/bridge-ibkr/releases/latest/download/ordertune-bridge-ibkr-linux-x86_64.tar.gz.sha256
sha256sum -c <<< "$(cat ordertune-bridge-ibkr-linux-x86_64.tar.gz.sha256)  ordertune-bridge-ibkr-linux-x86_64.tar.gz"

# 2. Dienstnutzer MIT Heimverzeichnis
sudo useradd --system --create-home --home-dir /home/ordertune-bridge \
     --shell /usr/sbin/nologin ordertune-bridge

# 3. Entpacken nach /opt — die Inhalte des Programmordners, nicht den Ordner
tar -xzf ordertune-bridge-ibkr-linux-x86_64.tar.gz
sudo mkdir -p /opt/ordertune-bridge
sudo cp -a ordertune-bridge-ibkr/. /opt/ordertune-bridge/
sudo chown -R ordertune-bridge:ordertune-bridge /opt/ordertune-bridge

# 4. Koppeln — ALS DER DIENSTNUTZER, aus dem Programmordner heraus
cd /opt/ordertune-bridge && sudo runuser -u ordertune-bridge -- \
  env HOME=/home/ordertune-bridge ./ordertune-bridge-ibkr --pair

# 5. Einheit setzen und starten
sudo cp ordertune-bridge.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ordertune-bridge
```

### Schritt 4 ist der, an dem es schiefgeht

Zwei Dinge daran sind unsichtbar, wenn sie falsch sind.

**`cd /opt/ordertune-bridge`.** Seit T1-206 sucht die Bridge `bridge.env`
neben dem Programm (`paths.env_file()`), also ist das `cd` keine Bedingung
mehr — es schadet aber nichts und hält die Befehlszeile bei dem, was auch im
Handbuch steht.

Bis dahin war es Pflicht, und der Fehler war teuer: `main()` löste die Datei
gegen das **Arbeitsverzeichnis** auf, obwohl der Kopf von `paths.py` das
Gegenteil behauptete. Ohne `cd` landete die frisch gekoppelte `bridge.env`
dort, wo der Befehl abgesetzt wurde — die Kopplung meldete Erfolg, und der
Dienst startete später in `env_missing`.

**`env HOME=…`.** `runuser -u` wechselt die Kennung, nicht die Umgebung.
`$HOME` bliebe das des Aufrufers, und daraus leitet die Bridge ihre Ablage
(`~/.local/share/ordertune-bridge`) und den Vorschlag für das
Berichtsverzeichnis (`~/IBExport`) ab.

**Und: als der Dienstnutzer, nicht als man selbst.** Wer als er selbst koppelt,
schreibt eine `bridge.env`, die dem Dienst nicht gehört.

## Das Heimverzeichnis ist keine Formalie

`paths.data_root()` legt im gepackten Zustand `submitted-dispatches.json` unter
`~/.local/share/ordertune-bridge` ab — den Riegel gegen den Doppelauftrag aus
T1-103 H, dessen ganzer Zweck es ist, den Neustart zu überleben.

Ein Dienstnutzer ohne Heimverzeichnis führt **ohne Fehlermeldung** dazu, dass
die Bridge über einen Neustart hinweg vergisst, was sie schon abgesendet hat:
`place_order` gelingt, `ack_order` scheitert, der nächste Abruf liefert denselben
Auftrag erneut aus — zwei Echtaufträge.

Deshalb prüft die Bridge das seit T1-206 beim Start (`paths.probe_writable`) und
schreibt eine Warnung, die den Riegel namentlich nennt. Der Handel läuft weiter;
still bleibt es nicht.

## TWS und Bridge unter derselben Kennung

Seit T1-207 liest die Bridge ein Verzeichnis, das ein **fremdes Programm**
schreibt. Damit zählt erstmals, wer schreibt und wer liest — auf Windows liefen
beide immer unter demselben angemeldeten Nutzer, und die Frage tauchte nie auf.

Die Auflösung ist nicht Gruppenrechte, sondern sie gar nicht erst entstehen zu
lassen: **Xvfb, IBC mit der TWS und die Bridge laufen alle unter
`ordertune-bridge`**, jeweils als eigene Einheit. Ein Dienstnutzer, drei
Einheiten, eine Rechtewelt.

Laufen sie auseinander, meldet die Bereitschaftsprüfung `unreadable` — richtig
erkannt, aber erst auf dem Kundenserver.

TWS und IBC liefern wir nicht mit und installieren sie nicht — die IBKR-Lizenz
verbietet die Weitergabe. Das ist auf Windows genauso.

## Das Berichtsverzeichnis — der eine Handgriff, den wir nicht abnehmen können

Die Einrichtung der TWS unterscheidet sich zwischen Windows und Linux **kaum**:
derselbe Dialog, dieselben Schalter, dieselbe Reihenfolge. Es gibt genau eine
Stelle, die sich unterscheidet, und sie ist zugleich die einzige, an der ein
Fehler teuer wird — **wohin die TWS ihre Tagesberichte schreibt.**

| | Windows | Linux |
|---|---|---|
| Ordner | `C:\IBExport` | `/home/ordertune-bridge/IBExport` |
| Angelegt von | dem Kunden | **dem Installer** |
| Gehört | dem angemeldeten Nutzer | `ordertune-bridge` |

Der Ordnername ist auf beiden Plattformen derselbe. Nur der Elternordner
unterscheidet sich — in der Anleitung ist das **ein** Ordnername mit zwei
Präfixen, nicht zwei Anleitungen.

### Warum genau dort und nirgendwo sonst

**Nicht unter `/opt/ordertune-bridge`.** Der Installer ersetzt den
Programmordner bei einer Aktualisierung vollständig. Läge das Archiv dort, wäre
es nach jedem Update weg — und das Archiv ist genau die Quelle, mit der eine
Füllung nach einer Auszeit der Bridge noch nachtragbar ist. Der teuerste
denkbare Nebeneffekt eines Updates.

**Im Heimverzeichnis des Dienstnutzers**, weil TWS und Bridge unter derselben
Kennung laufen (Entscheidung 7). Damit entsteht die Rechtefrage gar nicht erst,
statt gepflegt zu werden.

**Vom Installer angelegt, bevor die TWS eingestellt wird.** Zwei Gründe, beide
sparen einen Support-Fall: der Verzeichnis-Auswähler der TWS zeigt den Ordner
dann an, statt dass der Kunde einen Pfad blind eintippt — und die
Bereitschaftsprüfung startet nicht bei `no_dir`, was wie ein Fehler aussieht,
obwohl nur noch nichts exportiert wurde.

### Was einzutragen ist

```
Global Configuration -> Export Reports

  Directory        /home/ordertune-bridge/IBExport
  Export filename  LEER LASSEN
  Field separator  semicolon
  Export trade reports periodically: on
```

Zwei davon sind Fallen, die sich nicht von selbst zeigen:

* **Ein eingetragener Dateiname** lässt die TWS in jedem Intervall dieselbe
  Datei schreiben. Nur der zuletzt geschriebene Tag überlebt — dieselbe
  Sackgasse wie `reqExecutions`, nur mit mehr Schritten. Belegt an
  `IBTrades7497.csv`.
* **Ein Komma als Trennzeichen** zerbricht Zeilen, weil IBKR nicht quotet.

### Und dann nachprüfen, nicht glauben

Ein Tippfehler im Pfad fällt **nicht** auf. Die TWS legt den Ordner an, den sie
bekommt, exportiert fleissig dorthin, und alles sieht richtig aus. Bemerkt wird
es an einer Füllung, die nach einer Auszeit fehlt — also dann, wenn es zu spät
ist.

Deshalb gibt es seit T1-206 einen Befehl, der die Frage beantwortet:

```
cd /opt/ordertune-bridge && sudo runuser -u ordertune-bridge -- \
  env HOME=/home/ordertune-bridge ./ordertune-bridge-ibkr --check-reports
```

Er braucht **keine laufende TWS und keine Verbindung** — die Frage hängt an der
Platte. Sein Ausgangscode ist 0, wenn das Archiv als Quelle taugt, sonst 1; er
lässt sich also in eine Einrichtungsroutine hängen.

Die Befunde, die er nennt, und was sie heissen:

| Befund | Heisst |
|---|---|
| `ok` | Die Bridge liest, was die TWS schreibt. Fertig. |
| `not_configured` | `TWS_EXPORT_DIR` steht nicht in `bridge.env`. |
| `no_dir` | Der Ordner existiert nicht — meist ein Tippfehler im TWS-Dialog. |
| `unreadable` | TWS und Bridge laufen unter **verschiedenen** Kennungen. |
| `no_file` | Ordner da, noch keine Datei. Direkt nach der Einrichtung normal; die TWS exportiert im Intervall. |
| `fixed_name` | Die Dateien tragen kein Datum — das Feld „Export filename" ist gefüllt und muss leer sein. |
| `stale` | Die jüngste Datei ist über vier Tage alt. Entweder lief die TWS nicht, oder der periodische Export ist aus. |

Der Installer führt den Befehl am Ende selbst einmal aus, damit der Kunde den
Ausgangszustand sieht. `no_file` ist dort erwartbar und hält den Lauf nicht an.

## Fallen, die nur hier auftreten

| Symptom | Ursache |
|---|---|
| Verbindungs-Timeout, „niemand auf dem Port" | Die TWS läuft nicht, weil kein Display da ist. Xvfb prüfen. |
| Kryptischer Ladefehler beim Start | glibc zu alt. `ldd --version`; gebaut wird gegen 22.04. |
| Verbunden, grün, trägt aber nichts nach | `IBKR_TWS_HOST` zeigt auf eine andere Maschine, `TWS_EXPORT_DIR` wird **lokal** gelesen. |
| `unreadable` in der Bereitschaftsprüfung | TWS und Bridge laufen unter verschiedenen Kennungen. |
| Dienst läuft, Ablage nicht schreibbar | Dienstnutzer ohne Heimverzeichnis. Siehe oben. |

SELinux/AppArmor auf RHEL-Derivaten: ausserhalb der Zusage.

## Warum kein makeself

Der Owner-Entscheid lautet „neben der `.exe` auch eine `.sh`". Die wörtliche
Lesart wäre ein selbstentpackendes Archiv — eine Datei, Programm inklusive.
Verworfen, und zwar aus demselben Grund, aus dem auf Linux One-Folder statt
One-File gebaut wird: es entpackt beim Ausführen nach `/tmp` und startet von
dort, und auf einem gehärteten VPS ist `/tmp` mit `noexec` eingehängt.

Wir hätten die Fehlerklasse damit vom Programmstart auf die Installation
verschoben und dabei behauptet, sie sei fort. Der Release-Workflow stellt den
Fall deshalb nach (`Prove it starts with noexec on /tmp`); ein One-File-Bündel
fällt dort durch.

## Update

```
sudo ./ordertune-bridge-ibkr-linux-installer.sh
```

Ein zweiter Lauf fragt nach, hält den Dienst an, ersetzt das Programm und
startet ihn wieder. **`bridge.env` bleibt erhalten** — es wird nicht neu
gekoppelt. Von Hand: Dienst anhalten, `/opt/ordertune-bridge` ersetzen,
`bridge.env` zurücklegen, Dienst starten.

## Nachsehen

```
systemctl status ordertune-bridge
journalctl -u ordertune-bridge -f
sudo -u ordertune-bridge cat /home/ordertune-bridge/.local/share/ordertune-bridge/logs/bridge.log
```
