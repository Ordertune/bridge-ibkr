#!/usr/bin/env bash
#
# Ordertune Bridge (IBKR) — installer for Linux
# https://github.com/Ordertune/bridge-ibkr
#
# This script downloads the Bridge, verifies its checksum, installs it to
# /opt/ordertune-bridge, creates a service user, installs a systemd unit and
# then walks you through pairing it with your Ordertune account.
#
# It makes no outbound connection other than to github.com, and it starts
# nothing you did not ask for. Read it before you run it.
#
#   sudo ./ordertune-bridge-ibkr-linux-installer.sh
#
# ─────────────────────────────────────────────────────────────────────────────
# T1-206 A / Entscheidung 8 — warum diese Datei ein Skript ist und kein Archiv
#
# Der Owner-Entscheid lautet: neben der `.exe` traegt jedes Release auch eine
# `.sh`. Die woertliche Lesart waere ein selbstentpackendes Archiv (makeself) —
# eine Datei, Programm inklusive. Sie ist verworfen, und zwar aus demselben
# Grund, aus dem auf Linux One-Folder statt One-File gebaut wird: ein
# selbstentpackendes Archiv legt seinen Inhalt beim Ausfuehren in ein
# Temporaerverzeichnis und startet von dort. Auf einem gehaerteten VPS ist
# `/tmp` mit `noexec` eingehaengt, und dann bricht der erste Handgriff des
# Kunden ab, mit einer Meldung, die niemand deutet.
#
# Dieses Skript enthaelt kein Programm. Es fuehrt die Handgriffe aus, die im
# Handbuch ohnehin stehen, in derselben bindenden Reihenfolge — und das
# Programm laeuft anschliessend aus `/opt`. `/tmp` kommt nicht vor: auch der
# Zwischenspeicher liegt unter `/opt`.
#
# Es ist damit **kein zweiter Installationsweg**, nur ein bequemerer Zugang zum
# selben. Der Handweg aus dem `tar.gz` bleibt vollstaendig gangbar und ist in
# DOCS-12 beschrieben.
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

REPO="Ordertune/bridge-ibkr"
ARCHIV="ordertune-bridge-ibkr-linux-x86_64.tar.gz"
BASIS="https://github.com/${REPO}/releases/latest/download"
API="https://api.github.com/repos/${REPO}/releases/latest"

ZIEL="/opt/ordertune-bridge"
BINAER="${ZIEL}/ordertune-bridge-ibkr"
ENV_DATEI="${ZIEL}/bridge.env"
DIENST="ordertune-bridge"
EINHEIT="/etc/systemd/system/${DIENST}.service"
DIENSTNUTZER="ordertune-bridge"
HEIM="/home/${DIENSTNUTZER}"

# Das Berichtsverzeichnis der TWS.
#
# Der Ordner heisst `IBExport` wie auf Windows — gleicher Name, anderer
# Elternordner. Damit steht in der Anleitung EIN Ordnername statt zwei.
#
# Er liegt NICHT unter `/opt/ordertune-bridge`: dieses Skript ersetzt den
# Programmordner bei einer Aktualisierung vollstaendig (`rm -rf`), und das
# Berichtsarchiv liegt dort genau falsch. Es ist die Quelle, mit der eine
# Fuellung nach einer Auszeit der Bridge noch nachtragbar ist — es bei jedem
# Update zu loeschen waere der teuerste denkbare Nebeneffekt.
#
# Er liegt im Heimverzeichnis des Dienstnutzers, weil TWS und Bridge unter
# derselben Kennung laufen (T1-206 Entscheidung 7). Damit gibt es keine
# Rechtefrage, die gepflegt werden muesste.
EXPORT_DIR="${HEIM}/IBExport"

# Der Zwischenspeicher liegt bewusst unter /opt und nicht unter /tmp — siehe
# den Kopf. Ausserdem liegt er damit auf derselben Dateisystem-Ebene wie das
# Ziel, und das Verschieben am Ende ist ein Umbenennen statt eines Kopierens.
STAGE="$(dirname "${ZIEL}")/.ordertune-bridge-install.$$"

