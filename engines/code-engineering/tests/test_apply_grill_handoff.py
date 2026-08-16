# -*- coding: utf-8 -*-
"""CE grill promote, apply gate, and session handoff."""

from __future__ import annotations

from pathlib import Path

import yaml

from code_engineering.apply import apply_gate, patch_guard
from code_engineering.handoff import write_session_handoff
from code_engineering.intent import promote_intent_grill


def test_promote_intent_grill_merges_staged_fields(tmp_path: Path) -> None:
    arch = "arch35"
    staging = tmp_path / ".ascendc-pilot" / arch / "runs" / "r1" / "actions" / "intent_grill"
    staging.mkdir(parents=True)
    (staging / "staging.yaml").write_text(
        yaml.safe_dump(
            {
                "in_scope": ["fix sync"],
                "out_of_scope": ["perf"],
                "acceptance": ["UT"],
                "open_questions": [],
                "side": "kernel",
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    intent = tmp_path / ".ascendc-pilot" / arch / "ce" / "intent" / "intent.yaml"
    intent.parent.mkdir(parents=True)
    intent.write_text(
        yaml.safe_dump({"schema": "ce-intent/v1", "intent": "fix sync"}, allow_unicode=True),
        encoding="utf-8",
    )
    out = promote_intent_grill(tmp_path, architecture=arch, run_id="r1")
    assert out.get("ok") is True, out
    doc = yaml.safe_load(intent.read_text(encoding="utf-8"))
    assert doc.get("intent") == "fix sync"
    assert doc.get("in_scope") == ["fix sync"]
    assert doc.get("acceptance") == ["UT"]
    assert doc.get("open_questions") == []


def test_apply_gate_requires_confirm_and_anchors(tmp_path: Path) -> None:
    arch = "arch35"
    ce = tmp_path / ".ascendc-pilot" / arch / "ce"
    (ce / "intent").mkdir(parents=True)
    (ce / "intent" / "confirmation.yaml").write_text(
        "schema: ce-intent-confirmation/v1\nstatus: confirmed\n", encoding="utf-8"
    )
    (ce / "intent" / "anchors.yaml").write_text("anchors: []\n", encoding="utf-8")
    denied = apply_gate(tmp_path, architecture=arch)
    assert denied.get("ok") is False
    (ce / "intent" / "anchors.yaml").write_text(
        "anchors:\n- file: op_kernel/foo.cpp\n", encoding="utf-8"
    )
    allowed = apply_gate(tmp_path, architecture=arch)
    assert allowed.get("ok") is True, allowed


def test_patch_guard_rejects_files_outside_anchors(tmp_path: Path) -> None:
    arch = "arch35"
    ce = tmp_path / ".ascendc-pilot" / arch / "ce"
    (ce / "intent").mkdir(parents=True)
    (ce / "apply").mkdir(parents=True)
    (ce / "intent" / "anchors.yaml").write_text(
        "anchors:\n- file: op_kernel/foo.cpp\n", encoding="utf-8"
    )
    (ce / "apply" / "change_capture.yaml").write_text(
        "diff_spans:\n  op_kernel/foo.cpp: [[1, 2]]\n  op_host/bar.cpp: [[3, 4]]\n",
        encoding="utf-8",
    )
    result = patch_guard(tmp_path, architecture=arch)
    assert result.get("ok") is False
    assert "op_host/bar.cpp" in (result.get("extra_files") or [])


def test_write_session_handoff_is_pointer_only(tmp_path: Path) -> None:
    out = write_session_handoff(
        tmp_path,
        architecture="arch35",
        next_slash="/ce-apply",
        artifact_paths=["ce/intent/intent.yaml"],
        open_items=[],
    )
    assert out.get("ok") is True, out
    text = Path(out["artifact"]).read_text(encoding="utf-8")
    assert "/ce-apply" in text
    assert "ce/intent/intent.yaml" in text
    assert "grill-with-docs" not in text
