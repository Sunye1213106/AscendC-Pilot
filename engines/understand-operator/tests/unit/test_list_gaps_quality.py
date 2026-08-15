# -*- coding: utf-8 -*-
"""list_gaps classification and cannbot quality grade."""

from __future__ import annotations

from uo_init.diagnostics.quality import codemap_quality
from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import EntityKind
from uo_init.resolve.semantic_gap import classify_gap_entity, list_gaps, summarize_gaps


def test_list_gaps_skips_settled_project_and_builtin() -> None:
    cm = CodeMap(op_name="toy", architecture="arch35")
    cm.upsert(
        EntityKind.TYPE,
        "LoopInfo",
        attrs={"role": "source_type", "root_status": "PROJECT"},
        status="extracted",
    )
    cm.upsert(
        EntityKind.OPERATION,
        "__builtin_expect",
        attrs={"callee": "__builtin_expect", "root_status": "BUILTIN", "root_proof": "compiler_builtin"},
        status="extracted",
    )
    cm.upsert(
        EntityKind.OPERATION,
        "Helper",
        attrs={"callee": "Helper", "root_status": "PROJECT", "root_proof": "project_free"},
        status="extracted",
    )
    partial_noise = cm.upsert(
        EntityKind.TYPE,
        "PreloadArgs",
        attrs={"role": "source_type", "root_status": "PROJECT"},
        status="partial",
    )
    # upsert may promote PROJECT+partial → extracted
    assert classify_gap_entity(partial_noise) is None
    gaps = [g for g in list_gaps(cm) if g.get("code") == "entity_status"]
    names = {g.get("name") for g in gaps}
    assert "LoopInfo" not in names
    assert "__builtin_expect" not in names
    assert "Helper" not in names
    assert "PreloadArgs" not in names


def test_host_leaf_and_field_owner_buckets() -> None:
    cm = CodeMap(op_name="toy", architecture="arch35")
    host = cm.upsert(
        EntityKind.VARIABLE,
        "context_",
        eid="HOSTUNRESOLVED::context_",
        attrs={"provenance": "source_host_unresolved_dependency"},
        status="partial",
    )
    field = cm.upsert(
        EntityKind.TILING_FIELD,
        "mm1TilingData",
        attrs={"reason": "field_owner_unknown"},
        status="partial",
    )
    get_op = cm.upsert(
        EntityKind.OPERATION,
        "Get",
        attrs={"callee": "Get", "root_status": "UNRESOLVED"},
        status="partial",
    )
    assert classify_gap_entity(host) == "host_runtime_leaf"
    assert classify_gap_entity(field) == "locate_blocking"
    assert classify_gap_entity(get_op) == "catalog_unproven"
    gaps = list_gaps(cm)
    buckets = summarize_gaps(gaps)
    assert buckets["host_runtime_leaf"] >= 1
    assert buckets["locate_blocking"] >= 1
    assert buckets["catalog_unproven"] >= 1