rot()   { printf '\033[31m%s\033[0m\n' "$*" >&2; }
fett()  { printf '\033[1m%s\033[0m\n'  "$*"; }
sagen() { printf '%s\n' "$*"; }

# Aufraeumen bei JEDEM Ausgang, auch bei Ctrl+C und bei `set -e`.
#
# Das ist die Zusicherung „bei falscher Summe bleibt nichts Halbes in /opt
# zurueck". Sie darf nicht daran haengen, dass der Abbruchweg daran denkt —
# deshalb ein Trap und kein Aufruf an den Fehlerstellen.
aufraeumen() { rm -rf "${STAGE}"; }
trap aufraeumen EXIT INT TERM

abbruch() {
  sagen
  rot "  $*"
  sagen
  exit 1
}

# ── Was vorhanden sein muss ─────────────────────────────────────────────────

[ "$(id -u)" -eq 0 ] || abbruch "Please run this with sudo: sudo $0"

case "$(uname -m)" in
  x86_64|amd64) ;;
  *) abbruch "This build is x86_64 only. Found: $(uname -m)." ;;
esac

command -v systemctl >/dev/null 2>&1 \
  || abbruch "systemd is required and systemctl was not found."

command -v tar >/dev/null 2>&1 || abbruch "tar is required and was not found."

# `runuser` und nicht `su`: der Dienstnutzer bekommt `nologin` als Shell, und
# `su` geht daran zugrunde. `runuser` fuehrt den Befehl direkt aus.
command -v runuser >/dev/null 2>&1 \
  || abbruch "runuser is required (package util-linux) and was not found."

if command -v curl >/dev/null 2>&1; then
  HOLEN() { curl -fsSL --retry 3 --retry-delay 2 -o "$2" "$1"; }
  LESEN() { curl -fsSL --retry 3 --retry-delay 2 "$1"; }
elif command -v wget >/dev/null 2>&1; then
  HOLEN() { wget -q -O "$2" "$1"; }
  LESEN() { wget -q -O - "$1"; }
else
  abbruch "Either curl or wget is required and neither was found."
fi

if command -v sha256sum >/dev/null 2>&1; then
  SUMME() { sha256sum "$1" | awk '{print $1}'; }
elif command -v shasum >/dev/null 2>&1; then
  SUMME() { shasum -a 256 "$1" | awk '{print $1}'; }
else
  abbruch "sha256sum is required and was not found."
fi

sagen
fett "  Ordertune Bridge — installer"
sagen "  ────────────────────────────────────────────────────────────────"
sagen

# ── Eine bestehende Installation wird nicht still ueberschrieben ────────────
#
# Ein zweiter Lauf auf derselben Maschine ist der Normalfall: so wird
# aktualisiert. Er darf aber nicht unbemerkt eine laufende Bridge anhalten —
# zwischen „Programm ersetzt" und „Dienst wieder oben" liegt ein Fenster, in
# dem kein Auftrag abgeholt wird, und der Kunde soll wissen, dass er es
# oeffnet.
AKTUALISIERUNG=0
if [ -e "${ZIEL}" ]; then
  AKTUALISIERUNG=1
  fett "  An installation already exists at ${ZIEL}."
  if systemctl is-active --quiet "${DIENST}" 2>/dev/null; then
    sagen "  The service is running right now."
    sagen "  Updating stops it, replaces the program and starts it again."
    sagen "  While it is stopped, no orders are picked up."
  else
    sagen "  The service is not running."
  fi
  if [ -f "${ENV_DATEI}" ]; then
    sagen "  Your bridge.env will be kept. You do not need to pair again."
  fi
  sagen
  if [ -t 0 ]; then
    read -r -p "  Continue and update? [y/N] " antwort
    case "${antwort}" in
      y|Y|yes|YES) ;;
      *) sagen; sagen "  Left untouched. Nothing was changed."; exit 1 ;;
    esac
  else
    abbruch "Refusing to update without a confirmation. Run this on a terminal."
  fi
  sagen
