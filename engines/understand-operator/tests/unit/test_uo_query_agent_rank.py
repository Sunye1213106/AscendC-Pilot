# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import Entity, EntityKind
from uo_init.ir.relation import RelationKind
from uo_init.store.writer import write_codemap
from uo_init.uo_query import open_query


def _product(cm: CodeMap, tmp_path: Path) -> Path:
    product = tmp_path / ".ascendc-pilot" / "arch35" / "uo" / "toy.arch35.uo"
    product.parent.mkdir(parents=True, exist_ok=True)
    write_codemap(cm, product)
    return product


def _write_src(tmp_path: Path, rel: str, body: str) -> str:
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return rel.replace("\\", "/")


def test_field_does_not_match_json_mention(tmp_path: Path) -> None:
    cm = CodeMap(op_name="toy", architecture="arch35")
    cm.add_entity(
        Entity(
            id="TDF_block",
            kind=EntityKind.TILING_FIELD,
            name="blockOuter",
            attrs={
                "owner": "SplitParams",
                "value_defining_sites": [
                    {"guards": [{"condition": "fBaseParams.isBn2MultiBlk"}]}
                ],
            },
            file="op_kernel/td.h",
            line_start=10,
            status="confirmed",
        )
    )
    cm.add_entity(
        Entity(
            id="FLD_bn2",
            kind=EntityKind.FIELD,
            name="fBaseParams.isBn2MultiBlk",
            attrs={"layer": "host", "rhs": "!hasRope"},
            file="op_host/tiling.cpp",
            line_start=20,
            status="confirmed",
        )
    )
    _product(cm, tmp_path)
    q = open_query(tmp_path)
    hit = q.field_impact("isBn2MultiBlk")
    assert hit["ok"] is True
    assert hit["field"]["name"] == "fBaseParams.isBn2MultiBlk"
    assert hit["field"]["kind"] == "FIELD"


def test_field_falls_back_to_tiling_key(tmp_path: Path) -> None:
    cm = CodeMap(op_name="toy", architecture="arch35")
    cm.add_entity(
        Entity(
            id="TK_dne",
            kind=EntityKind.TILING_KEY,
            name="IsDNoEqual",
            attrs={
                "packing_value_sites": [
                    {
                        "file": "op_host/tiling.cpp",
                        "line": 1439,
                        "rhs": "(d1 != d) || hasRope",
                    }
                ]
            },
            file="op_kernel/key.h",
            line_start=105,
            status="confirmed",
        )
    )
    _product(cm, tmp_path)
    q = open_query(tmp_path)
    hit = q.field_impact("IsDNoEqual")
    assert hit["ok"] is True
    assert hit["field"]["kind"] == "TILING_KEY"
    assert hit["field"]["name"] == "IsDNoEqual"


def test_type_search_drops_hash_when_srctype_exists(tmp_path: Path) -> None:
    cm = CodeMap(op_name="toy", architecture="arch35")
    cm.add_entity(
        Entity(
            id="SRCTYPE::mutex_buffer.h::MutexBuffer",
            kind=EntityKind.TYPE,
            name="MutexBuffer",
            attrs={"cpp_kind": "class", "role": "storage_wrapper_type"},
            file="op_kernel/mutex_buffer.h",
            line_start=52,
            status="confirmed",
        )
    )
    cm.add_entity(
        Entity(
            id="TYPE_DEADBEEF",
            kind=EntityKind.TYPE,
            name="MutexBuffer",
            attrs={"role": "storage_wrapper_type"},
            file="op_kernel/mutex_buffer.h",
            line_start=146,
            status="extracted",
        )
    )
    _product(cm, tmp_path)
    q = open_query(tmp_path)
    rows = q.search("MutexBuffer", kinds=["TYPE"])
    assert [row["id"] for row in rows] == ["SRCTYPE::mutex_buffer.h::MutexBuffer"]


