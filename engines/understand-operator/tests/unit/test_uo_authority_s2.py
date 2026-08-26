# -*- coding: utf-8 -*-
"""S2: UO authority is arch-scoped ``.uo``; update/query fail-closed."""
from __future__ import annotations

from pathlib import Path

import pytest

from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import EntityKind
from uo_init.pilot_engines import ENGINES
from uo_init.store.reader import find_uo_product
from uo_init.store.writer import write_codemap
from uo_init.update.plan import plan_kb_update
from uo_init.uo_query import open_query


def _write_product(tmp_path: Path, *, op="toy", arch="arch35") -> Path:
    cm = CodeMap(op_name=op, architecture=arch)
    cm.upsert(EntityKind.ARCH, arch)
    product = tmp_path / ".ascendc-pilot" / arch / "uo" / f"{op}.{arch}.uo"
    write_codemap(cm, product)
    return product


def test_engines_update_chain_has_compile_commit_not_sqlite_export(tmp_path: Path):
    assert "compile" in ENGINES
    assert "commit" in ENGINES
    assert "export_kb" not in ENGINES
    assert "build_index" not in ENGINES
    assert "export_integrity" not in ENGINES
    assert "extract_tiling_key" not in ENGINES
    change_set = {
        "op_name": "toy",
        "files": [{"path": "op_host/foo.cpp", "role": "host", "in_scope": True}],
        "head_revision": "h",
        "base_revision": "b",
        "needs_scope_review": False,
    }
    plan = plan_kb_update(
        tmp_path, "toy", change_set=change_set, write=False, architecture="arch35"
    )
    assert "compile" in plan["actions"]
    assert "commit" in plan["actions"]
    assert "export_kb" not in plan["actions"]
    assert "build_index" not in plan["actions"]
    assert "export_integrity" not in plan["actions"]
    assert "scripts" not in plan
    assert "needs_cbm_reindex" not in plan
    assert "extract_host" in plan["actions"]


def test_find_uo_product_arch_scoped_and_ignores_legacy_top_level(tmp_path: Path):
    product = _write_product(tmp_path)
    found = find_uo_product(tmp_path, op_name="toy", architecture="arch35")
    assert found == product.resolve()

    legacy = tmp_path / ".ascendc-pilot" / "uo" / "other.arch35.uo"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    cm = CodeMap(op_name="other", architecture="arch35")
    write_codemap(cm, legacy)
    found2 = find_uo_product(tmp_path, architecture="arch35")
    assert found2 == product.resolve()
    assert found2 != legacy.resolve()


def test_find_uo_product_newest_when_op_name_spelling_differs(tmp_path: Path) -> None:
    older = _write_product(tmp_path, op="toy_op")
    newer = _write_product(tmp_path, op="ToyOp")
    older.touch()
    import time

    time.sleep(0.05)
    newer.touch()
    found = find_uo_product(tmp_path, architecture="arch35")
    assert found == newer.resolve()


def test_find_uo_product_unique_arch_without_arg(tmp_path: Path):
    product = _write_product(tmp_path)
    found = find_uo_product(tmp_path)
    assert found == product.resolve()


def test_find_uo_product_default_slot(tmp_path: Path):
    product = _write_product(tmp_path, arch="default")
    found = find_uo_product(tmp_path, op_name="toy", architecture="default")
    assert found == product.resolve()
    assert find_uo_product(tmp_path) == product.resolve()


def test_find_uo_product_ambiguous_arch_returns_none(tmp_path: Path):
    _write_product(tmp_path, arch="arch22")
    later = _write_product(tmp_path, arch="arch35")
    assert find_uo_product(tmp_path) is None
    found = find_uo_product(tmp_path, architecture="arch35")
    assert found == later.resolve()


def test_find_uo_product_none_without_uo(tmp_path: Path):
    db = tmp_path / ".ascendc-pilot" / "arch35" / "uo" / "indexes" / "kb_graph.sqlite"
    db.parent.mkdir(parents=True, exist_ok=True)
    db.write_bytes(b"x")
    assert find_uo_product(tmp_path, architecture="arch35") is None


def test_open_codemap_query_fail_closed(tmp_path: Path):
    from uo_init.query.engine import open_codemap_query

    with pytest.raises(FileNotFoundError):
        open_codemap_query(tmp_path)
    product = _write_product(tmp_path)
    q = open_codemap_query(tmp_path, architecture="arch35")
    assert Path(q.path) == product.resolve()


