from __future__ import annotations

from uo_init.kernel_sync import pair_events


def test_sync_pairing_is_conservative() -> None:
    wait = {"kind": "WaitFlag", "flag": "f", "pipe": "V", "event": 1, "buffer_identity": "ub", "cross_core": False}
    assert pair_events([wait])[0]["status"] == "UNRESOLVED_SYNC_PAIRING"
    producer = {**wait, "kind": "SetFlag"}
    assert pair_events([producer, wait])[0]["status"] == "PAIRED"
    multi = pair_events([producer, producer, wait], prefer_nearest_preceding=False)
    assert multi[0]["status"] == "MULTIPLE_PAIR_CANDIDATES"


def test_sync_pairing_nearest_preceding_is_partial() -> None:
    a = {
        "kind": "SetFlag",
        "flag": "f",
        "pipe": "V",
        "event": 1,
        "buffer_identity": "ub",
        "cross_core": False,
        "function": "Process",
        "line": 10,
        "column": 1,
    }
    b = {**a, "line": 20}
    wait = {**a, "kind": "WaitFlag", "line": 30}
    row = pair_events([a, b, wait])[0]
    assert row["status"] == "PAIRED"
    assert row["producer"]["line"] == 20
    assert row["confidence"] == "partial"