fi

# ── Herunterladen und nachrechnen ───────────────────────────────────────────

mkdir -p "${STAGE}"

FASSUNG="$(LESEN "${API}" 2>/dev/null \
  | grep -m1 '"tag_name"' \
  | sed -E 's/.*"tag_name"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/' || true)"
[ -n "${FASSUNG}" ] || FASSUNG="(latest)"

sagen "  Version:  ${FASSUNG}"
sagen "  Source:   ${BASIS}/${ARCHIV}"
sagen

sagen "  Downloading..."
HOLEN "${BASIS}/${ARCHIV}" "${STAGE}/${ARCHIV}" \
  || abbruch "Download failed. Check the machine's internet connection."

# Die Summe liegt als eigener Anhang im selben Release und steht zusaetzlich in
# der Release-Notiz.
#
# Ehrlich gesagt, was dieser Abgleich leistet und was nicht: er faengt eine
# abgebrochene oder auf dem Weg beschaedigte Datei, und er gibt dem Kunden
# einen Wert, den er gegen die Release-Seite halten kann. Er ist **kein**
# Ersatz fuer eine Signatur — wer GitHub faelschen koennte, faelschte beide
# Dateien. Auf Linux gibt es kein Gegenstueck zum EV-Zertifikat; das ist der
# Stand, und ihn zu beschoenigen waere schlechter als ihn zu nennen.
sagen "  Verifying checksum..."
ERWARTET="$(LESEN "${BASIS}/${ARCHIV}.sha256" 2>/dev/null | awk '{print $1}' || true)"
[ -n "${ERWARTET}" ] \
  || abbruch "Could not fetch the checksum. Nothing was installed."

GEFUNDEN="$(SUMME "${STAGE}/${ARCHIV}")"
if [ "${ERWARTET}" != "${GEFUNDEN}" ]; then
  sagen
  rot "  CHECKSUM MISMATCH — nothing was installed."
  sagen "    expected  ${ERWARTET}"
  sagen "    found     ${GEFUNDEN}"
  sagen
  sagen "  Do not run the downloaded file. Try again; if it keeps failing,"
  sagen "  report it at https://github.com/${REPO}/issues"
  sagen
  exit 1
fi
sagen "  SHA-256 ok: ${GEFUNDEN}"
sagen

tar -xzf "${STAGE}/${ARCHIV}" -C "${STAGE}" \
  || abbruch "Could not unpack the archive. Nothing was installed."

[ -x "${STAGE}/ordertune-bridge-ibkr/ordertune-bridge-ibkr" ] \
  || abbruch "The archive does not have the expected layout. Nothing was installed."

# ── Dienstnutzer ────────────────────────────────────────────────────────────
#
# Mit Heimverzeichnis, und das ist keine Formalie: `paths.data_root()` legt
# `submitted-dispatches.json` unter `~/.local/share/ordertune-bridge` ab — den
# Riegel gegen den Doppelauftrag, dessen ganzer Zweck es ist, den Neustart zu
# ueberleben. Ein Dienstnutzer ohne Heimverzeichnis fuehrt ohne Fehlermeldung
# dorthin, dass die Bridge vergisst, was sie schon abgesendet hat.

if id -u "${DIENSTNUTZER}" >/dev/null 2>&1; then
  sagen "  Service user ${DIENSTNUTZER} already exists."
else
  sagen "  Creating service user ${DIENSTNUTZER}..."
  useradd --system --create-home --home-dir "${HEIM}" \
          --shell /usr/sbin/nologin "${DIENSTNUTZER}" \
    || abbruch "Could not create the service user. Nothing was installed."
fi

