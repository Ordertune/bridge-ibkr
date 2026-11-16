"""T1-414 — ein Handelskonto je Verbindung.

Sieht der IBKR-Login mehrere Konten, legt die Plattform fest, in welchem
gehandelt wird, und meldet es in der Heartbeat-Antwort (`tradingAccountId`).
Diese Datei enthaelt die beiden reinen Regeln dazu; sie fasst weder IBKR noch
das Netz an und ist ohne TWS pruefbar.

Ausloeser (2026-11-16): ein Login mit sechs Konten. Das Kapital kam aus dem
zuletzt gelesenen Konto (1 Mio. EUR), die Order landete ohne `order.account`
im TWS-Standardkonto (rund 50.000 EUR). Orders wurden rund 20-fach zu gross.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Grund, mit dem ein Auftrag abgewiesen wird, dessen Zielkonto nicht das
#: aktuelle Handelskonto ist (AC-19i). Die Plattform kennt ihn als `other`.
ACCOUNT_MISMATCH = "account_mismatch"


@dataclass(frozen=True)
class HeartbeatAntwort:
    """Was die Plattform auf den Herzschlag antwortet.

    `konto_gemeldet` unterscheidet „die Plattform sagt nichts" (aeltere
    Fassung, Feld fehlt) von „die Plattform sagt: kein Konto festgelegt"
    (`null`). Nur im zweiten Fall wird eine fruehere Vorgabe geloescht.
    """

    konto_gemeldet: bool
    konto: str | None


def antwort_aus_json(data: object) -> HeartbeatAntwort:
    if not isinstance(data, dict) or "tradingAccountId" not in data:
        return HeartbeatAntwort(konto_gemeldet=False, konto=None)
    wert = data.get("tradingAccountId")
    konto = wert.strip() if isinstance(wert, str) and wert.strip() else None
    return HeartbeatAntwort(konto_gemeldet=True, konto=konto)


def waehle_handelskonto(konten: list[str], vorgabe: str | None) -> str | None:
    """Das Konto, in dem gehandelt und aus dem gelesen wird.

    1. Die Vorgabe der Plattform, wenn sie im Login steht.
    2. Sonst wie bisher: genau ein Konto im Login ist dieses.
    3. Sonst keins. Bei mehreren Konten wird nie geraten (T1-306).
    """
    if vorgabe and vorgabe in konten:
        return vorgabe
    return konten[0] if len(konten) == 1 else None


def pruefe_zielkonto(ziel: str | None, konto: str | None) -> str | None:
    """`None`, wenn der Auftrag hinaus darf, sonst der Ablehnungstext.

    Ein Auftrag ohne Zielkonto stammt von einer Plattform vor T1-414 und laeuft
    wie bisher. Traegt er eins, muss es das aktuelle Handelskonto sein: sonst
    wurde seine Menge gegen das Kapital eines anderen Kontos gerechnet.
    """
    if ziel is None:
        return None
    if konto is None:
        return (
            f"Order was sized for account {maskiere(ziel)}, but this bridge has "
            "no trading account. Not sent."
        )
    if ziel != konto:
        return (
            f"Order was sized for account {maskiere(ziel)}, but the bridge now "
            f"trades in {maskiere(konto)}. Not sent."
        )
    return None


def maskiere(konto: str) -> str:
    """Praefix, Auslassung, letzte vier Zeichen — wie die Plattform."""
    i = 0
    while i < len(konto) and konto[i].isalpha():
        i += 1
    praefix, rest = konto[:i], konto[i:]
    return f"{praefix}…{rest[-4:]}" if len(rest) > 4 else f"{praefix}…"