def test_method_search_prefers_qualified_definition(tmp_path: Path) -> None:
    cm = CodeMap(op_name="toy", architecture="arch35")
    cm.add_entity(
        Entity(
            id="MTH_call",
            kind=EntityKind.METHOD,
            name="MutexBuffer",
            file="op_kernel/block_cube.h",
            line_start=470,
            status="extracted",
        )
    )
    cm.add_entity(
        Entity(
            id="SRCKDEF::mutex_buffer.h::MutexBuffer::Init",
            kind=EntityKind.METHOD,
            name="MutexBuffer::Init",
            file="op_kernel/mutex_buffer.h",
            line_start=68,
            status="extracted",
        )
    )
    _product(cm, tmp_path)
    q = open_query(tmp_path)
    rows = q.search("MutexBuffer", kinds=["METHOD"])
    assert rows[0]["name"] == "MutexBuffer::Init"
    assert int(rows[0]["line_start"] or 0) == 68


def test_snippet_covers_hit_line_when_span_is_thin(tmp_path: Path) -> None:
    rel = "op_kernel/kernel_base.h"
    lines = [f"line {i}" for i in range(1, 80)]
    lines[21] = "    // before"
    lines[22] = "    if constexpr (IS_ROPE) {"
    lines[23] = "        constInfo.s1Dr = s1 * dRopeSize;"
    lines[24] = "    }"
    _write_src(tmp_path, rel, "\n".join(lines) + "\n")
    cm = CodeMap(op_name="toy", architecture="arch35")
    cm.add_entity(
        Entity(
            id="KBR",
            kind=EntityKind.BRANCH,
            name="IS_ROPE",
            attrs={"condition": "IS_ROPE", "function": "SetConstInfo", "layer": "kernel"},
            file=rel,
            line_start=23,
            line_end=23,
            status="confirmed",
        )
    )
    _product(cm, tmp_path)
    q = open_query(tmp_path)
    out = q.aggregate_kernel_branch("IS_ROPE")
    snip = str(out["branches"][0].get("snippet") or "")
    assert "23:" in snip
    assert "s1Dr" in snip


def test_kernel_branch_one_exemplar_per_function(tmp_path: Path) -> None:
    rel = "op_kernel/block.h"
    body = "\n".join(f"line {i}" for i in range(1, 40)) + "\n"
    _write_src(tmp_path, rel, body)
    cm = CodeMap(op_name="toy", architecture="arch35")
    for i, (fn, line) in enumerate(
        (("InitCubeBuffer", 10), ("SetConstInfo", 20), ("DqkvMulsAndCastFromGM", 30)),
        start=1,
    ):
        cm.add_entity(
            Entity(
                id=f"KBR_{i}",
                kind=EntityKind.BRANCH,
                name="IS_ROPE",
                attrs={"condition": "IS_ROPE", "function": fn, "layer": "kernel"},
                file=rel,
                line_start=line,
                line_end=line,
                status="confirmed",
            )
        )
        cm.add_entity(
            Entity(
                id=f"KBR_{i}b",
                kind=EntityKind.BRANCH,
                name="IS_ROPE",
                attrs={"condition": "IS_ROPE", "function": fn, "layer": "kernel"},
                file=rel,
                line_start=line + 1,
                line_end=line + 1,
                status="confirmed",
            )
        )
    _product(cm, tmp_path)
    q = open_query(tmp_path)
    out = q.aggregate_kernel_branch("IS_ROPE", limit=8)
    assert out["count"] == 6
    assert out["functions"] == {
        "InitCubeBuffer": 2,
        "SetConstInfo": 2,
        "DqkvMulsAndCastFromGM": 2,
    }
    fns = [
        (hit.get("facts") or {}).get("function") for hit in out["branches"]
    ]
    assert fns == ["InitCubeBuffer", "SetConstInfo", "DqkvMulsAndCastFromGM"]
    files = out["files"][rel]
    assert "snippet" not in files[0]
    assert files[0]["line"]
    narrowed = q.aggregate_kernel_branch("IS_ROPE SetConstInfo")
    assert narrowed["count"] == 2
    assert list(narrowed["functions"]) == ["SetConstInfo"]
    assert len(narrowed["branches"]) == 2


