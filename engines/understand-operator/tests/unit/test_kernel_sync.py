from __future__ import annotations

from uo_init.kernel_sync import pair_events


def test_sync_pairing_is_conservative() -> None:
    wait = {"kind": "WaitFlag", "flag": "f", "pipe": "V", "event": 1, "buffer_identity": "ub", "cross_core": False}
    assert pair_events([wait])[0]["status"] == "UNRESOLVED_SYNC_PAIRING"
    producer = {**wait, "kind": "SetFlag"}
    assert pair_events([producer, wait])[0]["status"] == "PAIRED"
    assert pair_events([producer, producer, wait])[0]["status"] == "MULTIPLE_PAIR_CANDIDATES"