def test_cli_status_only_and_dump_list_use_uo(tmp_path: Path, capsys):
    import json

    from ascendc_pilot.cli import main

    rc = main(
        [
            "uo-query",
            "--project",
            str(tmp_path),
            "--architecture",
            "arch35",
            "--status-only",
        ]
    )
    assert rc == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload.get("ok") is False

    product = _write_product(tmp_path)
    quality = product.parent / "checks" / "quality.yaml"
    quality.parent.mkdir(parents=True, exist_ok=True)
    quality.write_text(
        "grade: ready\n"
        "integrity: pass\n"
        "locate_ready: true\n"
        "graph:\n"
        "  entity_count: 12\n"
        "  relation_count: 34\n"
        "unresolved:\n"
        "  locate_blocking: 0\n"
        "  total: 2\n",
        encoding="utf-8",
    )
    rc = main(
        [
            "uo-query",
            "--project",
            str(tmp_path),
            "--architecture",
            "arch35",
            "--status-only",
        ]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload.get("ok") is True
    assert payload.get("product", "").endswith(product.name)
    assert payload.get("grade") == "ready"
    assert payload.get("entity_count") == 12
    assert payload.get("relation_count") == 34
    assert payload.get("locate_blocking") == 0
    assert payload.get("unresolved_total") == 2
    assert payload.get("locate_ready") is True

    rc = main(
        [
            "uo",
            "dump",
            "--project",
            str(tmp_path),
            "--architecture",
            "arch35",
            "--list",
        ]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload.get("ok") is True
    assert isinstance(payload.get("views"), list)


def test_cli_dump_list_fails_without_product(tmp_path: Path):
    from ascendc_pilot.cli import main

    rc = main(
        [
            "uo",
            "dump",
            "--project",
            str(tmp_path),
            "--architecture",
            "arch35",
            "--list",
        ]
    )
    assert rc == 1


def test_uo_root_unique_arch_without_env(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("UO_ARCH", raising=False)
    monkeypatch.delenv("ASCENDC_ARCH", raising=False)
    from uo_init.pilot_engines import _uo_root

    uo = tmp_path / ".ascendc-pilot" / "arch35" / "uo"
    uo.mkdir(parents=True)
    assert _uo_root(tmp_path) == uo.resolve()

    legacy = tmp_path / "legacy" / ".ascendc-pilot" / "uo"
    legacy.mkdir(parents=True)
    with pytest.raises(ValueError, match="ARCHITECTURE"):
        _uo_root(tmp_path / "legacy")


def test_update_operator_fail_closed_without_uo(tmp_path: Path):
    from uo_init.update.apply import update_operator

    with pytest.raises(FileNotFoundError, match=r"\.uo"):
        update_operator(tmp_path, "toy", architecture="arch35")


def test_emit_confidence_report_removed(tmp_path: Path):
    """The retired subcommand must not be reachable on `acp`.

    This asserted a structured `legacy_command_removed` payload, but no
    legacy-command shim was ever built: argparse simply does not register the
    subcommand, so it exits 2 on an unknown choice. Assert the guarantee that
    actually exists rather than a rejection contract nothing implements.
    """
    import pytest

    from ascendc_pilot.cli import main

    with pytest.raises(SystemExit) as excinfo:
        main(["emit-confidence-report", "--project", str(tmp_path)])
    assert excinfo.value.code == 2


def test_migrate_refuses_legacy_agent_dir(tmp_path: Path):
    from ascendc_pilot.paths import ensure_control_layout, migrate_legacy_agent_dir

    (tmp_path / ".ascendc-agent").mkdir()
    out = migrate_legacy_agent_dir(tmp_path, arch="arch35")
    assert out.get("ok") is False
    assert out.get("error") == "legacy_agent_dir"
    import pytest

    with pytest.raises(ValueError, match="legacy_agent_dir"):
        ensure_control_layout(tmp_path, arch="arch35")


def test_migrate_refuses_top_level_uo_product(tmp_path: Path):
    from ascendc_pilot.paths import migrate_top_level_uo_products

    dest = tmp_path / ".ascendc-pilot" / "uo"
    dest.mkdir(parents=True)
    (dest / "toy.arch35.uo").write_bytes(b"x")
    out = migrate_top_level_uo_products(tmp_path)
    assert out.get("ok") is False
    assert out.get("error") == "legacy_top_level_uo"
