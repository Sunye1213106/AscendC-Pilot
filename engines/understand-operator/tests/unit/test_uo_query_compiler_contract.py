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


def test_buffer_allocated_and_wrapper_hits(tmp_path: Path) -> None:
    cm = CodeMap(op_name="toy", architecture="arch35")
    cm.add_entity(
        Entity(
            id="BUF_Q",
            kind=EntityKind.BUFFER,
            name="q0",
            attrs={"allocated": True, "wraps_storage": True},
            file="op_kernel/arch35/process.h",
            line_start=20,
            status="extracted",
        )
    )
    cm.add_entity(
        Entity(
            id="TYPE_WRAP",
            kind=EntityKind.TYPE,
            name="Basket",
            attrs={"wraps_storage": True, "wraps_lock": True},
            file="op_kernel/arch35/process.h",
            line_start=8,
            status="extracted",
        )
    )
    _product(cm, tmp_path)
    q = open_query(tmp_path)
    out = q.aggregate_buffer("Basket")
    assert out["count"] >= 1
    names = [str(row.get("name") or "") for row in out["buffers"]]
    assert any(n == "Basket" for n in names)
    queued = q.aggregate_buffer("q0")
    assert queued["count"] >= 1


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


def test_empty_pipe_search_retries_tpipe(tmp_path: Path) -> None:
    from uo_init.query.hints import attach_query_hints

    payload: dict = {"ok": True, "count": 0}
    attach_query_hints(payload, "PRE_CORE_POST", count=0, kinds=("PIPE",))
    assert "TPipe" in payload["suggested_retries"]
    assert "pipeIn" not in payload["suggested_retries"]
    assert "operator index" in payload["hint"]
    assert "PRE_CORE_POST" in payload["hint"]
    assert "RegbaseFAG" not in payload["hint"]


def test_kernel_launch_keeps_entry_file_drops_hw_and_legacy(tmp_path: Path) -> None:
    cm = CodeMap(op_name="toy", architecture="arch35")
    cm.add_entity(
        Entity(
            id="PIPE_V",
            kind=EntityKind.PIPE,
            name="PIPE_V",
            attrs={"role": "src_pipe", "catalog": "ascendc"},
            status="extracted",
        )
    )
    cm.add_entity(
        Entity(
            id="PIPE_legacy",
            kind=EntityKind.PIPE,
            name="pipeSfmg",
            attrs={"role": "launch_instance"},
            file="op_kernel/toy.cpp",
            line_start=40,
            status="confirmed",
        )
    )
    for name, line in (("pipeIn", 10), ("pipeBase", 20), ("pipePost", 30)):
        cm.add_entity(
            Entity(
                id=f"PIPE_{name}",
                kind=EntityKind.PIPE,
                name=name,
                attrs={"role": "launch_instance", "kernel_file": "op_kernel/arch35/entry.h"},
                file="op_kernel/arch35/entry.h",
                line_start=line,
                status="confirmed",
            )
        )
    _product(cm, tmp_path)
    q = open_query(tmp_path)
    out = q.aggregate_kernel_launch(limit=8)
    names = [row.get("pipe") for row in out["phases"] if row.get("ok")]
    assert names == ["pipeIn", "pipeBase", "pipePost"]
    assert "PIPE_V" not in names
    assert "pipeSfmg" not in names
    assert (out.get("coverage") or {}).get("completeness") == "siblings_checked"
    others = " ".join(out.get("other_kernels") or [])
    assert "toy.cpp" in others.replace("\\", "/")


def test_occupancy_skips_non_core_fields_and_input_writers(tmp_path: Path) -> None:
    from uo_init.ir.relation import RelationKind

    cm = CodeMap(op_name="toy", architecture="arch35")
    inner = Entity(
        id="TDF_s1",
        kind=EntityKind.TILING_FIELD,
        name="s1Inner",
        attrs={
            "owner": "BaseParams",
            "local_aliases": [{"name": "s1Inner", "rhs": "64"}],
        },
        file="op_kernel/td.h",
        line_start=4,
        status="confirmed",
    )
    core = Entity(
        id="TDF_core",
        kind=EntityKind.TILING_FIELD,
        name="coreNum",
        file="op_kernel/td.h",
        line_start=5,
        status="confirmed",
    )
    query = Entity(
        id="IN_query",
        kind=EntityKind.INPUT,
        name="query",
        file="op_host/proto.h",
        line_start=1,
        status="confirmed",
    )
    cm.add_entity(inner)
    cm.add_entity(core)
    cm.add_entity(query)
    cm.link(RelationKind.WRITES, query.id, inner.id, status="confirmed")
    _product(cm, tmp_path)
    q = open_query(tmp_path)
    skip = q.field_impact("s1Inner")
    assert skip["ok"] is True
    assert not skip.get("occupancy_axis")
    writers = skip.get("writers") or []
    assert all(str(row.get("kind") or "") != EntityKind.INPUT.value for row in writers)
    hit = q.field_impact("coreNum")
    assert hit["occupancy_axis"] == "coreNum vs aicNum"


