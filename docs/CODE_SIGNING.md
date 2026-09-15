# Code Signing — Beschaffung und Einrichtung

Dieses Dokument gehört zu T1-182. Es beschreibt, warum die ausgelieferte EXE
bis 0.23.2 „Unknown publisher" meldete, was dagegen zu tun ist, und was es
**nicht** löst.

---

## Die wichtigste Erwartung zuerst

> Eine Signatur lässt die Warnung nicht sofort verschwinden.

Das ist die Nachricht, die man am liebsten anders hätte. Microsoft hat 2024
geändert, wie SmartScreen mit Zertifikaten umgeht. Früher galt: ein
EV-Zertifikat bringt sofortigen guten Ruf, die Warnung bleibt von der ersten
Datei an weg. Das gilt nicht mehr. Heute müssen **OV- und EV-Zertifikate
gleichermaßen** erst Reputation aufbauen, und Reputation entsteht daraus, dass
genügend Leute die Datei herunterladen und ausführen, ohne dass etwas
Auffälliges passiert.

Was die Signatur **sofort** ändert:

| | unsigniert | signiert, ohne Reputation |
|---|---|---|
| Herausgeber im Dialog | `Unknown publisher` | der geprüfte Name |
| Aussage des Dialogs | „unbekannte App" | „unbekannter Herausgeber ist geprüft" |
| Datei nachweislich unverändert | nein | ja |
| Warnung beim ersten Start | ja | ja |
| Warnung nach genügend Downloads | bleibt für immer | fällt weg |

Der Unterschied ist also nicht „Warnung weg", sondern: die Warnung hört auf,
dauerhaft zu sein, und der Kunde sieht im Dialog einen Namen, den er
wiedererkennt, statt `Unknown publisher`. Ohne Zertifikat baut sich nie
Reputation auf — jede Fassung startet bei null, für immer.

**Reputation hängt am Zertifikat, nicht an der Datei.** Deshalb: ein
Zertifikat, lange behalten, jede Fassung damit signieren. Ein Wechsel setzt den
aufgebauten Ruf zurück.

---

## Warum der alte Weg nicht mehr existiert

In `release.yml` stand bis T1-182:

```
signtool sign /f cert.pfx /p $env:CERT_PW ...
```

Dieser Weg ist seit dem **01.06.2023** nicht mehr gangbar. Das CA/Browser-Forum
verlangt seitdem, dass der private Schlüssel eines Code-Signing-Zertifikats auf
Hardware nach FIPS 140-2 Level 2 bzw. Common Criteria EAL4+ erzeugt wird und
diese nie verlässt. Seitdem gibt **keine** Zertifizierungsstelle mehr eine
`.pfx`-Datei heraus.

Das Geheimnis `CERT_PFX_BASE64` hätte also nie befüllt werden können. Der
Schritt wartete auf etwas, das es nicht zu kaufen gibt — und lief wegen eines
zweiten Fehlers ohnehin nie (siehe T1-182 B).

Heute gibt es zwei Formen:

- **USB-Token** — physisch, per Post. Funktioniert nicht in einem
  GitHub-Actions-Läufer, weil dort niemand einen Stick einsteckt.
- **Cloud-HSM** — der Schlüssel liegt beim Dienstleister, der Build schickt den
  Hashwert hin und bekommt die Signatur zurück. Das ist der Weg, der mit CI
  funktioniert, und den `release.yml` jetzt geht.

---

## Die Entscheidung (Owner, 2026-09-15)

**SSL.com, OV Code Signing mit eSigner**, ausgestellt auf:

```
Order Dynamics GmbH
Geschwister-Scholl-Str. 109
20251 Hamburg
HRB 200459
```

Damit ist der Antragsteller eine **juristische Person**, nicht eine natürliche.
Das ist der einfachere Weg: OV-Validierung für eine GmbH ist der Normalfall,
und der Handelsregistereintrag ist genau der Nachweis, den die
Zertifizierungsstelle sehen will.

**OV, nicht EV.** EV kostet deutlich mehr und bringt seit der Änderung von 2024
**keinen Reputationsvorteil** mehr. Der Aufpreis kauft nichts, was hier zählt.

- **OV Code Signing** ab ca. 129 $/Jahr, dazu eSigner für die Signiervorgänge
  (ca. 20 $/Monat je Zugangsdatensatz, mit kostenlosem Testzeitraum).
- Offizielle GitHub-Aktion, in `release.yml` verdrahtet und auf SHA gepinnt.

### Warum nicht die anderen

- **Azure Trusted Signing als Einzelperson** (~10 $/Monat, sonst das
  günstigste). Auf die **USA und Kanada** beschränkt.
- **Azure Trusted Signing als Organisation.** Verlangt eine belegbare
  Steuerhistorie von **drei Jahren oder mehr**. Für eine frisch eingetragene
  GmbH also noch nicht. **Wiedervorlage:** sobald Order Dynamics GmbH drei
  Jahre alt ist, ist das die deutlich günstigere Option — ein Wechsel setzt
  allerdings die aufgebaute Reputation zurück und will gegengerechnet sein.
- **Certum Cloud Code Signing** (~120 €/Jahr, EU). Scheitert an der
  Automatisierung: **keine CI/CD-Unterstützung**, das Signieren verlangt eine
  interaktive Sitzung — bei jedem Release.

