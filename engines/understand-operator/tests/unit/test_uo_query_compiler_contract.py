# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import Entity, EntityKind
from uo_init.query.sql import _fit_payload
from uo_init.store.writer import write_codemap
from uo_init.uo_query import open_query


def _product(cm: CodeMap, tmp_path: Path) -> Path:
    product = tmp_path / ".ascendc-pilot" / "arch35" / "uo" / "toy.arch35.uo"
    product.parent.mkdir(parents=True, exist_ok=True)
    write_codemap(cm, product)
    return product


def test_arch35_ranks_ahead_of_unscoped_cpp(tmp_path: Path) -> None:
    cm = CodeMap(op_name="toy", architecture="arch35")
    cm.add_entity(
        Entity(
            id="OP_legacy",
            kind=EntityKind.OPERATION,
            name="OpBarrier",
            attrs={"callee": "OpBarrier"},
            file="op_kernel/toy_op.cpp",
            line_start=85,
            status="extracted",
        )
    )
    cm.add_entity(
        Entity(
            id="OP_arch",
            kind=EntityKind.OPERATION,
            name="OpBarrier",
            attrs={"callee": "OpBarrier", "kernel_phase": "pre"},
            file="op_kernel/arch35/toy_entry_regbase.h",
            line_start=40,
            status="extracted",
        )
    )
    _product(cm, tmp_path)
    q = open_query(tmp_path)
    rows = q.search("OpBarrier", kinds=(), limit=8)
    assert str(rows[0]["file"]).replace("\\", "/").endswith("toy_entry_regbase.h")
    api = q.aggregate_kernel_api("OpBarrier", limit=8)
    assert "arch35" in str(api["calls"][0]["file"]).replace("\\", "/")


def test_kernel_launch_returns_three_phases(tmp_path: Path) -> None:
    cm = CodeMap(op_name="toy", architecture="arch35")
    for name, phase, line in (
        ("pipeIn", "pre", 10),
        ("pipeBase", "main", 20),
        ("pipePost", "post", 30),
    ):
        cm.add_entity(
            Entity(
                id=f"PIPE_{name}",
                kind=EntityKind.PIPE,
                name=name,
                attrs={"kernel_phase": phase},
                file="op_kernel/arch35/toy_entry_regbase.h",
                line_start=line,
                status="confirmed",
            )
        )
    cm.add_entity(
        Entity(
            id="FN_entry",
            kind=EntityKind.FUNCTION,
            name="OpEntry",
            file="op_kernel/arch35/toy_entry_regbase.h",
            line_start=1,
            status="confirmed",
        )
    )
    _product(cm, tmp_path)
    q = open_query(tmp_path)
    out = q.aggregate_kernel_launch()
    names = [row.get("pipe") for row in out["phases"] if row.get("ok")]
    assert names == ["pipeIn", "pipeBase", "pipePost"]
    assert out["entry"]["name"] == "OpEntry"
    assert "ProcessVec" not in str(out)
    assert str(out["phases"][0]["file"]).replace("\\", "/").find("arch35") >= 0


def test_field_resolves_local_alias_without_hardcoded_map(tmp_path: Path) -> None:
    cm = CodeMap(op_name="toy", architecture="arch35")
    cm.add_entity(
        Entity(
            id="TDF_split",
            kind=EntityKind.TILING_FIELD,
            name="coreSplit",
            attrs={
                "owner": "SplitParams",
                "local_aliases": [
                    {"name": "splitCount", "rhs": "B * N", "file": "op_host/td.cpp", "line": 12},
                ],
                "fused_outer_candidates": [
                    {"name": "splitCount", "rhs": "B * N"},
                ],
            },
            file="op_kernel/td.h",
            line_start=10,
            status="confirmed",
        )
    )
    _product(cm, tmp_path)
    q = open_query(tmp_path)
    hit = q.field_impact("splitCount")
    assert hit["ok"] is True
    assert hit["field"]["name"] == "coreSplit"
    assert hit["alias_from"] == "splitCount"
    assert hit["occupancy_axis"] == "splitCount vs aicNum"
    assert hit["coverage"]["occupancy_axis"] == "splitCount vs aicNum"