def test_quality_ready_when_surfaces_green() -> None:
    cm = CodeMap(op_name="toy", architecture="arch35")
    cm.upsert(
        EntityKind.FUNCTION,
        "DoTiling",
        attrs={"provenance": "source_host_function"},
        file="op_host/t.cpp",
        line=1,
        status="extracted",
    )
    cm.upsert(
        EntityKind.KERNEL,
        "toy_kernel",
        attrs={"source_signature": True},
        file="op_kernel/toy.cpp",
        line=1,
        status="extracted",
    )
    cm.upsert(
        EntityKind.INPUT,
        "q",
        attrs={"api_kind": "tensor", "dtype": "float16", "facts": {"dtype": "float16"}},
        file="op_graph/toy_proto.h",
        line=10,
        status="extracted",
    )
    cm.upsert(
        EntityKind.OUTPUT,
        "out",
        attrs={"api_kind": "tensor"},
        file="op_graph/toy_proto.h",
        line=20,
        status="extracted",
    )
    cm.upsert(
        EntityKind.TILING_KEY,
        "SplitAxis",
        attrs={
            "host_packing_expressions": ["0"],
            "packing_value_sites": [{"file": "op_host/t.cpp", "line": 4}],
        },
        file="op_host/t.h",
        line=2,
        status="extracted",
    )
    cm.upsert(
        EntityKind.TILING_DATA,
        "ToyTiling",
        attrs={},
        file="op_kernel/t.h",
        line=1,
        status="extracted",
    )
    cm.upsert(
        EntityKind.TILING_FIELD,
        "s1Inner",
        attrs={
            "owner": "ToyTiling",
            "rhs": "aivNum",
            "host_writer_sites": [{"file": "op_host/t.cpp", "line": 8}],
        },
        file="op_kernel/t.h",
        line=3,
        status="extracted",
    )
    cm.upsert(
        EntityKind.OPERATION,
        "DataCopy",
        attrs={"callee": "DataCopy", "root_status": "REACHED"},
        file="op_kernel/toy.cpp",
        line=40,
        status="extracted",
    )
    cm.upsert(
        EntityKind.BUFFER,
        "ub",
        attrs={"memory_space": "UB", "tposition": "VECIN", "root_status": "REACHED"},
        file="op_kernel/toy.cpp",
        line=30,
        status="extracted",
    )
    cm.link("FLOWS_TO", "E_placeholder", "E_placeholder2")  # may no-op if ids missing
    # Wire evidence-backed paths with real ids
    kernel = next(e for e in cm.by_kind(EntityKind.KERNEL))
    inp = next(e for e in cm.by_kind(EntityKind.INPUT))
    out = next(e for e in cm.by_kind(EntityKind.OUTPUT))
    key = next(e for e in cm.by_kind(EntityKind.TILING_KEY))
    td = next(e for e in cm.by_kind(EntityKind.TILING_DATA))
    cm.link("DERIVES", inp.id, key.id)
    cm.link("SELECTS", key.id, kernel.id)
    cm.link("FLOWS_TO", td.id, kernel.id)
    cm.link("FLOWS_TO", kernel.id, out.id)
    cm.link("FLOWS_TO", inp.id, kernel.id)

    q = codemap_quality(cm, integrity_ok=True)
    assert q["grade"] in {"ready", "usable"}, q
    assert q["surfaces"]["field_rw"]["ok"] is True
    assert q["surfaces"]["kernel_api"]["ok"] is True


def test_quality_empty_graph_fails_when_source_has_copy(tmp_path: Path) -> None:
    op = tmp_path / "op"
    (op / "op_kernel" / "arch35").mkdir(parents=True)
    (op / "op_kernel" / "arch35" / "k.h").write_text(
        "void Kernel() { DataCopy(dst, src, n); }\n",
        encoding="utf-8",
    )
    cm = CodeMap(op_name="glue", architecture="arch35")
    cm.upsert(
        EntityKind.KERNEL,
        "glue_kernel",
        attrs={"source_signature": True},
        file="op_kernel/arch35/k.h",
        line=1,
        status="extracted",
    )
    cm.upsert(
        EntityKind.INPUT,
        "x",
        attrs={"api_kind": "tensor", "dtype": "float16", "facts": {"dtype": "float16"}},
        file="op_graph/p.h",
        line=1,
        status="extracted",
    )
    q = codemap_quality(cm, integrity_ok=True, source_root=op)
    assert q["surfaces"]["kernel_api"]["ok"] is False
    assert "kernel_api_gap" in q["not_ready_reasons"]


def test_quality_honest_empty_graph_when_source_has_no_needles(tmp_path: Path) -> None:
    op = tmp_path / "op"
    (op / "op_kernel" / "arch35").mkdir(parents=True)
    (op / "op_kernel" / "arch35" / "k.h").write_text(
        "void Kernel() { int x = 0; (void)x; }\n",
        encoding="utf-8",
    )
    cm = CodeMap(op_name="empty", architecture="arch35")
    cm.upsert(
        EntityKind.KERNEL,
        "empty_kernel",
        attrs={"source_signature": True},
        file="op_kernel/arch35/k.h",
        line=1,
        status="extracted",
    )
    cm.upsert(
        EntityKind.INPUT,
        "x",
        attrs={"api_kind": "tensor", "dtype": "float16", "facts": {"dtype": "float16"}},
        file="op_graph/p.h",
        line=1,
        status="extracted",
    )
    q = codemap_quality(cm, integrity_ok=True, source_root=op)
    assert q["surfaces"]["kernel_api"]["ok"] is True