### Was die Prüfung verlangen wird

Die Identitätsprüfung dauert erfahrungsgemäß einige Werktage. **Das ist der
lange Teil** — nicht die Einrichtung. Erfahrungsgemäß gefragt:

- Aktueller **Handelsregisterauszug** (HRB 200459, Amtsgericht Hamburg).
- Nachweis der **Geschäftsadresse** — die Anschrift muss zum Registereintrag
  passen.
- Eine **verifizierbare Telefonnummer** des Unternehmens. Das ist der Schritt,
  der am häufigsten hakt: die Nummer muss über ein unabhängiges,
  öffentlich einsehbares Verzeichnis auffindbar sein. Ein Eintrag, den die CA
  selbst nachschlagen kann, spart hier Tage.
- Eine **Firmen-E-Mail-Adresse** auf der eigenen Domain.

### Der Name, den der Kunde sieht

Im Startdialog erscheint künftig `Order Dynamics GmbH` — der geprüfte
juristische Name aus dem Zertifikat, nicht der Produktname und nicht die
Domain.

**Das ist eine offene Kante:** im Impressum auf ordertune.com steht derzeit
`J. Klindworth` als Einzelunternehmen. Ein Kunde, der neben seinem Depot einen
Firmennamen liest, den er auf der Website nirgends findet, hat davon wenig —
die Signatur soll Zutrauen schaffen, und ein nicht zuordenbarer Name tut das
Gegenteil. Sobald die GmbH die betreibende Gesellschaft ist, gehört sie ins
Impressum, und `release.yml` prüft, dass nichts anderes signiert wird.

---

## Einrichtung

Vier Geheimnisse im Repository setzen
(`Settings → Secrets and variables → Actions`):

| Geheimnis | Herkunft |
|---|---|
| `SSLCOM_USERNAME` | SSL.com-Konto |
| `SSLCOM_PASSWORD` | SSL.com-Konto |
| `SSLCOM_CREDENTIAL_ID` | eSigner, je Zertifikat |
| `SSLCOM_TOTP_SECRET` | eSigner, beim Einrichten der Automatisierung erzeugt |

Sobald `SSLCOM_USERNAME` gesetzt ist, signiert `release.yml` bei jedem
`v*`-Tag. Eine eigene Umschaltung gibt es nicht — das Vorhandensein der
Zugangsdaten **ist** die Umschaltung.

### Bis das Zertifikat da ist

Ein Tag-Release ohne Zugangsdaten **schlägt jetzt fehl**. Das ist Absicht: bis
0.23.2 ist stillschweigend unsigniert ausgeliefert worden, und genau diese
Stille war der Fehler.

Wer bewusst unsigniert ausliefern will, setzt die Repository-Variable

```
ALLOW_UNSIGNED_RELEASE = true
```

Dann läuft der Release durch, und die Release-Notiz sagt offen, dass die Datei
unsigniert ist, samt SHA-256-Summe zum Nachprüfen.

---

## Nachprüfen

Nach einem signierten Release, auf einem Windows-Rechner:

```powershell
$sig = Get-AuthenticodeSignature .\ordertune-bridge-ibkr.exe
$sig.Status                          # Valid
$sig.SignerCertificate.Subject       # ... O=Order Dynamics GmbH ...
$sig.TimeStamperCertificate.Subject  # nicht leer
```

`release.yml` prüft **dieselben drei Dinge** selbst und bricht ab, wenn eines
fehlt:

1. **Zustand `Valid`** — die Kette trägt bis zu einer Wurzel, der Windows traut.
2. **Herausgeber `Order Dynamics GmbH`** — nicht kosmetisch. Genau dieser Name
   steht im Startdialog, und an ihm hängt der Reputationsaufbau. Ein
   versehentlich anderes Zertifikat (falsche `credential_id`, zweites
   Zertifikat im Konto, Wechsel beim Verlängern) würde sonst still ausgeliefert
   und der aufgebaute Ruf begänne von vorn. Die Erwartung steht als
   `ERWARTETER_HERAUSGEBER` im Workflow.
3. **Zeitstempel vorhanden** — der Teil, der die Signatur überlebt. Ohne ihn
   wird die Datei ungültig, sobald das Zertifikat abläuft, also mitten im Leben
   einer ausgelieferten Fassung.

Dazu als Gegenprobe `signtool verify /pa /v` — `/pa` ist die Richtlinie, nach
der Windows beim Doppelklick prüft; ohne sie wird gegen eine andere Kette
geprüft und Erfolg gemeldet, wo der Explorer später meckert.

Ohne Windows zur Hand:

```bash
osslsigncode verify ordertune-bridge-ibkr.exe
```

---

## Was den Ruf beschleunigt

- **Immer dasselbe Zertifikat.** Ein Wechsel setzt die Reputation zurück.
- **Jede Fassung signieren**, auch Vorabfassungen. Ungesignierte Dateien
  zahlen nicht auf den Ruf ein.
- **Eine Download-Adresse.** Wechselnde Hosts verteilen den Ruf statt ihn zu
  sammeln.
- Eine als unbedenklich eingestufte Datei lässt sich bei Microsoft zur
  Analyse einreichen
  (<https://www.microsoft.com/en-us/wdsi/filesubmission>). Das hilft
  gegen eine konkrete Fehleinstufung, ersetzt aber keinen Reputationsaufbau.
