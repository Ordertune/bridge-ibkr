import re

from ordertune_bridge_ibkr.fingerprint import compute_fingerprint


def test_fingerprint_is_stable():
    a = compute_fingerprint()
    b = compute_fingerprint()
    assert a == b


def test_fingerprint_is_hex_sha256():
    f = compute_fingerprint()
    assert re.match(r"^[0-9a-f]{64}$", f)
