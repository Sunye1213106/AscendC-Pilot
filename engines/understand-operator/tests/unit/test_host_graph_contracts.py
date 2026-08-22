# -*- coding: utf-8 -*-
"""Toy-graph contracts for Host catalog, definition identity, and query identity.

Anonymous Host names only. Do not assert operator-specific identifiers.
"""
from __future__ import annotations

from pathlib import Path

from uo_init.host_ir import FuncSummary
from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import Entity, EntityKind
from uo_init.ir.relation import RelationKind
from uo_init.passes.host_graph_status import GRAPH_STATUS_CATALOG, HOST_GRAPH_PROVENANCE
from uo_init.query.sql import CARD_SNIPPET_MAX_LINES, SNIPPET_LINES
from uo_init.store.writer import write_codemap
from uo_init.uo_query import open_query


def _product(cm: CodeMap, tmp_path: Path) -> Path:
    product = tmp_path / ".ascendc-pilot" / "arch35" / "uo" / "toy.arch35.uo"
    product.parent.mkdir(parents=True, exist_ok=True)
    write_codemap(cm, product)
    return product


class _Write:
    def __init__(self, path, *, function="FnHost", file="op_host/h.cpp", line=18, rhs="x + 1"):
        self.path = path
        self.function = function
        self.file = file
        self.line = line
        self.rhs = rhs

    def guards(self):
        return []


class _Host:
    def __init__(
        self,
        *,
        summaries=None,
        writes=None,
        local_writes=None,
        call_sites=None,
        controls=None,
        premises=None,
    ):
        self.backend = "clang"
        self.summaries = summaries or {}
        self.writes = writes or []
        self.local_writes = local_writes or []
        self.call_sites = call_sites or []
        self.controls = controls or []
        self._premises = premises or []

    def legality_premises(self):
        return list(self._premises)


def _kernel_rooted_at(cm: CodeMap) -> int:
    return sum(
        1
        for rel in cm.relations.values()
        if rel.kind_name() == RelationKind.ROOTED_AT.value
        and str(rel.attrs.get("provenance") or "") == "kernel_root_trace"
    )


def test_graph_status_roots_from_named_and_forwarded_refuse() -> None:
    host = _Host(
        summaries={
            "FnRefuse": FuncSummary(
                name="FnRefuse",
                file="op_host/h.cpp",
                line=10,
                line_end=40,
                returns=["GRAPH_FAILED"],
            ),
            "FnFwd": FuncSummary(
                name="FnFwd",
                file="op_host/h.cpp",
                line=50,
                line_end=80,
                returns=["ret"],
            ),
        },
        premises=[
            ("condA", "FnRefuse", "op_host/h.cpp", 15),
            ("ret != GRAPH_SUCCESS", "FnFwd", "op_host/h.cpp", 55),
        ],
    )
    cm = CodeMap.from_host_ir(host, op_name="toy", architecture="arch35")
    roots = [
        e
        for e in cm.by_kind(EntityKind.TYPE)
        if str(e.attrs.get("catalog") or "") == GRAPH_STATUS_CATALOG
    ]
    names = {e.name for e in roots}
    assert "GRAPH_FAILED" in names
    failed = next(e for e in roots if e.name == "GRAPH_FAILED")
    assert failed.attrs.get("role") == "host_refuse"
    incoming = [
        rel
        for rel in cm.relations.values()
        if rel.dst == failed.id and rel.kind_name() in {RelationKind.RETURNS.value, RelationKind.ROOTED_AT.value}
    ]
    assert incoming
    assert all(str(rel.attrs.get("provenance") or "") == HOST_GRAPH_PROVENANCE for rel in incoming)
    assert _kernel_rooted_at(cm) == 0


def test_write_site_does_not_shrink_definition_span() -> None:
    host = _Host(
        summaries={
            "FnBody": FuncSummary(
                name="FnBody",
                file="op_host/h.cpp",
                line=10,
                line_end=40,
            )
        },
        writes=[_Write("owner.fldLeaf", function="FnBody", line=25, rhs="1")],
    )
    cm = CodeMap.from_host_ir(host, op_name="toy", architecture="arch35")
    fn = cm.by_name("FnBody", kind=EntityKind.FUNCTION)[0]
    assert fn.line_start == 10
    assert fn.line_end == 40
    field = cm.by_name("owner.fldLeaf", kind=EntityKind.FIELD)[0]
    sites = field.attrs.get("write_sites") or []
    assert any(int(site.get("line") or 0) == 25 for site in sites if isinstance(site, dict))


def test_local_write_lands_on_assignment_not_use() -> None:
    host = _Host(
        summaries={"FnPack": FuncSummary(name="FnPack", file="op_host/h.cpp", line=8, line_end=30)},
        local_writes=[_Write("splitAxis", function="FnPack", line=18, rhs="coreIdx + 1")],
    )
    cm = CodeMap.from_host_ir(host, op_name="toy", architecture="arch35")
    var = cm.by_name("splitAxis", kind=EntityKind.VARIABLE)[0]
    assert var.line_start == 18
    sites = var.attrs.get("write_sites") or []
    assert any(int(site.get("line") or 0) == 18 for site in sites if isinstance(site, dict))