def test_packing_sites_rank_formula_first(tmp_path: Path) -> None:
    rel = "op_host/tiling.cpp"
    body = "\n".join(
        [
            "struct T {",
            "    bool hasRope = false;",
            "};",
            "void GetShapeAttrsInfo() {",
            "    bool hasQueryRope = true;",
            "    bool hasKeyRope = true;",
            "    fBaseParams.hasRope = hasQueryRope && hasKeyRope;",
            "}",
            "",
        ]
    )
    _write_src(tmp_path, rel, body)
    cm = CodeMap(op_name="toy", architecture="arch35")
    cm.add_entity(
        Entity(
            id="TK",
            kind=EntityKind.TILING_KEY,
            name="IsRope",
            attrs={
                "bit_lo": 48,
                "bit_hi": 48,
                "value_domain": ["0", "1"],
                "packing_value_sites": [
                    {"file": rel, "line": 2, "rhs": "false"},
                    {
                        "file": rel,
                        "line": 7,
                        "rhs": "hasQueryRope && hasKeyRope",
                        "function": "GetShapeAttrsInfo",
                    },
                ],
            },
            file="op_kernel/key.h",
            line_start=10,
            status="confirmed",
        )
    )
    _product(cm, tmp_path)
    q = open_query(tmp_path)
    out = q.aggregate_tiling_key("IsRope")
    sites = (out["keys"][0].get("facts") or {}).get("packing_value_sites") or []
    assert str(sites[0].get("rhs") or "").find("hasQueryRope") >= 0
    assert str(sites[0].get("function") or "") == "GetShapeAttrsInfo"
    snip = str(out["keys"][0].get("snippet") or "")
    assert "hasQueryRope && hasKeyRope" in snip
    assert "7:" in snip


def test_field_primary_prefers_formula_and_writer_candidates(tmp_path: Path) -> None:
    rel = "op_host/tiling.cpp"
    lines = [f"line {i}" for i in range(1, 30)]
    lines[4] = "    this.fBaseParams.isBn2MultiBlk = false;"
    lines[11] = (
        "    this.fBaseParams.isBn2MultiBlk = bnSparseLimit && s1Inner >= 128 && !hasRope;"
    )
    _write_src(tmp_path, rel, "\n".join(lines) + "\n")
    cm = CodeMap(op_name="toy", architecture="arch35")
    field = Entity(
        id="FLD_bn2",
        kind=EntityKind.FIELD,
        name="fBaseParams.isBn2MultiBlk",
        attrs={"layer": "host", "rhs": "false"},
        file=rel,
        line_start=5,
        status="confirmed",
    )
    writer_false = Entity(
        id="MTH_sparse",
        kind=EntityKind.METHOD,
        name="DoSparse",
        file=rel,
        line_start=5,
        status="extracted",
    )
    writer_real = Entity(
        id="MTH_split",
        kind=EntityKind.METHOD,
        name="SetSplitAxis",
        file=rel,
        line_start=12,
        status="extracted",
    )
    cm.add_entity(field)
    cm.add_entity(writer_false)
    cm.add_entity(writer_real)
    cm.link(RelationKind.WRITES, writer_false.id, field.id)
    cm.link(RelationKind.WRITES, writer_real.id, field.id)
    _product(cm, tmp_path)
    q = open_query(tmp_path)
    hit = q.field_impact("isBn2MultiBlk")
    assert hit["ok"] is True
    rhs = str((hit["field"].get("facts") or {}).get("rhs") or "")
    assert "hasRope" in rhs
    assert "!hasRope" in rhs or "hasRope" in rhs
    cands = hit.get("candidates") or []
    assert 1 <= len(cands) <= 3
    assert any("hasRope" in str((c.get("facts") or {}).get("rhs") or "") for c in cands)
    assert "hasRope" in str(cands[0].get("snippet") or "")


