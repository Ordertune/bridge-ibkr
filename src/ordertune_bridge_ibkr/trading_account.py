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

from .masking import mask_account

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


#: Ergebnis von `pruefe_zielkonto`: der Auftrag bleibt liegen (Konto noch
#: unbekannt, z. B. direkt nach dem Start vor dem ersten Herzschlag).
ZIEL_WARTEN = "warten"
#: Ergebnis von `pruefe_zielkonto`: der Auftrag wurde fuer ein anderes Konto
#: gerechnet und wird abgewiesen.
ZIEL_ABWEISEN = "abweisen"


def pruefe_zielkonto(ziel: str | None, konto: str | None) -> tuple[str | None, str]:
    """`(None, "")`, wenn der Auftrag hinaus darf; sonst Urteil und Text.

    - Ohne Zielkonto stammt der Auftrag von einer Plattform vor T1-414 und
      laeuft wie bisher.
    - Ist das Handelskonto (noch) unbekannt, bleibt er liegen: nach einem
      Neustart kennt die Bridge ihr Konto erst mit dem ersten Herzschlag, und
      eine endgueltige Ablehnung wuerde eine gueltige Freigabe vernichten.
      Laeuft er dabei ab, verfaellt er wie jeder andere.
    - Steht ein anderes Konto fest, wurde seine Menge gegen fremdes Kapital
      gerechnet: abweisen.
    """
    if ziel is None or ziel == konto:
        return None, ""
    if konto is None:
        return ZIEL_WARTEN, (
            f"Order was sized for account {mask_account(ziel)}; the trading "
            "account of this bridge is not known yet. Holding it."
        )
    return ZIEL_ABWEISEN, (
        f"Order was sized for account {mask_account(ziel)}, but the bridge now "
        f"trades in {mask_account(konto)}. Not sent."
    )
