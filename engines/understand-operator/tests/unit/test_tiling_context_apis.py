# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from uo_init.clang_walk import CallSite
from uo_init.host_ir import HostIR
from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import EntityKind
from uo_init.passes.tiling_context_apis import enrich_tiling_context_apis
from uo_init.store.writer import write_codemap
from uo_init.uo_query import open_query


def test_tiling_context_apis_locate_setschedulemode(tmp_path: Path) -> None:
    host = tmp_path / "op_host" / "arch35"
    host.mkdir(parents=True)
    src = host / "tiling.cpp"
    src.write_text(
        "void DoTiling() {\n"
        "  if (need_batch) {\n"
        "    ctx->SetScheduleMode(1);\n"
        "  }\n"
        "  ctx->SetBlockDim(8);\n"
        "  helper->DoSomethingElse();\n"
        "}\n",
        encoding="utf-8",
    )
    rel = "op_host/arch35/tiling.cpp"
    ir = HostIR(
        call_sites=[
            CallSite(
                caller="DoTiling",
                callee="SetScheduleMode",
                file=rel,
                line=3,
                args=("1",),
                receiver="ctx",
                receiver_type="gert::TilingContext *",
            ),
            CallSite(
                caller="DoTiling",
                callee="SetBlockDim",
                file=rel,
                line=5,
                args=("8",),
                receiver="ctx",
            ),
            CallSite(
                caller="DoTiling",
                callee="DoSomethingElse",
                file=rel,
                line=6,
                receiver="helper",
            ),
        ]
    )
    cm = CodeMap(op_name="ToyOp", architecture="arch35")
    enrich_tiling_context_apis(cm, tmp_path, architecture="arch35", host_ir=ir)
    names = {e.name for e in cm.by_kind(EntityKind.OPERATION)}
    assert "SetScheduleMode" in names
    assert "SetBlockDim" in names
    assert "DoSomethingElse" not in names
    sched = next(e for e in cm.by_kind(EntityKind.OPERATION) if e.name == "SetScheduleMode")
    assert sched.line_start == 3
    assert sched.attrs.get("catalog") == "cann_tiling_context"
    assert sched.attrs.get("layer") == "host"
    assert sched.attrs.get("argument") == "1"

    product = tmp_path / ".ascendc-pilot" / "arch35" / "uo" / "toy.arch35.uo"
    product.parent.mkdir(parents=True, exist_ok=True)
    write_codemap(cm, product)
    q = open_query(tmp_path)
    loc = q.aggregate_locate("SetScheduleMode")
    assert loc["count"] >= 1
    files = " ".join(str(row.get("file") or "") for row in loc["locations"])
    assert "tiling.cpp" in files.replace("\\", "/")
    facts = next(
        (row.get("facts") or {})
        for row in loc["locations"]
        if str(row.get("name") or "") == "SetScheduleMode"
    )
    assert facts.get("catalog") == "cann_tiling_context"
    assert str(facts.get("argument") or "") == "1"


def test_tiling_context_apis_mints_platform_getcorenumaiv(tmp_path: Path) -> None:
    host = tmp_path / "op_host" / "arch35"
    host.mkdir(parents=True)
    src = host / "tiling.cpp"
    src.write_text(
        "void DoTiling() {\n"
        "  uint32_t aiv = plat->GetCoreNumAiv();\n"
        "  ctx->SetBlockDim(aiv);\n"
        "}\n",
        encoding="utf-8",
    )
    rel = "op_host/arch35/tiling.cpp"
    ir = HostIR(
        call_sites=[
            CallSite(
                caller="DoTiling",
                callee="GetCoreNumAiv",
                file=rel,
                line=2,
                receiver="plat",
            ),
            CallSite(
                caller="DoTiling",
                callee="SetBlockDim",
                file=rel,
                line=3,
                args=("aiv",),
                receiver="ctx",
            ),
        ]
    )
    cm = CodeMap(op_name="ToyOp", architecture="arch35")
    fn = cm.upsert(
        EntityKind.FUNCTION,
        "DoTiling",
        attrs={"layer": "host", "provenance": "clang_walk"},
        file=rel,
        line=1,
    )
    enrich_tiling_context_apis(cm, tmp_path, architecture="arch35", host_ir=ir)
    aiv = next(e for e in cm.by_kind(EntityKind.OPERATION) if e.name == "GetCoreNumAiv")
    assert aiv.attrs.get("catalog") == "cann_platform"
    assert aiv.line_start == 2
    from uo_init.ir.relation import RelationKind

    callees = {dst.id for _rel, dst in cm.neighbors(fn.id, kind=RelationKind.CALLS, direction="out")}
    assert aiv.id in callees
    product = tmp_path / ".ascendc-pilot" / "arch35" / "uo" / "toy.arch35.uo"
    product.parent.mkdir(parents=True, exist_ok=True)
    write_codemap(cm, product)
    loc = open_query(tmp_path).aggregate_locate("GetCoreNumAiv")
    assert loc["count"] >= 1


def test_tiling_context_apis_skips_without_host_ir(tmp_path: Path) -> None:
    cm = CodeMap(op_name="ToyOp", architecture="arch35")
    enrich_tiling_context_apis(cm, tmp_path, architecture="arch35", host_ir=None)
    assert not list(cm.by_kind(EntityKind.OPERATION))
