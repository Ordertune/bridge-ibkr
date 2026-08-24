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
    assert dispatch_id_from_order_ref("  ot-e99a18c4-28cb-48d5-8260-853678922e03  ") == "e99a18c4-28cb-48d5-8260-853678922e03"


def test_fremde_auftraege_werden_uebergangen():
    for fremd in [None, "", "   ", "manual-123", "IB-4711", "OT-GROSS"]:
        assert dispatch_id_from_order_ref(fremd) is None


def test_praefix_allein_ist_keine_kennung():
    assert dispatch_id_from_order_ref("ot-") is None
    assert dispatch_id_from_order_ref("ot-   ") is None


def test_ein_etikett_ohne_uuid_faellt_auf_die_alte_regel_zurueck():
    # Was nicht wie eine UUID endet, wird wie frueher als Ganzes gelesen.
    assert dispatch_id_from_order_ref("ot-e99a18c4-28cb-48d5-8260-853678922e03") == "e99a18c4-28cb-48d5-8260-853678922e03"


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
    assert is_ours("ot-a2b6fc51-c807-4075-8df7-5ee6f067c3e4")
    assert not is_ours("manual-123")
    assert not is_ours(None)
    assert not is_ours("")


# ── T1-114: der Rueckbericht ────────────────────────────────────────────────


class _Order:
    def __init__(self, **kw):
        self.orderId = kw.get("orderId", 0)
        self.orderRef = kw.get("orderRef", "")
        self.ocaGroup = kw.get("ocaGroup", "")
        self.ocaType = kw.get("ocaType", 0)
        self.goodAfterTime = kw.get("goodAfterTime", "")
        self.goodTillDate = kw.get("goodTillDate", "")
        self.lmtPrice = kw.get("lmtPrice", 0.0)
        self.orderType = kw.get("orderType", "")
        self.tif = kw.get("tif", "")
        self.totalQuantity = kw.get("totalQuantity", 0.0)


class _Status:
    def __init__(self, status="Submitted"):
        self.status = status


class _Trade:
    def __init__(self, order, status="Submitted"):
        self.order = order
        self.orderStatus = _Status(status)


def _unser(**kw):
    kw.setdefault("orderRef", f"ot-ALAB-7809-Peak_Reload-{UUID}")
    return _Trade(_Order(**kw))


def test_nur_eigene_auftraege_gehen_mit():
    from ordertune_bridge_ibkr.order_reference import wire_open_orders

    fremd = _Trade(_Order(orderRef="manual-123", orderId=99))
    out = wire_open_orders([_unser(orderId=865), fremd])
    assert len(out) == 1
    assert out[0]["brokerOrderId"] == "865"
    assert out[0]["dispatchId"] == UUID


def test_der_fall_vom_2026_08_21():
    """Die weggefallene Zeitbedingung wird als solche berichtet."""
    from ordertune_bridge_ibkr.order_reference import wire_open_orders

    out = wire_open_orders(
        [
            _unser(
                orderId=865,
                ocaGroup="OCA_ALAB_2026-08-21_Peak_Reload",
                ocaType=3,
                goodAfterTime="",  # genau das, was IBKR am Montag fuehrte
                lmtPrice=290.52,
                orderType="LMT",
                tif="DAY",
                totalQuantity=1.0,
            )
        ]
    )
    assert out[0]["ocaGroup"] == "OCA_ALAB_2026-08-21_Peak_Reload"
    assert out[0]["ocaType"] == 3
    # Der Befund: der Leerstring wird NICHT als Wert gemeldet.
    assert out[0]["goodAfterTime"] is None
    assert out[0]["lmtPrice"] == 290.52


def test_ein_in_tws_geaendertes_limit_wird_sichtbar():
    from ordertune_bridge_ibkr.order_reference import wire_open_orders

    out = wire_open_orders([_unser(lmtPrice=90.67)])
    assert out[0]["lmtPrice"] == 90.67


def test_ohne_aufloesbaren_vermerk_faellt_der_auftrag_weg():
    """Ohne Zuordnung ist die Zeile eine Behauptung ohne Adresse."""
    from ordertune_bridge_ibkr.order_reference import wire_open_orders

    assert wire_open_orders([_Trade(_Order(orderRef=""))]) == []
    assert wire_open_orders([_Trade(_Order(orderRef="ot-"))]) == []


def test_kein_limit_bleibt_null_statt_null_komma_null():
    """IBKR schreibt 0.0 fuer „kein Limit" — das ist kein Preis."""
    from ordertune_bridge_ibkr.order_reference import wire_open_orders

    out = wire_open_orders([_unser(orderType="MOC", lmtPrice=0.0)])
    assert out[0]["lmtPrice"] is None
    assert out[0]["orderType"] == "MOC"


def test_die_liste_ist_gedeckelt():
    from ordertune_bridge_ibkr.order_reference import (
        MAX_OPEN_ORDERS_REPORTED,
        wire_open_orders,
    )

    viele = [_unser(orderId=i) for i in range(MAX_OPEN_ORDERS_REPORTED + 20)]
    assert len(wire_open_orders(viele)) == MAX_OPEN_ORDERS_REPORTED


def test_leere_und_kaputte_eingaben():
    from ordertune_bridge_ibkr.order_reference import wire_open_orders

    assert wire_open_orders([]) == []
    assert wire_open_orders(None) == []
    assert wire_open_orders([object()]) == []


# ── T1-115: der Besitzanspruch braucht einen Nachweis ───────────────────────


def test_ein_von_hand_getippter_vermerk_gehoert_uns_NICHT():
    """Der Fall vom 2026-08-21, den der Owner versehentlich vorgefuehrt hat.

    Er trug `ot-INTC-7690-Day_Ripper` von Hand in TWS ein. Unter der alten
    Regel galt das als „unserer" — die Fuellung wurde weder als fremde
    Ausfuehrung gemeldet noch ueber den eigenen Weg gefunden. Sie fiel durch
    beide Wege.
    """
    assert not is_ours("ot-INTC-7690-Day_Ripper")
    assert not is_ours("ot-INTC-7835-Day_Ripper")
    assert not is_ours("ot-abc123")
    assert not is_ours("ot-")


def test_echte_vermerke_gehoeren_weiterhin_uns():
    assert is_ours(f"ot-{UUID}")
    assert is_ours(f"ot-ALAB-7809-Peak_Reload-{UUID}")
    assert is_ours(f"  ot-{UUID}  ")


def test_fremde_bleiben_fremd():
    for fremd in [None, "", "   ", "manual_INTC-7690", "IB-4711", "OT-GROSS"]:
        assert not is_ours(fremd)


def test_der_rueckbericht_folgt_derselben_regel():
    """Was nicht uns gehoert, gehoert auch nicht in den Bericht."""
    from ordertune_bridge_ibkr.order_reference import wire_open_orders

    getippt = _Trade(_Order(orderRef="ot-INTC-7690-Day_Ripper", orderId=1))
    assert wire_open_orders([getippt]) == []
