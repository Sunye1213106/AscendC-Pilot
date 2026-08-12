# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from ascendc_pilot.evidence_window import disk_window_proof, parse_lines_spec


def test_parse_lines_spec() -> None:
    assert parse_lines_spec("10-20") == (10, 20)
    assert parse_lines_spec("7") == (7, 7)


def test_disk_window_proof_sha(tmp_path: Path) -> None:
    src = tmp_path / "op_host" / "arch35" / "demo.cpp"
    src.parent.mkdir(parents=True)
    src.write_text("L1\nL2\nL3\nL4\nL5\n", encoding="utf-8")
    out = disk_window_proof(tmp_path, path="op_host/arch35/demo.cpp", lines="2-4")
    assert out["ok"] is True
    assert out["evidence_snippet"] == "L2\nL3\nL4"
    assert len(out["evidence_window_sha256"]) == 64
    # Stable hash for the joined window.
    import hashlib

    expect = hashlib.sha256(b"L2\nL3\nL4").hexdigest()
    assert out["evidence_window_sha256"] == expect


def test_disk_window_rejects_traversal(tmp_path: Path) -> None:
    out = disk_window_proof(tmp_path, path="../outside.cpp", lines="1-2")
    assert out["ok"] is False