def test_buffer_policy_suffix_hits_without_mutex_catalog(tmp_path: Path) -> None:
    cm = CodeMap(op_name="toy", architecture="arch35")
    cm.add_entity(
        Entity(
            id="TYPE_3",
            kind=EntityKind.TYPE,
            name="FooPolicy3buff",
            attrs={"role": "storage_wrapper_type", "mutex_policy": "3buff"},
            file="op_kernel/arch35/block_cube.h",
            line_start=80,
            status="confirmed",
        )
    )
    _product(cm, tmp_path)
    q = open_query(tmp_path)
    out = q.aggregate_buffer("3buff")
    assert out["count"] >= 1
    names = [str(row.get("name") or "") for row in out["buffers"]]
    assert any("3buff" in n.lower() for n in names)
    policies = [str(p).lower() for p in (out["coverage"].get("mutex_policies") or [])]
    assert "3buff" in policies or any("3buff" in n.lower() for n in names)


def test_buffer_policy_type_name_hits_without_role_attr(tmp_path: Path) -> None:
    cm = CodeMap(op_name="toy", architecture="arch35")
    cm.add_entity(
        Entity(
            id="TYPE_P3",
            kind=EntityKind.TYPE,
            name="FooPolicy3buff",
            attrs={},
            file="op_kernel/arch35/mutex_buffers_policy.h",
            line_start=20,
            status="confirmed",
        )
    )
    _product(cm, tmp_path)
    q = open_query(tmp_path)
    out = q.aggregate_buffer("3buff")
    assert out["count"] >= 1
    names = [str(row.get("name") or "") for row in out["buffers"]]
    assert any("3buff" in n.lower() for n in names)


def test_fit_payload_keeps_coverage_and_files() -> None:
    payload = {
        "ok": True,
        "coverage": {
            "sibling_files": ["a.cpp", "b.cpp", "c.cpp"],
            "completeness": "siblings_checked",
            "total_matched": 20,
            "answerable": True,
        },
        "files": {
            "a.cpp": [{"name": "x", "line": 1}],
            "b.cpp": [{"name": "y", "line": 2}],
        },
        "dim_coverage": {"DTemplateNum": ["64", "128", "192", "256", "768"]},
        "locations": [
            {"file": f"f{i}.cpp", "line_start": i, "snippet": ("line\n" * 80) + ("x" * 400)}
            for i in range(20)
        ],
    }
    out = _fit_payload(payload, max_chars=2500)
    assert "coverage" in out
    assert out["coverage"]["sibling_files"] == ["a.cpp", "b.cpp", "c.cpp"]
    assert "files" in out
    assert "dim_coverage" in out
    assert len(out["locations"]) >= 5


def test_fit_payload_keeps_coverage_checked_when_clipped() -> None:
    payload = {
        "ok": True,
        "coverage": {
            "completeness": "coverage_checked",
            "total_matched": 40,
            "answerable": True,
            "dim_coverage": {"DTemplateNum": ["64", "128", "192"]},
        },
        "dim_coverage": {"DTemplateNum": ["64", "128", "192"]},
        "template_blocks": [
            {"file": f"sel_{i}.h", "snippet": ("ARGS_SEL\n" * 40) + ("x" * 800)}
            for i in range(12)
        ],
    }
    out = _fit_payload(payload, max_chars=1200)
    assert out["coverage"]["completeness"] == "coverage_checked"
    assert out["coverage"]["dim_coverage"]["DTemplateNum"] == ["64", "128", "192"]
    assert "dim_coverage" in out


def test_q11_compile_uses_locate_not_kernel_launch() -> None:
    from uo_init.query.plan import compile_query, plan_query_slices

    q11 = (
        "偶发 hang，plog 停在 Pre 末尾 SyncALLCores。有人说 BufferID 没配对。"
        "arch35 为什么 PostTiling 要 SetScheduleMode(1)？哪条路径故意不设？"
        "AIC/AIV dummy 和 CrossCore flag 怎么配？"
    )
    ids = [row["slice_id"] for row in plan_query_slices(q11)]
    assert "pipe" not in ids
    assert "locate" in ids
    plan = compile_query(q11)
    assert plan["first_query"][0]["mode"] == "locate"
    assert plan["first_query"][0]["pattern"] == "SetScheduleMode"


def test_empty_pipe_search_retries_pipein(tmp_path: Path) -> None:
    from uo_init.query.hints import attach_query_hints

    payload: dict = {"ok": True, "count": 0}
    attach_query_hints(payload, "PRE_CORE_POST", count=0, kinds=("PIPE",))
    assert "pipeIn" in payload["suggested_retries"]
    assert "kernel_launch" in payload["hint"]
    assert "PRE_CORE_POST" in payload["hint"]
    assert "RegbaseFAG" not in payload["hint"]