def test_definition_card_uses_recorded_span_window(tmp_path: Path) -> None:
    rel = "op_host/h.cpp"
    lines = [f"    stmt_{i}();" for i in range(1, 28)]
    lines[1] = "void FnWide() {"
    lines[21] = "}"
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    cm = CodeMap(op_name="toy", architecture="arch35")
    cm.add_entity(
        Entity(
            id="FN_wide",
            kind=EntityKind.FUNCTION,
            name="FnWide",
            attrs={"layer": "host"},
            file=rel,
            line_start=2,
            line_end=22,
            status="confirmed",
        )
    )
    cm.add_entity(
        Entity(
            id="BR_one",
            kind=EntityKind.BRANCH,
            name="flagA",
            attrs={"predicate": "flagA", "layer": "host"},
            file=rel,
            line_start=6,
            line_end=6,
            status="confirmed",
        )
    )
    _product(cm, tmp_path)
    q = open_query(tmp_path, architecture="arch35")
    card = next(row for row in (q.agent_query(pattern="FnWide").get("cards") or []) if row.get("kind") == "FUNCTION")
    snip_lines = [ln for ln in str(card.get("snippet") or "").splitlines() if ln.strip()]
    assert len(snip_lines) >= 20
    assert len(snip_lines) <= SNIPPET_LINES
    span = card.get("definition_span") or {}
    assert int(span.get("line_end") or 0) == 22
    branch = next(row for row in (q.agent_query(pattern="flagA").get("cards") or []) if row.get("kind") == "BRANCH")
    br_lines = [ln for ln in str(branch.get("snippet") or "").splitlines() if ln.strip()]
    assert len(br_lines) <= CARD_SNIPPET_MAX_LINES


def test_around_seed_is_enclosing_definition(tmp_path: Path) -> None:
    rel = "op_host/h.cpp"
    body = "\n".join(f"line {i}" for i in range(1, 50)) + "\n"
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    cm = CodeMap(op_name="toy", architecture="arch35")
    fn = cm.upsert(
        EntityKind.FUNCTION,
        "FnEnclose",
        eid="FN_enclose",
        attrs={"layer": "host"},
        file=rel,
        line=10,
        line_end=40,
        status="confirmed",
    )
    field = cm.upsert(
        EntityKind.FIELD,
        "owner.fldInner",
        eid="FLD_inner",
        attrs={"layer": "host"},
        file=rel,
        line=20,
        status="confirmed",
    )
    cm.link(RelationKind.WRITES, fn.id, field.id, attrs={"file": rel, "line": 20})
    _product(cm, tmp_path)
    q = open_query(tmp_path, architecture="arch35")
    out = q.agent_query(file=rel, line=20)
    seeds = list(out.get("seeds") or [])
    assert seeds
    assert str(seeds[0].get("name") or "") == "FnEnclose"
    assert str(seeds[0].get("kind") or "") == "FUNCTION"


def test_empty_cover_is_coverage_checked_with_nearby(tmp_path: Path) -> None:
    cm = CodeMap(op_name="toy", architecture="arch35")
    cm.add_entity(
        Entity(
            id="TK_alpha",
            kind=EntityKind.TILING_KEY,
            name="DimAlpha",
            attrs={
                "source_declared": True,
                "decl_order": 0,
                "bit_width": 1,
                "bit_lo": 0,
                "bit_hi": 0,
                "value_domain": ["0", "1"],
                "allowed_values": ["0", "1"],
                "decl_kind": "UINT",
                "kind_tpl": "UINT",
                "provenance": "source_tpl_args_decl",
            },
            file="op_kernel/template_tiling_key.h",
            status="confirmed",
        )
    )
    cm.add_entity(
        Entity(
            id="TPL_0",
            kind=EntityKind.TEMPLATE,
            name="ARGS_SEL_0",
            attrs={
                "tpl_role": "args_sel_group",
                "sel_group_index": 0,
                "fixed_fields": {"DimAlpha": "0"},
                "field_domains": {},
                "provenance": "source_tpl_args_sel",
            },
            file="op_kernel/template_tiling_key.h",
            status="confirmed",
        )
    )
    _product(cm, tmp_path)
    q = open_query(tmp_path, architecture="arch35")
    out = q.agent_query(pattern="DimAlpha=1")
    assert int(out.get("matching_block_count") or 0) == 0
    assert out.get("completeness") == "coverage_checked"
    cov = out.get("coverage") or {}
    assert cov.get("completeness") == "coverage_checked"
    nearby = cov.get("nearby") or out.get("nearby") or []
    assert nearby
    assert any(str(row.get("dropped") or "") == "DimAlpha" for row in nearby if isinstance(row, dict))


