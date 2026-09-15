"""T1-182 B — die Signierung bleibt verdrahtet.

## Was hier bewacht wird

Der Signierschritt in `release.yml` ist **nie gelaufen**, kein einziges Mal:

    - name: Sign EXE (if cert available)
      if: env.CERT_PFX_BASE64 != ''      # <- env des EIGENEN Schrittes
      env:
        CERT_PFX_BASE64: ${{ secrets.CERT_PFX_BASE64 }}

Ein `if:` sieht die `env:` seines eigenen Schrittes nicht — nur die von Job und
Workflow. Die Bedingung verglich immer Leer gegen Leer. Gemerkt hat es niemand,
weil ein uebersprungener Schritt grau ist und nicht rot: der Release war gruen.

Das ist nicht durch Ausfuehren pruefbar — der Workflow laeuft auf GitHub, nicht
hier. Geprueft wird deshalb die Datei, so wie `test_build_targets_the_launcher`
`build.py` prueft. Billig zuzusichern, teuer im Feld zu entdecken.

Ohne `yaml`: PyYAML steht weder in `requirements.txt` noch in den
Laufzeit-Abhaengigkeiten, und ein `importorskip` waere hier genau der stille
Rueckfall, den dieser Vorgang abschafft.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"

# Der Name, auf den das Zertifikat lautet — Order Dynamics GmbH,
# Geschwister-Scholl-Str. 109, 20251 Hamburg, HRB 200459.
HERAUSGEBER = "Order Dynamics GmbH"


def zeilen() -> list[str]:
    return WORKFLOW.read_text(encoding="utf-8").splitlines()


def wirksame_zeilen() -> list[str]:
    """Nur was der Runner ausfuehrt — ohne Kommentare.

    Die Kommentare in `release.yml` nennen den alten `CERT_PFX_BASE64`-Weg
    ausdruecklich, weil die Begruendung sonst verloren geht. Eine Zusicherung,
    die auf den blossen Wortlaut anschlaegt, wuerde entweder falsch alarmieren
    oder — schlimmer — dazu fuehren, dass jemand die Erklaerung loescht, um
    sie gruen zu bekommen.
    """
    return [z for z in zeilen() if not z.lstrip().startswith("#")]


def zeile_von(nadel: str) -> int:
    for i, z in enumerate(zeilen()):
        if nadel in z:
            return i
    raise AssertionError(f"{nadel!r} steht nicht in release.yml")


def test_der_unmoegliche_weg_ist_weg() -> None:
    """Ein `.pfx`-Zertifikat gibt es seit dem 01.06.2023 nicht mehr zu kaufen.

    Das CA/Browser-Forum verlangt den privaten Schluessel seitdem auf Hardware
    (FIPS 140-2 Level 2 / EAL4+). Ein Geheimnis `CERT_PFX_BASE64` haette nie
    befuellt werden koennen — der Schritt wartete auf etwas, das es nicht gibt.
    """
    wirksam = "\n".join(wirksame_zeilen())

    assert "CERT_PFX_BASE64" not in wirksam, (
        "release.yml wartet wieder auf eine .pfx-Datei. Die gibt es seit "
        "2023 nicht mehr; der Schritt koennte nie laufen."
    )
    assert "signtool sign /f" not in wirksam, (
        "signiert wieder aus einer Schluesseldatei statt ueber das Cloud-HSM"
    )


def test_der_riegel_steht_auf_job_ebene() -> None:
    """Der eigentliche Fehler: ein `if:` liest die eigene `env:` nicht.

    Steht die Ableitung unterhalb von `steps:`, ist sie an einem Schritt
    haengen geblieben und die Bedingung ist wieder immer falsch.
    """
    env_zeile = zeile_von("SIGNIERUNG_KONFIGURIERT:")
    steps_zeile = zeile_von("\n    steps:".strip())

    assert env_zeile < steps_zeile, (
        "SIGNIERUNG_KONFIGURIERT steht unterhalb von `steps:` — damit haengt "
        "es an einem Schritt, und ein `if:` kann es nicht lesen. Genau so ist "
        "der Signierschritt bis 0.23.2 nie gelaufen."
    )


def test_der_erwartete_herausgeber_ist_festgenagelt() -> None:
    """Auf WELCHEN Namen signiert wurde, ist nicht kosmetisch.

    Der Name steht im Startdialog, und an ihm haengt der Reputationsaufbau.
    Ein anderes Zertifikat — falsche `credential_id`, zweites Zertifikat im
    Konto, Wechsel beim Verlaengern — wuerde sonst still ausgeliefert, und der
    aufgebaute Ruf begaenne bei null.
    """
    inhalt = WORKFLOW.read_text(encoding="utf-8")

    assert f'ERWARTETER_HERAUSGEBER: "{HERAUSGEBER}"' in inhalt, (
        f"Der erwartete Herausgeber ist nicht mehr {HERAUSGEBER!r}. Ist das "
        "Absicht, gehoert der Reputationsverlust mitbedacht — er haengt am "
        "Zertifikat, nicht an der Datei."
    )
    assert zeile_von("ERWARTETER_HERAUSGEBER:") < zeile_von("\n    steps:".strip())

    assert "SignerCertificate.Subject" in inhalt, (
        "Der Herausgeber wird nicht mehr gegen die gebaute Datei geprueft"
    )


def test_die_signatur_wird_belegt_und_nicht_geglaubt() -> None:
    """Ein gruener Signierschritt ist kein Beleg fuer eine gueltige Signatur.

    Dieselbe Lehre wie beim Symbol: `--icon` mitzugeben hiess nicht, dass es
    ankam. Geprueft werden drei Dinge an der ausgelieferten Datei.
    """
    inhalt = WORKFLOW.read_text(encoding="utf-8")

    assert "Get-AuthenticodeSignature" in inhalt
    assert "TimeStamperCertificate" in inhalt, (
        "Ohne Zeitstempel wird die Datei ungueltig, sobald das Zertifikat "
        "ablaeuft — mitten im Leben einer ausgelieferten Fassung"
    )
    assert "verify /pa" in inhalt, (
        "/pa ist die Richtlinie, nach der Windows beim Doppelklick prueft"
    )


def test_die_signieraktion_ist_auf_einen_sha_gepinnt() -> None:
    """Ein Tag laesst sich verschieben — diese Aktion sieht unsere Signierrechte.

    Die Anleitung des Anbieters nennt `@develop`. Das ist ein bewegliches
    Ziel mit Zugriff auf `SSLCOM_*`.
    """
    inhalt = WORKFLOW.read_text(encoding="utf-8")
    treffer = re.search(r"SSLcom/esigner-codesign@(\S+)", inhalt)

    assert treffer, "die Signieraktion steht nicht mehr in release.yml"
    ref = treffer.group(1)
    assert re.fullmatch(r"[0-9a-f]{40}", ref), (
        f"Signieraktion haengt an {ref!r} statt an einem SHA. Ein Tag oder "
        "Branch laesst sich verschieben."
    )


def test_ein_unsignierter_release_ist_eine_entscheidung() -> None:
    """Bis 0.23.2 ist stillschweigend unsigniert ausgeliefert worden.

    Genau diese Stille war der Fehler — nicht die fehlende Signatur.
    """
    inhalt = WORKFLOW.read_text(encoding="utf-8")

    assert "ALLOW_UNSIGNED_RELEASE" in inhalt, (
        "der bewusste Ausweg fehlt — dann ist der Riegel entweder weg oder "
        "er stranded jeden Release ohne Zertifikat"
    )
    assert "UNSIGNIERT_ERLAUBT" in inhalt
