"""T1-184 — die Karte argumentiert nicht gegen den Knopf darunter.

## Der Befund

Owner-Befund 2026-09-15 an einer Aufnahme des Assistenten nach einem `401`.
Die schwarze Karte sagte:

    Generate a fresh token in Ordertune and download the new bridge.env.

Drei Zentimeter darunter, im selben Bild, stand Schritt 1:

    Get a code here, type it into Ordertune, done.
    Nothing to download, nothing to copy between windows.
    [ Get a pairing code ]

Der Kern ist nicht ein veralteter Text, sondern **welche** Stoerungen diese
Karte zeigen: `RENEWABLE_AUTH_CODES` sind genau die Codes, bei denen T1-181
den Assistenten oeffnet — und alle vier schickten zum Herunterladen einer
Datei. Die Schnittmenge war vollstaendig.

## Warum der Riegel an der Flaeche haengt und nicht am Wort

`missing_fingerprint` nennt einen Download und ist trotzdem richtig: dieser
Code erreicht den Assistenten nie, er landet im Konsolen-Abbruch, und dort ist
die Website die einzig moegliche Antwort.

Eine Zusicherung, die bloss „download" in `failures.py` sucht, schlaegt dort
falsch an. Und ein Riegel, der beim ersten Fehlalarm stoert, wird
abgeschaltet — dann bewacht er gar nichts mehr. Geprueft wird deshalb die
Paarung aus Code UND Flaeche.

## Die drei Flaechen

  * **Konsolen-Abbruch** — kein Knopf, niemand davor. `action`.
  * **Karte im laufenden Cockpit** — kein Kopplungsknopf. `action`.
  * **Assistent** (`setup_mode`) — der Knopf steht darunter. `action_paired`.
"""
from __future__ import annotations

import httpx
import pytest

from ordertune_bridge_ibkr import failures

API = "https://t1.ordertune.com"


def fehler(code: str, status: int = 401) -> httpx.HTTPStatusError:
    """Eine Plattform-Antwort, wie der Handshake sie bekommt.

    Die Form ist `{"error": {"code", "message"}}` — geschachtelt, nicht flach.
    Ein flaches `{"error": code}` faellt lautlos in den Sammelfall
    `handshake_failed`, und dann prueft der Test irgendetwas, nur nicht die
    Stoerung, die im Namen steht.
    """
    request = httpx.Request("POST", f"{API}/api/bridge/v1/handshake")
    response = httpx.Response(
        status,
        json={"error": {"code": code, "message": "-"}},
        request=request,
    )
    return httpx.HTTPStatusError("nope", request=request, response=response)


def test_das_fixture_trifft_wirklich_den_gemeinten_code() -> None:
    """Zuerst das Messwerkzeug pruefen.

    Der erste Entwurf dieser Datei baute `{"error": code}` und landete fuer
    jeden Code im Sammelfall — vier Zusicherungen, die nichts pruefen und
    trotzdem etwas behaupten.
    """
    f = failures.classify_handshake_error(fehler("connection_revoked"), API)

    assert f.code == "connection_revoked", (
        f"das Fixture erzeugt {f.code!r} statt der gemeinten Stoerung — die "
        "Tests darunter messen dann den Sammelfall"
    )


@pytest.mark.parametrize("code", sorted(failures.RENEWABLE_AUTH_CODES))
def test_der_assistent_raet_zu_keinem_download(code: str) -> None:
    """Der eigentliche Befund, je Code festgenagelt.

    Nicht „irgendwo in failures.py steht kein download", sondern: der Text,
    den DIESE Flaeche zeigt, raet nicht zu etwas, das der Knopf darunter
    ausdruecklich ueberfluessig macht.
    """
    f = failures.classify_handshake_error(fehler(code), API)
    text = " ".join(f.action_paired).lower()

    assert f.action_paired, (
        f"{code} oeffnet den Assistenten, hat aber keinen Text dafuer — dann "
        "faellt die Karte auf den ausfuehrlichen Text zurueck, und der nennt "
        "einen Download"
    )
    assert "download" not in text, (
        f"{code}: die Karte im Assistenten raet zum Herunterladen, waehrend "
        "darunter 'Nothing to download' samt Kopplungsknopf steht"
    )
    assert "bridge.env" not in text, f"{code}: die Karte nennt wieder die Datei"