def test_quality_not_ready_without_kernel_span() -> None:
    cm = CodeMap(op_name="empty", architecture="arch35")
    cm.upsert(EntityKind.INPUT, "q", status="extracted")
    q = codemap_quality(cm, integrity_ok=True)
    assert q["grade"] == "not_ready"
    assert "no_kernel_span" in q["not_ready_reasons"]


def _ready_skeleton(*, with_output: bool, link_output: bool) -> CodeMap:
    cm = CodeMap(op_name="toy", architecture="arch35")
    cm.upsert(
        EntityKind.FUNCTION,
        "DoTiling",
        attrs={"provenance": "source_host_function"},
        file="op_host/t.cpp",
        line=1,
        status="extracted",
    )
    cm.upsert(
        EntityKind.KERNEL,
        "toy_kernel",
        attrs={"source_signature": True},
        file="op_kernel/toy.cpp",
        line=1,
        status="extracted",
    )
    cm.upsert(
        EntityKind.INPUT,
        "q",
        attrs={"api_kind": "tensor", "dtype": "float16", "facts": {"dtype": "float16"}},
        file="op_graph/toy_proto.h",
        line=10,
        status="extracted",
    )
    if with_output:
        cm.upsert(
            EntityKind.OUTPUT,
            "out",
            attrs={"api_kind": "tensor"},
            file="op_graph/toy_proto.h",
            line=20,
            status="extracted",
        )
    cm.upsert(
        EntityKind.TILING_KEY,
        "SplitAxis",
        attrs={
            "host_packing_expressions": ["0"],
            "packing_value_sites": [{"file": "op_host/t.cpp", "line": 4}],
        },
        file="op_host/t.h",
        line=2,
        status="extracted",
    )
    cm.upsert(
        EntityKind.TILING_DATA,
        "ToyTiling",
        attrs={},
        file="op_kernel/t.h",
        line=1,
        status="extracted",
    )
    cm.upsert(
        EntityKind.TILING_FIELD,
        "s1Inner",
        attrs={
            "owner": "ToyTiling",
            "rhs": "aivNum",
            "host_writer_sites": [{"file": "op_host/t.cpp", "line": 8}],
        },
        file="op_kernel/t.h",
        line=3,
        status="extracted",
    )
    cm.upsert(
        EntityKind.OPERATION,
        "DataCopy",
        attrs={"callee": "DataCopy", "root_status": "REACHED"},
        file="op_kernel/toy.cpp",
        line=40,
        status="extracted",
    )
    cm.upsert(
        EntityKind.BUFFER,
        "ub",
        attrs={"memory_space": "UB", "tposition": "VECIN", "root_status": "REACHED"},
        file="op_kernel/toy.cpp",
        line=30,
        status="extracted",
    )
    kernel = next(e for e in cm.by_kind(EntityKind.KERNEL))
    inp = next(e for e in cm.by_kind(EntityKind.INPUT))
    key = next(e for e in cm.by_kind(EntityKind.TILING_KEY))
    td = next(e for e in cm.by_kind(EntityKind.TILING_DATA))
    cm.link("DERIVES", inp.id, key.id)
    cm.link("SELECTS", key.id, kernel.id)
    cm.link("FLOWS_TO", td.id, kernel.id)
    cm.link("FLOWS_TO", inp.id, kernel.id)
    if with_output and link_output:
        out = next(e for e in cm.by_kind(EntityKind.OUTPUT))
        cm.link("FLOWS_TO", kernel.id, out.id)
    if not with_output:
        cm.meta["source_contract_stats"] = {
            "api_source_files": 1,
            "api_outputs": 0,
        }
    return cm


def test_quality_ready_when_proto_has_no_output() -> None:
    cm = _ready_skeleton(with_output=False, link_output=False)
    q = codemap_quality(cm, integrity_ok=True)
    assert q["surfaces"]["paths"]["ok"] is True, q["surfaces"]["paths"]
    assert q["surfaces"]["paths"]["output_n"] == 0
    assert q["grade"] == "ready", q


def test_quality_paths_fail_when_output_exists_without_path() -> None:
    cm = _ready_skeleton(with_output=True, link_output=False)
    q = codemap_quality(cm, integrity_ok=True)
    assert q["surfaces"]["paths"]["ok"] is False, q["surfaces"]["paths"]
    assert q["surfaces"]["paths"]["input_output"] is False
    assert q["grade"] == "usable", q