def test_leaf_name_hits_owner_prefixed_write(tmp_path: Path) -> None:
    cm = CodeMap(op_name="toy", architecture="arch35")
    field = cm.upsert(
        EntityKind.FIELD,
        "this.owner.leaf",
        eid="FLD_leaf",
        attrs={
            "layer": "host",
            "rhs": "true",
            "write_sites": [{"file": "op_host/h.cpp", "line": 95, "rhs": "true"}],
        },
        file="op_host/h.cpp",
        line=95,
        status="confirmed",
    )
    cm.add_entity(
        Entity(
            id="BR_other",
            kind=EntityKind.BRANCH,
            name="leaf",
            attrs={"predicate": "leaf", "layer": "kernel"},
            status="extracted",
        )
    )
    cm.link(RelationKind.WRITES, "FN_dummy", field.id)
    _product(cm, tmp_path)
    q = open_query(tmp_path, architecture="arch35")
    out = q.agent_query(pattern="leaf")
    cards = list(out.get("cards") or [])
    hit = next((row for row in cards if str(row.get("kind") or "") == "FIELD"), None)
    assert hit is not None
    assert str(hit.get("name") or "") == "this.owner.leaf"
    assert int(hit.get("line") or 0) == 95


def test_same_file_formula_derives_outranks_input(tmp_path: Path) -> None:
    cm = CodeMap(op_name="toy", architecture="arch35")
    target = cm.upsert(
        EntityKind.FIELD,
        "owner.encoded",
        eid="FLD_enc",
        attrs={"layer": "host"},
        file="op_host/h.cpp",
        line=40,
        status="confirmed",
    )
    formula = cm.upsert(
        EntityKind.PREDICATE,
        "(d1!=d)||flagX",
        eid="PRED_formula",
        attrs={"layer": "host"},
        file="op_host/h.cpp",
        line=38,
        status="confirmed",
    )
    inp = cm.upsert(EntityKind.INPUT, "IN_QUERY", eid="IN_query", attrs={"api_kind": "tensor"})
    cm.link(
        RelationKind.DERIVES,
        formula.id,
        target.id,
        attrs={"file": "op_host/h.cpp", "line": 38, "rhs": "(d1!=d)||flagX", "expression": "(d1!=d)||flagX"},
        status="confirmed",
    )
    cm.link(RelationKind.DERIVES, inp.id, target.id, attrs={"provenance": "name_bind"}, status="extracted")
    _product(cm, tmp_path)
    q = open_query(tmp_path, architecture="arch35")
    card = next(
        row
        for row in (q.agent_query(pattern="encoded").get("cards") or [])
        if str(row.get("kind") or "") == "FIELD"
    )
    neigh = list(((card.get("edges") or {}).get("DERIVES") or {}).get("neighbors") or [])
    assert neigh
    assert str(neigh[0].get("kind") or "") != "INPUT"
    assert "(d1!=d)||flagX" in str(neigh[0].get("name") or "")


def test_status_identifier_returns_catalog_root(tmp_path: Path) -> None:
    host = _Host(
        summaries={
            "FnRefuse": FuncSummary(
                name="FnRefuse",
                file="op_host/h.cpp",
                line=10,
                line_end=20,
                returns=["GRAPH_FAILED"],
            )
        },
        premises=[("condA", "FnRefuse", "op_host/h.cpp", 12)],
    )
    cm = CodeMap.from_host_ir(host, op_name="toy", architecture="arch35")
    cm.add_entity(
        Entity(
            id="TYPE_lt",
            kind=EntityKind.TYPE,
            name="AscendC::LocalTensor",
            attrs={"catalog": "ascendc", "spelling": "LocalTensor", "root": "AscendC::LocalTensor"},
            status="extracted",
        )
    )
    cm.add_entity(
        Entity(
            id="MTH_ltb",
            kind=EntityKind.METHOD,
            name="LocalTensorBufferBase",
            file="op_kernel/buf.hpp",
            line_start=30,
            line_end=40,
            status="extracted",
        )
    )
    _product(cm, tmp_path)
    q = open_query(tmp_path, architecture="arch35")
    failed = q.agent_query(pattern="GRAPH_FAILED")
    assert failed.get("ok") is True
    type_card = next((row for row in (failed.get("cards") or []) if row.get("kind") == "TYPE"), None)
    assert type_card is not None
    extras = type_card.get("extras") or {}
    facts_catalog = extras.get("catalog") or type_card.get("catalog") or ""
    assert facts_catalog == GRAPH_STATUS_CATALOG
    assert (type_card.get("role") or extras.get("role")) == "host_refuse"
    span = type_card.get("definition_span") or {}
    assert str(span.get("file") or type_card.get("file") or "").replace("\\", "/").endswith(
        "op_host/h.cpp"
    )
    assert int(span.get("line_start") or type_card.get("line") or 0) == 10
    writers = extras.get("writers") or []
    assert writers
    assert int(writers[0].get("line") or 0) == 10
    catalog_empty = q.agent_query(pattern="LocalTensor")
    assert catalog_empty.get("ok") is False
    assert not (catalog_empty.get("cards") or [])
