# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from ascendc_pilot.evidence_window import (
    disk_window_proof,
    first_evidence_locator,
    parse_lines_spec,
)


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
    import hashlib

    expect = hashlib.sha256(b"L2\nL3\nL4").hexdigest()
    assert out["evidence_window_sha256"] == expect


def test_disk_window_rejects_traversal(tmp_path: Path) -> None:
    out = disk_window_proof(tmp_path, path="../outside.cpp", lines="1-2")
    assert out["ok"] is False


def test_first_evidence_locator_takes_file_ext_not_last_colon() -> None:
    loc = first_evidence_locator(
        "op_kernel/arch35/flash_attention_score_grad_tiling_data_regbase.h:105 "
        "TILING_FIELD n2; set_n2 at tiling_normal_regbase.cpp:2068"
    )
    assert loc == (
        "op_kernel/arch35/flash_attention_score_grad_tiling_data_regbase.h",
        "105",
    )
    loc = first_evidence_locator("runner.py:50-56 pttype from case.dtype")
    assert loc == ("runner.py", "50-56")
    assert first_evidence_locator("result writeback column") is None


def test_disk_window_proof_colon_suffix_does_not_raise(tmp_path: Path) -> None:
    src = tmp_path / "op_kernel" / "arch35" / "flash_attention_score_grad_tiling_data_regbase.h"
    src.parent.mkdir(parents=True)
    src.write_text("x\n" * 120, encoding="utf-8")
    # Windows NTFS stream syntax / naive rpartition leftover. Must not raise.
    out = disk_window_proof(
        tmp_path,
        path="op_kernel/arch35/flash_attention_score_grad_tiling_data_regbase.h:105",
        lines="105",
    )
    assert out["ok"] is False
    assert out.get("error") in {"bad_path", "missing_file"}
    cr = disk_window_proof(
        tmp_path,
        path="op_kernel/arch35/flash_attention_\r",
        lines="1",
    )
    assert cr["ok"] is False
    ok = disk_window_proof(
        tmp_path,
        path="op_kernel/arch35/flash_attention_score_grad_tiling_data_regbase.h",
        lines="2",
    )
    assert ok["ok"] is True