def test_kernel_branch_ranks_rich_bodies_and_caps_candidates(tmp_path: Path) -> None:
    rel = "op_kernel/kernel.h"
    lines = [f"    // pad {i}" for i in range(1, 90)]
    lines[9] = "    if constexpr (IS_ROPE) { return GetKeyOffset(); }"
    lines[19] = "    if constexpr (IS_ROPE) {"
    lines[20] = "        runInfo.queryOffsetWithRope = GetQueryOffset<false>(runInfo);"
    lines[21] = "    }"
    lines[39] = "    if constexpr (IS_D_NO_EQUAL) {"
    lines[40] = "        if constexpr (IS_ROPE) {"
    lines[41] = "            constInfo.s1Dr = s1 * dRopeSize;"
    lines[42] = "            constInfo.s2Dr = s2 * dRopeSize;"
    lines[43] = "        }"
    lines[44] = "    }"
    lines[59] = "        if constexpr (IS_ROPE) {"
    lines[60] = "            DataCopyPad(dst, src, params);"
    lines[61] = "            params.blockLen = dSizeV;"
    lines[62] = "        }"
    lines[69] = "        if constexpr (IS_ROPE) {"
    lines[70] = "            constInfo.mm2Ka = constInfo.mm2Ka / 3 << 1;"
    lines[71] = "        }"
    _write_src(tmp_path, rel, "\n".join(lines) + "\n")
    cm = CodeMap(op_name="toy", architecture="arch35")
    specs = (
        ("GetKeyOffset", 10),
        ("SetRunInfo", 20),
        ("SetConstInfo", 41),
        ("DqkvMulsAndCastFromGM", 60),
        ("SetConstInfo", 70),
    )
    for i, (fn, line) in enumerate(specs, start=1):
        cm.add_entity(
            Entity(
                id=f"KBR_{i}",
                kind=EntityKind.BRANCH,
                name="IS_ROPE",
                attrs={"condition": "IS_ROPE", "function": fn, "layer": "kernel"},
                file=rel,
                line_start=line,
                line_end=line,
                status="confirmed",
            )
        )
    _product(cm, tmp_path)
    q = open_query(tmp_path)
    out = q.aggregate_kernel_branch("IS_ROPE", limit=8)
    fns = [(hit.get("facts") or {}).get("function") for hit in out["branches"]]
    assert out["count"] == 5
    assert set(out["functions"]) == {fn for fn, _ in specs}
    assert len(fns) == 3
    assert fns[0] != "GetKeyOffset"
    assert "SetConstInfo" in fns
    assert "DqkvMulsAndCastFromGM" in fns
    first_snip = str(out["branches"][0].get("snippet") or "")
    assert "DataCopyPad" in first_snip or "s1Dr" in first_snip
    narrowed = q.aggregate_kernel_branch("IS_ROPE SetConstInfo")
    assert str(narrowed["branches"][0].get("snippet") or "").find("s1Dr") >= 0


def test_branch_window_includes_outer_constexpr(tmp_path: Path) -> None:
    rel = "op_kernel/kernel_base.h"
    lines = [f"line {i}" for i in range(1, 80)]
    lines[21] = "    if constexpr (IS_D_NO_EQUAL) {"
    lines[22] = "        // inner"
    lines[32] = "        if constexpr (IS_ROPE) {"
    lines[33] = "            constInfo.s1Dr = s1 * dRopeSize;"
    lines[34] = "        }"
    _write_src(tmp_path, rel, "\n".join(lines) + "\n")
    cm = CodeMap(op_name="toy", architecture="arch35")
    cm.add_entity(
        Entity(
            id="KBR",
            kind=EntityKind.BRANCH,
            name="IS_ROPE",
            attrs={"condition": "IS_ROPE", "function": "SetConstInfo", "layer": "kernel"},
            file=rel,
            line_start=33,
            line_end=33,
            status="confirmed",
        )
    )
    _product(cm, tmp_path)
    q = open_query(tmp_path)
    out = q.aggregate_kernel_branch("IS_ROPE")
    snip = str(out["branches"][0].get("snippet") or "")
    assert "IS_D_NO_EQUAL" in snip
    assert "s1Dr" in snip
    assert "33:" in snip