def test_locate_collapses_same_file_sites(tmp_path: Path) -> None:
    cm = CodeMap(op_name="toy", architecture="arch35")
    sites = [
        {"file": "op_host/split.cpp", "line": 100 + i, "line_start": 100 + i}
        for i in range(10)
    ]
    cm.add_entity(
        Entity(
            id="FN_split",
            kind=EntityKind.FUNCTION,
            name="SetSplitAxis",
            attrs={"definition_sites": sites},
            file="op_host/split.cpp",
            line_start=100,
            status="confirmed",
        )
    )
    _product(cm, tmp_path)
    q = open_query(tmp_path)
    out = q.aggregate_locate("SetSplitAxis", limit=8)
    assert len(out["locations"]) == 1
    facts = out["locations"][0].get("facts") or {}
    assert len(facts.get("definition_sites") or []) >= 10
    assert (out.get("coverage") or {}).get("completeness") != "page_clipped"
    assert (out.get("coverage") or {}).get("answerable") is True


def test_agent_query_name_card_groups_edges_and_field_extras(tmp_path: Path) -> None:
    from uo_init.ir.relation import RelationKind

    cm = CodeMap(op_name="toy", architecture="arch35")
    field = Entity(
        id="TDF_s1",
        kind=EntityKind.TILING_FIELD,
        name="s1Inner",
        attrs={"owner": "BaseParams"},
        file="op_kernel/td.h",
        line_start=4,
        status="confirmed",
    )
    writer = Entity(
        id="FN_set",
        kind=EntityKind.FUNCTION,
        name="SetS1Inner",
        file="op_host/td.cpp",
        line_start=20,
        status="confirmed",
    )
    reader = Entity(
        id="FN_use",
        kind=EntityKind.FUNCTION,
        name="UseS1Inner",
        file="op_kernel/process.h",
        line_start=8,
        status="confirmed",
    )
    cm.add_entity(field)
    cm.add_entity(writer)
    cm.add_entity(reader)
    cm.link(RelationKind.WRITES, writer.id, field.id, status="confirmed")
    cm.link(RelationKind.READS, reader.id, field.id, status="confirmed")
    _product(cm, tmp_path)
    q = open_query(tmp_path)
    out = q.agent_query(pattern="s1Inner")
    assert out["shape"] == "name"
    card = next(c for c in out["cards"] if c.get("kind") == EntityKind.TILING_FIELD.value)
    assert card["file"]
    assert "WRITES" in (card.get("edges") or {}) or (card.get("extras") or {}).get("writers")
    assert "READS" in (card.get("edges") or {}) or (card.get("extras") or {}).get("readers")
    assert any(name == "SetS1Inner" for name in (out.get("next") or []))


def test_agent_query_cover_empty_omits_sel_blocks(tmp_path: Path) -> None:
    import json

    cm = CodeMap(op_name="toy", architecture="arch35")
    _product(cm, tmp_path)
    q = open_query(tmp_path)
    out = q.agent_query(pattern="DTemplateNum=999")
    assert out["shape"] == "cover"
    assert int(out.get("matching_block_count") or 0) == 0
    assert out.get("template_blocks") == []
    blob = json.dumps(out)
    assert "ARGS_SEL" not in blob


def test_agent_query_index_and_around(tmp_path: Path) -> None:
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
    _product(cm, tmp_path)
    q = open_query(tmp_path)
    index = q.agent_query()
    assert index["shape"] == "index"
    names = [row.get("pipe") for row in index.get("phases") or []]
    assert "pipeIn" in names
    assert "Dim=" in str(index.get("hint") or "")
    around = q.agent_query(file="op_kernel/arch35/toy_entry_regbase.h", line=10)
    assert around["shape"] == "around"


def test_agent_query_rejects_nl_or_multi_token(tmp_path: Path) -> None:
    from uo_init.query.hints import looks_like_nl_or_multi_token, nl_or_multi_token_payload

    assert looks_like_nl_or_multi_token("FlashAttentionScoreGrad host_api_params")
    assert looks_like_nl_or_multi_token("这个算子的 tiling 怎么切")
    assert not looks_like_nl_or_multi_token("s1Inner")
    assert not looks_like_nl_or_multi_token("Dim=DTemplateNum")
    payload = nl_or_multi_token_payload("FlashAttentionScoreGrad host_api_params tiling_fields")
    assert payload["ok"] is False
    assert payload["empty_reason"] == "nl_or_multi_token"
    assert "FlashAttentionScoreGrad" in payload["suggested_retries"]
    cm = CodeMap(op_name="toy", architecture="arch35")
    cm.add_entity(
        Entity(
            id="PIPE_pipeIn",
            kind=EntityKind.PIPE,
            name="pipeIn",
            file="op_kernel/arch35/toy_entry_regbase.h",
            line_start=10,
            status="confirmed",
        )
    )
    _product(cm, tmp_path)
    q = open_query(tmp_path)
    out = q.agent_query(pattern="FlashAttentionScoreGrad host_api_params")
    assert out["ok"] is False
    assert out["empty_reason"] == "nl_or_multi_token"
