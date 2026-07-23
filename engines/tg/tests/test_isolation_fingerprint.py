"""Isolation + KB fingerprint gates (TG must not write UO_ROOT)."""

from __future__ import annotations

from pathlib import Path

import pytest

from testcase_agent.init_status import InitGateError, mark_init_confirmed, require_init_confirmed, write_init_status
from testcase_agent.isolation import (
    IsolationError,
    assert_tg_write_path,
    compute_kb_fingerprint,
    kb_fingerprint_matches,
    write_kb_fingerprint,
)
from testcase_agent.io import output_root, write_yaml


def test_assert_tg_write_path_blocks_uo_root(tmp_path: Path) -> None:
    uo = tmp_path / ".ascendc-agent" / "uo" / "ir" / "input_derivable.yaml"
    uo.parent.mkdir(parents=True)
    with pytest.raises(IsolationError, match="UO_ROOT"):
        assert_tg_write_path(uo)


def test_write_yaml_blocks_uo_root(tmp_path: Path) -> None:
    uo = tmp_path / ".ascendc-agent" / "uo" / "ir" / "x.yaml"
    uo.parent.mkdir(parents=True)
    with pytest.raises(IsolationError):
        write_yaml(uo, {"a": 1})


def test_write_yaml_allows_out_root(tmp_path: Path) -> None:
    out = tmp_path / ".ascendc-agent" / "tg" / "realization" / "x.yaml"
    write_yaml(out, {"ok": True})
    assert out.is_file()


def _seed_uo_kb(uo: Path, *, revision: str = "rev1", extra_hash: str = "abc") -> None:
    uo.mkdir(parents=True, exist_ok=True)
    (uo / "checks").mkdir(parents=True, exist_ok=True)
    (uo / "indexes").mkdir(parents=True, exist_ok=True)
    write_yaml = __import__("testcase_agent.io", fromlist=["write_yaml"]).write_yaml
    # write_yaml refuses .understand-operator — seed with raw write_text
    (uo / "manifest.yaml").write_text(f"source:\n  revision: {revision}\n", encoding="utf-8")
    (uo / "checks" / "artifact_hashes.yaml").write_text(
        f"hashes:\n  tiling/key_space.yaml: {extra_hash}\n",
        encoding="utf-8",
    )
    (uo / "checks" / "integrity.yaml").write_text("status: pass\n", encoding="utf-8")
    (uo / "checks" / "confidence_gate.yaml").write_text("status: pass\n", encoding="utf-8")
    (uo / "indexes" / "kb_graph.sqlite").write_bytes(b"sqlite-fake-" + revision.encode())


def test_fingerprint_stable_then_changes(tmp_path: Path) -> None:
    project = tmp_path / "op"
    project.mkdir()
    uo = project / ".ascendc-agent" / "uo"
    _seed_uo_kb(uo, revision="r1", extra_hash="h1")
    out = output_root(project, "DemoOp")
    (out / "init").mkdir(parents=True)
    fp1 = write_kb_fingerprint(out, uo)
    ok, _ = kb_fingerprint_matches(out, uo)
    assert ok
    assert fp1["digest"]
    _seed_uo_kb(uo, revision="r2", extra_hash="h2")
    ok2, detail = kb_fingerprint_matches(out, uo)
    assert not ok2
    assert detail["reason"] == "digest_mismatch"


def test_require_init_confirmed_asks_kb_stale_reinit(tmp_path: Path) -> None:
    project = tmp_path / "op"
    project.mkdir()
    uo = project / ".ascendc-agent" / "uo"
    _seed_uo_kb(uo, revision="r1")
    out = output_root(project, "DemoOp")
    (out / "init").mkdir(parents=True)
    write_init_status(
        out,
        {
            "version": 1,
            "op_name": "DemoOp",
            "status": "confirmed",
            "project_root": project.as_posix(),
            "understand_root": uo.as_posix(),
        },
    )
    write_kb_fingerprint(out, uo)
    require_init_confirmed(project, "DemoOp")  # fresh — ok
    _seed_uo_kb(uo, revision="r9", extra_hash="changed")
    with pytest.raises(InitGateError) as exc:
        require_init_confirmed(project, "DemoOp")
    assert exc.value.ask == "kb_stale_reinit"


def test_mark_init_confirmed_writes_fingerprint(tmp_path: Path) -> None:
    project = tmp_path / "op"
    project.mkdir()
    uo = project / ".ascendc-agent" / "uo"
    _seed_uo_kb(uo)
    out = output_root(project, "DemoOp")
    (out / "init").mkdir(parents=True)
    write_init_status(
        out,
        {
            "version": 1,
            "op_name": "DemoOp",
            "status": "pending_confirm",
            "project_root": project.as_posix(),
            "understand_root": uo.as_posix(),
        },
    )
    doc = mark_init_confirmed(out, notes="test", require_merge=False)
    assert doc["status"] == "confirmed"
    assert (out / "init" / "kb_fingerprint.yaml").is_file()
    assert doc.get("kb_fingerprint_digest") == compute_kb_fingerprint(uo)["digest"]