def test_tiling_key_payload_is_compact(tmp_path: Path) -> None:
    cm = CodeMap(op_name="toy", architecture="arch35")
    key = Entity(
        id="TK",
        kind=EntityKind.TILING_KEY,
        name="IsRope",
        attrs={"bit_lo": 48, "bit_hi": 48, "value_domain": ["0", "1"]},
        file="op_kernel/key.h",
        line_start=10,
        status="confirmed",
    )
    tpl = Entity(
        id="TPL_0",
        kind=EntityKind.TEMPLATE,
        name="ARGS_SEL_0",
        file="op_kernel/key.h",
        line_start=20,
        status="confirmed",
    )
    cm.add_entity(key)
    cm.add_entity(tpl)
    cm.link(RelationKind.BINDS, tpl.id, key.id)
    _product(cm, tmp_path)
    q = open_query(tmp_path)
    out = q.aggregate_tiling_key("IsRope")
    rels = out["keys"][0].get("relationships") or []
    assert not any(
        str(rel.get("other_name") or "").startswith("ARGS_SEL")
        or str(rel.get("other_kind") or "") == "TEMPLATE"
        for rel in rels
    )
    indexed = out["files"]["op_kernel/key.h"][0]
    assert "snippet" not in indexed
    assert indexed["name"] == "IsRope"
    assert indexed["line"] == 10


def test_collapse_duplicate_type_hashes_rewrites_wraps() -> None:
    from uo_init.passes.kernel_root_trace import _collapse_duplicate_type_hashes

    cm = CodeMap(op_name="toy", architecture="arch35")
    src = Entity(
        id="SRCTYPE::mutex_buffer.h::MutexBuffer",
        kind=EntityKind.TYPE,
        name="MutexBuffer",
        attrs={"role": "storage_wrapper_type", "cpp_kind": "class"},
        file="op_kernel/mutex_buffer.h",
        line_start=52,
        status="confirmed",
    )
    hashed = Entity(
        id="TYPE_DEADBEEF",
        kind=EntityKind.TYPE,
        name="MutexBuffer",
        attrs={"role": "storage_wrapper_type"},
        file="op_kernel/mutex_buffer.h",
        line_start=146,
        status="extracted",
    )
    owner = Entity(
        id="SRCTYPE::block.h::Cube",
        kind=EntityKind.TYPE,
        name="Cube",
        file="op_kernel/block.h",
        line_start=10,
        status="confirmed",
    )
    buf = Entity(
        id="BUF_q",
        kind=EntityKind.BUFFER,
        name="local_q",
        file="op_kernel/block.h",
        line_start=12,
        status="confirmed",
    )
    cm.add_entity(src)
    cm.add_entity(hashed)
    cm.add_entity(owner)
    cm.add_entity(buf)
    cm.link(RelationKind.WRAPS, owner.id, hashed.id)
    _collapse_duplicate_type_hashes(cm)
    assert src.id in cm.entities
    assert hashed.id not in cm.entities
    assert buf.id in cm.entities
    wraps = [r for r in cm.relations.values() if r.kind_name() == RelationKind.WRAPS.value]
    assert any(r.src == owner.id and r.dst == src.id for r in wraps)


def test_search_ranks_kernel_entry_ahead_of_processvec(tmp_path: Path) -> None:
    cm = CodeMap(op_name="toy", architecture="arch35")
    cm.add_entity(
        Entity(
            id="FN_vec",
            kind=EntityKind.FUNCTION,
            name="ProcessVec",
            file="op_kernel/arch35/process_vec.h",
            line_start=10,
            status="extracted",
        )
    )
    cm.add_entity(
        Entity(
            id="K_entry",
            kind=EntityKind.KERNEL,
            name="Process",
            file="op_kernel/arch35/flash_attention_score_grad_apt.cpp",
            line_start=40,
            status="extracted",
        )
    )
    _product(cm, tmp_path)
    q = open_query(tmp_path)
    rows = q.search("Process", kinds=(), limit=8)
    assert rows
    assert rows[0]["kind"] == EntityKind.KERNEL.value
    assert str(rows[0]["file"]).endswith("_apt.cpp")


