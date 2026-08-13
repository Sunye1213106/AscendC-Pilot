# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import EntityKind
from uo_init.passes.host_checks import enrich_host_checks
from uo_init.query.evidence import project_entity
from uo_init.source_locator import locations_from_attr_sites
from uo_init.store.writer import write_codemap
from uo_init.uo_query import open_query


def _op_tree(tmp_path: Path) -> Path:
    root = tmp_path / "toy_op"
    host = root / "op_host" / "arch35"
    host.mkdir(parents=True)
    (host / "tiling.cpp").write_text(
        """
void DoOpTiling() {
    OP_CHECK_IF(s1Inner == 0, OP_LOGE(opName, "bad"), return GRAPH_FAILED);
    OP_CHECK_IF(queryType == DT_INT8, OP_LOGE(opName, "dtype"), return GRAPH_FAILED);
}
""",
        encoding="utf-8",
    )
    return root


def test_host_check_binds_field_and_is_locatable(tmp_path: Path) -> None:
    root = _op_tree(tmp_path)
    cm = CodeMap(op_name="toy", architecture="arch35")
    field = cm.upsert(
        EntityKind.TILING_FIELD,
        "s1Inner",
        eid="TDF_s1",
        attrs={"owner": "ToyTilingData"},
        file="op_kernel/toy_tiling_data.h",
        line=10,
    )
    inp = cm.upsert(
        EntityKind.INPUT,
        "queryType",
        eid="IN_q",
        attrs={"dtype": "float16"},
        file="op_host/arch35/tiling.cpp",
        line=1,
    )
    enrich_host_checks(cm, root, architecture="arch35")

    checks = [e for e in cm.by_kind(EntityKind.BRANCH) if e.attrs.get("branch_kind") == "host_check"]
    assert len(checks) == 2
    assert all(e.file and e.line_start > 0 for e in checks)

    sites = field.attrs.get("check_sites") or []
    assert sites and sites[0]["guard"].startswith("s1Inner")
    assert (inp.attrs.get("check_sites") or [])

    hit = project_entity(field)
    assert hit is not None
    assert hit["facts"]["check_sites"]
    assert "s1Inner" in hit["facts"]["check_sites"][0]["guard"]

    locs = locations_from_attr_sites(field.id, "TILING_FIELD", field.attrs)
    assert any(loc.line_start > 0 and "s1Inner" in loc.snippet for loc in locs)

    product = tmp_path / ".ascendc-pilot" / "arch35" / "uo" / "toy.arch35.uo"
    product.parent.mkdir(parents=True, exist_ok=True)
    write_codemap(cm, product)
    q = open_query(tmp_path)
    locate = q.aggregate_locate("s1Inner")
    assert locate["count"] >= 1
    files = {(row.get("file"), int(row.get("line_start") or 0)) for row in locate["locations"]}
    assert any("tiling.cpp" in str(file) and line > 0 for file, line in files)


def test_from_host_ir_validation_controls_are_located() -> None:
    class _Ctrl:
        def __init__(self):
            self.universe = "VALIDATION_ONLY"
            self.snippet = "OP_CHECK_IF(aicNum_ == 0, return GRAPH_FAILED)"
            self.condition = "aicNum_ == 0"
            self.file = "op_host/tiling.cpp"
            self.line = 90
            self.function = "DoOpTiling"

    class _Host:
        backend = "clang"
        summaries = {}
        writes = []
        call_sites = []
        controls = [_Ctrl()]

    cm = CodeMap.from_host_ir(_Host(), op_name="toy", architecture="arch35")
    checks = [e for e in cm.by_kind(EntityKind.BRANCH) if e.attrs.get("branch_kind") == "host_check"]
    assert len(checks) == 1
    assert checks[0].file.endswith("tiling.cpp")
    assert checks[0].line_start == 90


def test_from_host_ir_function_keeps_declaration_span() -> None:
    from uo_init.host_ir import FuncSummary

    class _Host:
        backend = "clang"
        summaries = {
            "CheckShapeValid": FuncSummary(
                name="CheckShapeValid",
                file="op_host/arch35/flash_attention_score_grad_tiling.cpp",
                line=120,
            )
        }
        writes = []
        call_sites = []
        controls = []

    cm = CodeMap.from_host_ir(_Host(), op_name="toy", architecture="arch35")
    fns = [e for e in cm.by_kind(EntityKind.FUNCTION) if e.name == "CheckShapeValid"]
    assert len(fns) == 1
    assert fns[0].file.endswith("flash_attention_score_grad_tiling.cpp")
    assert fns[0].line_start == 120