# Auch im Bestandsfall: ein frueher ohne `--create-home` angelegter Nutzer hat
# genau das Loch, das oben beschrieben ist.
install -d -o "${DIENSTNUTZER}" -g "${DIENSTNUTZER}" -m 0755 "${HEIM}"
install -d -o "${DIENSTNUTZER}" -g "${DIENSTNUTZER}" -m 0755 \
        "${HEIM}/.local/share/ordertune-bridge"

# Der Ordner wird angelegt, BEVOR der Kunde die TWS einstellt. Zwei Gruende,
# und beide sparen einen Support-Fall: der Verzeichnis-Auswaehler der TWS zeigt
# ihn dann an (statt dass der Kunde einen Pfad blind eintippt), und die
# Bereitschaftspruefung startet nicht bei `no_dir`, was wie ein Fehler aussieht,
# obwohl nur noch nichts exportiert wurde.
install -d -o "${DIENSTNUTZER}" -g "${DIENSTNUTZER}" -m 0755 "${EXPORT_DIR}"

# ── Einspielen ──────────────────────────────────────────────────────────────

if [ "${AKTUALISIERUNG}" -eq 1 ] && systemctl is-active --quiet "${DIENST}" 2>/dev/null; then
  sagen "  Stopping ${DIENST}..."
  systemctl stop "${DIENST}"
fi

# `bridge.env` ueberlebt eine Aktualisierung. Sie ist die Datei des Kunden —
# Token, Port, Protokollstufe, und jeder Kommentar, den er hineingeschrieben
# hat. Sie mitzuersetzen hiesse, ihn nach jedem Update neu koppeln zu lassen.
if [ -f "${ENV_DATEI}" ]; then
  cp -p "${ENV_DATEI}" "${STAGE}/bridge.env.behalten"
fi

sagen "  Installing to ${ZIEL}..."
rm -rf "${ZIEL}"
mkdir -p "${ZIEL}"
cp -a "${STAGE}/ordertune-bridge-ibkr/." "${ZIEL}/"
if [ -f "${STAGE}/README.txt" ]; then
  cp -a "${STAGE}/README.txt" "${ZIEL}/"
fi

if [ -f "${STAGE}/bridge.env.behalten" ]; then
  cp -p "${STAGE}/bridge.env.behalten" "${ENV_DATEI}"
fi

chown -R "${DIENSTNUTZER}:${DIENSTNUTZER}" "${ZIEL}"
chmod 0755 "${BINAER}"
if [ -f "${ENV_DATEI}" ]; then
  chmod 0600 "${ENV_DATEI}"
fi

sagen "  Installing the systemd unit..."
cp -a "${STAGE}/ordertune-bridge.service" "${EINHEIT}"
chmod 0644 "${EINHEIT}"
systemctl daemon-reload

sagen
fett "  Installed: ${FASSUNG}"
sagen

# ── Koppeln ─────────────────────────────────────────────────────────────────
#
# `--pair` laeuft **als der Dienstnutzer**, und das ist die Stelle, an der ein
# Handweg am haeufigsten schiefgeht. Wer als er selbst koppelt, schreibt eine
# `bridge.env`, die dem Dienst spaeter nicht gehoert — und der startet dann in
# genau den Fehler, den niemand erwartet, weil die Kopplung ja geklappt hat.

if [ -f "${ENV_DATEI}" ] && grep -q '^ORDERTUNE_BRIDGE_TOKEN=..*' "${ENV_DATEI}" 2>/dev/null; then
  sagen "  Existing credentials kept — no pairing needed."