def test_search_diversifies_functions_by_file(tmp_path: Path) -> None:
    cm = CodeMap(op_name="toy", architecture="arch35")
    cm.add_entity(
        Entity(
            id="FN_a",
            kind=EntityKind.FUNCTION,
            name="HelperA",
            file="op_host/a.cpp",
            line_start=1,
            status="extracted",
        )
    )
    cm.add_entity(
        Entity(
            id="FN_b",
            kind=EntityKind.FUNCTION,
            name="HelperB",
            file="op_host/a.cpp",
            line_start=2,
            status="extracted",
        )
    )
    cm.add_entity(
        Entity(
            id="FN_c",
            kind=EntityKind.FUNCTION,
            name="HelperC",
            file="op_host/b.cpp",
            line_start=3,
            status="extracted",
        )
    )
    _product(cm, tmp_path)
    q = open_query(tmp_path)
    rows = q.search("Helper", kinds=("FUNCTION",), limit=2)
    files = {str(row.get("file") or "").replace("\\", "/") for row in rows}
    assert "op_host/a.cpp" in files
    assert "op_host/b.cpp" in files


def test_search_exact_ident_outranks_getter_and_vector_api(tmp_path: Path) -> None:
    cm = CodeMap(op_name="toy", architecture="arch35")
    cm.add_entity(
        Entity(
            id="FN_get",
            kind=EntityKind.FUNCTION,
            name="get_castBufferLen",
            file="op_host/tiling.cpp",
            line_start=10,
            status="extracted",
        )
    )
    cm.add_entity(
        Entity(
            id="OP_cast",
            kind=EntityKind.OPERATION,
            name="Cast",
            attrs={"callee": "Cast"},
            file="op_kernel/arch35/block_vec.h",
            line_start=20,
            status="extracted",
        )
    )
    cm.add_entity(
        Entity(
            id="OP_fused_vf",
            kind=EntityKind.OPERATION,
            name="FusedMulDstAdd",
            attrs={"callee": "FusedMulDstAdd"},
            file="op_kernel/vector_api/vf.h",
            line_start=30,
            status="extracted",
        )
    )
    cm.add_entity(
        Entity(
            id="VAR_fused",
            kind=EntityKind.VARIABLE,
            name="fusedOuter",
            file="op_host/arch35/tiling.cpp",
            line_start=40,
            status="extracted",
        )
    )
    _product(cm, tmp_path)
    q = open_query(tmp_path)
    cast_rows = q.search("Cast", limit=8)
    assert cast_rows
    assert str(cast_rows[0]["name"]) == "Cast"
    fused_rows = q.search("fused", limit=8)
    assert fused_rows
    assert str(fused_rows[0]["name"]) == "fusedOuter"
    assert "vector_api" not in str(fused_rows[0].get("file") or "").replace("\\", "/")


def test_locate_unique_macro_is_answerable(tmp_path: Path) -> None:
    cm = CodeMap(op_name="toy", architecture="arch35")
    cm.add_entity(
        Entity(
            id="MACRO_orig",
            kind=EntityKind.MACRO,
            name="ORIG_DTYPE_QUERY",
            file="op_kernel/arch35/template_tiling_key.h",
            line_start=10,
            status="confirmed",
        )
    )
    _product(cm, tmp_path)
    q = open_query(tmp_path)
    out = q.aggregate_locate("ORIG_DTYPE_QUERY")
    assert out["count"] == 1
    assert out["locations"][0]["kind"] == EntityKind.MACRO.value
    assert (out.get("coverage") or {}).get("answerable") is True


def test_kernel_runtime_if_field_is_branch(tmp_path: Path) -> None:
    from uo_init.passes.kernel_tiling_closure import enrich_kernel_field_branches

    root = tmp_path / "toy"
    kernel = root / "op_kernel" / "arch35"
    kernel.mkdir(parents=True)
    (root / "op_host" / "arch35").mkdir(parents=True)
    (kernel / "entry.h").write_text(
        "void InitConst() {\n"
        "  if (constInfo.enablePreSfmg) {\n"
        "    runPre();\n"
        "  }\n"
        "}\n",
        encoding="utf-8",
    )
    cm = CodeMap(op_name="toy", architecture="arch35")
    cm.add_entity(
        Entity(
            id="TF_pre",
            kind=EntityKind.TILING_FIELD,
            name="enablePreSfmg",
            file="op_host/td.h",
            line_start=1,
            status="confirmed",
        )
    )
    minted = enrich_kernel_field_branches(cm, root, architecture="arch35")
    assert minted >= 1
    names = [e.name for e in cm.by_kind(EntityKind.BRANCH)]
    assert "enablePreSfmg" in names
