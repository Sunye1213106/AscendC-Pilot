"""Isolation + KB fingerprint gates (TG must not write UO_ROOT)."""

from __future__ import annotations

from pathlib import Path

import pytest

from testcase_agent.init_status import InitGateError, mark_init_confirmed, require_init_confirmed
from testcase_agent.isolation import (
    IsolationError,
    assert_tg_write_path,
    compute_kb_fingerprint,
    kb_fingerprint_matches,
    write_kb_fingerprint,
)
from testcase_agent.io import output_root, write_yaml
from testcase_agent.products import dump_init, INIT_SCHEMA, load_init


def test_assert_tg_write_path_blocks_uo_root(tmp_path: Path) -> None:
    uo = tmp_path / ".ascendc-pilot" / "uo" / "ir" / "input_derivable.yaml"
    uo.parent.mkdir(parents=True)
    with pytest.raises(IsolationError, match="UO_ROOT"):
        assert_tg_write_path(uo)


def test_write_yaml_blocks_uo_root(tmp_path: Path) -> None:
    uo = tmp_path / ".ascendc-pilot" / "uo" / "ir" / "x.yaml"
    uo.parent.mkdir(parents=True)
    with pytest.raises(IsolationError):
        write_yaml(uo, {"a": 1})


def test_write_yaml_allows_out_root(tmp_path: Path) -> None:
    out = tmp_path / ".ascendc-pilot" / "tg" / "x.yaml"
    write_yaml(out, {"ok": True})
    assert out.is_file()


def _write_product_uo(path: Path, *, op_name: str = "DemoOp", arch: str = "arch35", stamp: str = "a") -> None:
    from uo_init.ir.codemap import CodeMap
    from uo_init.ir.entity import Entity, EntityKind
    from uo_init.store.writer import write_codemap

    path = Path(path)
    cm = CodeMap(op_name=op_name, architecture=arch)
    cm.add_entity(Entity(id=f"ARCH_{arch}", kind=EntityKind.ARCH, name=arch))
    cm.add_entity(Entity(id=f"STAMP_{stamp}", kind=EntityKind.ARCH, name=stamp))
    write_codemap(cm, path)


def _seed_init(out: Path, project: Path, *, digest: str = "pending") -> None:
    dump_init(
        out,
        {
            "schema": INIT_SCHEMA,
            "kind": "default_input",
            "table_kind": "csv",
            "uo_digest": digest,
            "confirmed": False,
            "project_root": project.as_posix(),
            "op_name": "DemoOp",
        },
    )


def test_fingerprint_stable_then_changes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UO_ARCH", "arch35")
    project = tmp_path / "op"
    product = project / ".ascendc-pilot" / "arch35" / "uo" / "DemoOp.arch35.uo"
    _write_product_uo(product, stamp="h1")
    out = output_root(project, "DemoOp", arch="arch35")
    out.mkdir(parents=True, exist_ok=True)
    fp1 = write_kb_fingerprint(out, product.parent)
    ok, _ = kb_fingerprint_matches(out, product.parent)
    assert ok
    assert fp1["digest"]
    _write_product_uo(product, stamp="h2")
    ok2, detail = kb_fingerprint_matches(out, product.parent)
    assert not ok2
    assert detail["reason"] == "digest_mismatch"


def test_require_init_confirmed_asks_kb_stale_reinit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UO_ARCH", "arch35")
    project = tmp_path / "op"
    product = project / ".ascendc-pilot" / "arch35" / "uo" / "DemoOp.arch35.uo"
    _write_product_uo(product, stamp="r1")
    out = output_root(project, "DemoOp", arch="arch35")
    out.mkdir(parents=True, exist_ok=True)
    _seed_init(out, project, digest="x")
    write_kb_fingerprint(out, product.parent)
    mark_init_confirmed(out, notes="ok", project_root=project)
    require_init_confirmed(project, "DemoOp")
    _write_product_uo(product, stamp="changed")
    with pytest.raises(InitGateError) as exc:
        require_init_confirmed(project, "DemoOp")
    assert exc.value.ask == "kb_stale_reinit"


def test_mark_init_confirmed_writes_fingerprint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UO_ARCH", "arch35")
    project = tmp_path / "op"
    product = project / ".ascendc-pilot" / "arch35" / "uo" / "DemoOp.arch35.uo"
    _write_product_uo(product)
    out = output_root(project, "DemoOp", arch="arch35")
    out.mkdir(parents=True, exist_ok=True)
    _seed_init(out, project)
    doc = mark_init_confirmed(out, notes="test", require_merge=False, project_root=project)
    assert doc["status"] == "confirmed"
    stored = load_init(out)
    assert stored.get("uo_digest") == compute_kb_fingerprint(product.parent)["digest"]
    assert stored.get("confirmed") is True
