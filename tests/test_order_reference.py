"""T1-109 — der sprechende Auftragsvermerk.

Die teure Frage ist nicht, ob das Etikett schoen aussieht, sondern ob die
dispatch_id nach einem Neustart noch gefunden wird. Sie ist das einzige, was
eine Sitzung ueberlebt; verliert die Bridge sie, kommt das Ergebnis eines
Echtauftrags nicht zurueck.
"""

from ordertune_bridge_ibkr.order_reference import (
    ORDER_REF_MAX_LEN,
    build_order_ref,
    dispatch_id_from_order_ref,
    is_ours,
)

UUID = "68b51461-05e6-4c8a-9f21-3d7e5a1b2c04"


# ── Zusammensetzen ──────────────────────────────────────────────────────────


def test_mit_etikett_steht_der_lesbare_teil_vorne():
    # Der ganze Zweck: TWS schneidet rechts ab.
    ref = build_order_ref(UUID, "ALAB-7808-Peak_Reload")
    assert ref == f"ot-ALAB-7808-Peak_Reload-{UUID}"
    assert ref.startswith("ot-ALAB-7808")


def test_ohne_etikett_entsteht_das_alte_format():
    assert build_order_ref(UUID, None) == f"ot-{UUID}"
    assert build_order_ref(UUID, "") == f"ot-{UUID}"
    assert build_order_ref(UUID, "   ") == f"ot-{UUID}"


def test_ein_etikett_aus_lauter_unerlaubten_zeichen_faellt_weg():
    assert build_order_ref(UUID, "!!! ???") == f"ot-{UUID}"


def test_punkt_und_unterstrich_bleiben_erhalten():
    # `BRK.B` und `Peak_Reload` sollen ihre vertraute Schreibweise behalten.
    ref = build_order_ref(UUID, "BRK.B-77-Peak_Reload")
    assert "BRK.B" in ref and "Peak_Reload" in ref


def test_zu_langes_etikett_faellt_weg_statt_die_kennung_zu_beschneiden():
    # Der teure Fall. Lieber ein stummer Vermerk als ein unauffindbarer
    # Auftrag — die dispatch_id wird NIE gekuerzt.
    ref = build_order_ref(UUID, "X" * 200)
    assert ref == f"ot-{UUID}"
    assert dispatch_id_from_order_ref(ref) == UUID


def test_die_obergrenze_wird_eingehalten():
    for etikett in ["ALAB-7808-Peak_Reload", "A-1", "X" * 24, None]:
        assert len(build_order_ref(UUID, etikett)) <= ORDER_REF_MAX_LEN


# ── Zurueckreden ────────────────────────────────────────────────────────────


def test_neues_format_wird_gelesen():
    assert dispatch_id_from_order_ref(f"ot-ALAB-7808-Peak_Reload-{UUID}") == UUID


def test_altes_format_wird_weiterhin_gelesen():
    # Abwaertskompatibilitaet: Auftraege, die eine aeltere Bridge gestellt hat,
    # liegen bei IBKR und muessen nach einem Update wiedergefunden werden.
    assert dispatch_id_from_order_ref(f"ot-{UUID}") == UUID


def test_hin_und_zurueck_fuer_beide_formen():
    for etikett in [None, "ALAB-7808-Peak_Reload", "INTC-7690-Day_Ripper"]:
        assert dispatch_id_from_order_ref(build_order_ref(UUID, etikett)) == UUID


def test_leerraum_um_den_vermerk_stoert_nicht():
    assert dispatch_id_from_order_ref(f"  ot-{UUID}  ") == UUID
    assert dispatch_id_from_order_ref("  ot-abc123  ") == "abc123"


def test_fremde_auftraege_werden_uebergangen():
    for fremd in [None, "", "   ", "manual-123", "IB-4711", "OT-GROSS"]:
        assert dispatch_id_from_order_ref(fremd) is None


def test_praefix_allein_ist_keine_kennung():
    assert dispatch_id_from_order_ref("ot-") is None
    assert dispatch_id_from_order_ref("ot-   ") is None


def test_ein_etikett_ohne_uuid_faellt_auf_die_alte_regel_zurueck():
    # Was nicht wie eine UUID endet, wird wie frueher als Ganzes gelesen.
    assert dispatch_id_from_order_ref("ot-abc123") == "abc123"


def test_eine_uuid_mitten_im_etikett_wird_nicht_verwechselt():
    # Nur das ENDE zaehlt. Sonst zoege ein Etikett, das zufaellig wie eine UUID
    # aussieht, die falsche Kennung.
    andere = "11111111-2222-3333-4444-555555555555"
    assert dispatch_id_from_order_ref(f"ot-{andere}-{UUID}") == UUID


# ── Besitz ──────────────────────────────────────────────────────────────────


def test_besitz_haengt_nur_am_praefix():
    # Diese Frage entscheidet, ob eine Fuellung als eigener Auftrag oder als
    # fremde Ausfuehrung gebucht wird. Sie muss auch dann noch stimmen, wenn
    # sich das Format dahinter aendert — sonst stuende der Bestand doppelt.
    assert is_ours(f"ot-{UUID}")
    assert is_ours(f"ot-ALAB-7808-Peak_Reload-{UUID}")
    assert is_ours("ot-was-auch-immer")
    assert not is_ours("manual-123")
    assert not is_ours(None)
    assert not is_ours("")