@pytest.mark.parametrize("code", sorted(failures.RENEWABLE_AUTH_CODES))
def test_der_assistent_zeigt_nicht_die_website(code: str) -> None:
    """Die Adresse ist der Weg fuer jemanden OHNE Knopf.

    Im Assistenten waere sie eine zweite, umstaendlichere Anleitung neben der,
    die als Knopf danebensteht.
    """
    f = failures.classify_handshake_error(fehler(code), API)

    assert not any("http" in zeile.lower() for zeile in f.action_paired), (
        f"{code}: die Karte schickt wieder auf die Website, obwohl der Knopf "
        "darunter dasselbe erledigt"
    )


@pytest.mark.parametrize("code", sorted(failures.RENEWABLE_AUTH_CODES))
def test_die_konsole_behaelt_ihren_vollstaendigen_weg(code: str) -> None:
    """Die Gegenprobe — und die wichtigere Haelfte.

    Eine Korrektur, die den ausfuehrlichen Text ueberall eindampft, macht den
    Assistenten richtig und laesst jemanden ohne Knopf ohne Antwort zurueck.
    """
    f = failures.classify_handshake_error(fehler(code), API)
    text = " ".join(f.action)

    assert API in text, (
        f"{code}: der Konsolen-Abbruch nennt die Adresse nicht mehr — dort "
        "gibt es keinen Knopf, auf den er sich zurueckziehen koennte"
    )
    assert len(f.action) > len(f.action_paired), (
        f"{code}: der Konsolentext ist nicht laenger als der Kartentext — "
        "vermutlich wurde die falsche Flaeche eingedampft"
    )


def test_stoerungen_ausserhalb_des_assistenten_bleiben_woertlich() -> None:
    """`missing_fingerprint` darf weiter zum Download raten.

    Das ist der Fall, an dem sich ein Riegel am Wort selbst entlarvt: der Text
    nennt einen Download und ist richtig, weil diese Stoerung den Assistenten
    nie erreicht.
    """
    unberuehrt = {
        "ip_mismatch", "fingerprint_mismatch", "missing_fingerprint", "rate_limited",
    }
    assert not (unberuehrt & failures.RENEWABLE_AUTH_CODES), (
        "einer dieser Codes oeffnet jetzt den Assistenten — dann braucht er "
        "einen eigenen Kartentext, sonst kehrt der Befund zurueck"
    )

    f = failures.classify_handshake_error(fehler("missing_fingerprint", 409), API)

    assert not f.action_paired, (
        "missing_fingerprint hat einen Kartentext bekommen, erreicht den "
        "Assistenten aber nicht — toter Text, der beim Lesen in die Irre fuehrt"
    )
    assert any("download" in z.lower() for z in f.action), (
        "der Konsolentext wurde mit eingedampft, obwohl diese Stoerung gar "
        "nicht im Assistenten landet"
    )


def test_ohne_kartentext_faellt_die_darstellung_zurueck() -> None:
    """Der Rueckfall muss den ausfuehrlichen Text liefern, nicht nichts.

    `main.py` waehlt `action_paired or action`. Ein leeres Feld darf keine
    leere Karte ergeben — eine Stoerung ohne Handlungsangabe ist schlimmer als
    eine mit der umstaendlichen.
    """
    f = failures.classify_handshake_error(fehler("rate_limited", 429), API)

    gezeigt = f.action_paired or f.action

    assert gezeigt is f.action
    assert gezeigt, "die Karte bliebe leer"