else
  fett "  Now pair this Bridge with your Ordertune account."
  sagen

  # Zwei Dinge muessen hier stimmen, und beide sind unsichtbar, wenn sie
  # falsch sind.
  #
  # **Das Arbeitsverzeichnis.** `main()` loest die Datei als
  # `Path("bridge.env").resolve()` auf — also gegen das ARBEITSVERZEICHNIS,
  # nicht gegen den Programmordner. Auf Windows faellt das nie auf, weil ein
  # Doppelklick beides gleichsetzt. Hier nicht: ohne `cd` landet die frisch
  # gekoppelte `bridge.env` in dem Ordner, aus dem dieses Skript gestartet
  # wurde, und der Dienst startet spaeter in einen Konfigurationsfehler,
  # obwohl die Kopplung sichtbar geklappt hat.
  #
  # **`$HOME`.** `runuser -u` wechselt die Kennung, aber NICHT die Umgebung —
  # `$HOME` bliebe `/root`. Die Bridge leitet daraus ihre Ablage und den
  # Vorschlag fuer das Berichtsverzeichnis ab. Beides zeigte dann auf das
  # Heimverzeichnis von root, auf das der Dienst spaeter keinen Zugriff hat.
  if ! ( cd "${ZIEL}" && runuser -u "${DIENSTNUTZER}" -- \
           env HOME="${HEIM}" "${BINAER}" --pair ); then
    sagen
    rot "  Pairing did not complete."
    sagen "  The program is installed. You can pair later with:"
    sagen "    cd ${ZIEL} && sudo runuser -u ${DIENSTNUTZER} -- \\"
    sagen "      env HOME=${HEIM} ${BINAER} --pair"
    sagen
    exit 1
  fi
fi

# ── Starten ─────────────────────────────────────────────────────────────────

sagen "  Enabling and starting ${DIENST}..."
systemctl enable --now "${DIENST}"

sleep 3
if systemctl is-active --quiet "${DIENST}"; then
  sagen
  fett "  Done. The Bridge is running and will start again after a reboot."
  sagen
  sagen "  Check it:   systemctl status ${DIENST}"
  sagen "  Follow it:  journalctl -u ${DIENST} -f"
  sagen "  Settings:   ${ENV_DATEI}"
  sagen
  fett "  One step is still yours: point TWS at the report folder."
  sagen
  sagen "  The Bridge reads this folder. TWS has to write to exactly it —"
  sagen "  a typo here is invisible: TWS will happily export somewhere else"
  sagen "  and everything looks fine until a fill goes missing."
  sagen
  sagen "  In TWS:  Global Configuration -> Export Reports"
  sagen
  sagen "    Directory        ${EXPORT_DIR}"
  sagen "    Export filename  leave EMPTY"
  sagen "    Field separator  semicolon"
  sagen "    Export trade reports periodically: on"
  sagen
  sagen "  Leave the filename empty: a fixed name makes TWS overwrite the same"
  sagen "  file every interval, and only the most recent day survives."
  sagen
  sagen "  TWS must run on this machine, as ${DIENSTNUTZER}, with a display"
  sagen "  (Xvfb is enough). The IB Gateway cannot export reports at all."
  sagen
  fett "  Then check it — do not guess:"
  sagen
  sagen "    sudo runuser -u ${DIENSTNUTZER} -- \\"
  sagen "      env HOME=${HEIM} ${BINAER} --check-reports"
  sagen
  sagen "  It says in one line whether the Bridge can read what TWS writes."
  sagen
  sagen "  Full guide: https://docs.ordertune.com/brokers/"
  sagen

  # Einmal gleich hier, damit der Kunde den Ausgangszustand sieht und den
  # Befehl schon einmal in Aktion hatte. Der Befund ist an dieser Stelle
  # erwartbar `no_file` — die TWS hat ja noch nicht exportiert. Genau deshalb
  # haelt er den Lauf NICHT an: ein roter Abschluss fuer einen erwarteten
  # Zustand erzieht dazu, den Befund zu ignorieren.
  ( cd "${ZIEL}" && runuser -u "${DIENSTNUTZER}" -- \
      env HOME="${HEIM}" "${BINAER}" --check-reports ) || true
  sagen
else
  sagen
  rot "  The service did not come up."
  sagen "  Look at why:  journalctl -u ${DIENST} -n 50 --no-pager"
  sagen
  exit 1
fi
