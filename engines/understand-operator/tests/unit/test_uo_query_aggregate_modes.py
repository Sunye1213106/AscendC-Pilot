# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from uo_init.ids import named_id
from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import Entity, EntityKind
from uo_init.query.legal_key_cache import clear_legal_key_cache, query_legal_keys
from uo_init.store.reader import load_view_blob
from uo_init.store.writer import write_codemap
from uo_init.uo_query import open_query


def _add_tpl_key(
    cm: CodeMap,
    *,
    name: str,
    order: int,
    bw: int,
    domain: list[int | str],
    kind: str = "UINT",
) -> None:
    shift = sum(
        int(e.attrs.get("bit_width") or 0)
        for e in cm.by_kind(EntityKind.TILING_KEY)
        if e.attrs.get("source_declared")
    )
    cm.add_entity(
        Entity(
            id=f"TK_{name}",
            kind=EntityKind.TILING_KEY,
            name=name,
            attrs={
                "source_declared": True,
                "decl_order": order,
                "bit_width": bw,
                "bit_lo": shift,
                "bit_hi": shift + bw - 1,
                "value_domain": [str(v) for v in domain],
                "allowed_values": [str(v) for v in domain],
                "decl_kind": kind,
                "kind_tpl": kind,
                "provenance": "source_tpl_args_decl",
            },
            file="op_kernel/template_tiling_key.h",
            status="confirmed",
        )
    )


def _add_tpl_group(
    cm: CodeMap,
    *,
    index: int,
    fixed: dict[str, int | str],
    domains: dict[str, list[int | str]] | None = None,
) -> None:
    cm.add_entity(
        Entity(
            id=f"TPL_{index}",
            kind=EntityKind.TEMPLATE,
            name=f"ARGS_SEL_{index}",
            attrs={
                "tpl_role": "args_sel_group",
                "sel_group_index": index,
                "fixed_fields": {k: str(v) for k, v in fixed.items()},
                "field_domains": {
                    k: [str(v) for v in values]
                    for k, values in dict(domains or {}).items()
                },
                "provenance": "source_tpl_args_sel",
            },
            file="op_kernel/template_tiling_key.h",
            status="confirmed",
        )
    )


def test_legal_key_cache_uses_structured_index(tmp_path: Path) -> None:
    cm = CodeMap(op_name="toy", architecture="arch35")
    _add_tpl_key(cm, name="SplitAxis", order=0, bw=2, domain=[0, 1])
    _add_tpl_key(cm, name="IsTnd", order=1, bw=1, domain=[0, 1], kind="BOOL")
    _add_tpl_group(cm, index=0, fixed={"SplitAxis": 0, "IsTnd": 0})
    _add_tpl_group(cm, index=1, fixed={"SplitAxis": 1, "IsTnd": 1})
    _add_tpl_group(cm, index=2, fixed={"SplitAxis": 1, "IsTnd": 0})
    product = tmp_path / "toy.arch35.uo"
    write_codemap(cm, product)

    clear_legal_key_cache()
    first = query_legal_keys(product, dim="SplitAxis", value="1", limit=10)
    assert first["indexed"] is True
    assert first["total_matched"] == 2

    combined = query_legal_keys(product, pattern="SplitAxis=1,IsTnd=1", limit=10)
    assert combined["indexed"] is True
    assert combined["filters"] == {"SplitAxis": "1", "IsTnd": "1"}
    assert combined["total_matched"] == 1
    assert combined["rows"][0]["sel_group_id"] == named_id("TemplateBinding", "sel1")

    second = query_legal_keys(product, pattern="IsTnd=0", limit=10)
    assert second["cached"] is True
    assert second["indexed"] is True
    assert second["total_matched"] == 2


def test_writer_rebuilds_legal_key_view_instead_of_laundering_input(tmp_path: Path) -> None:
    cm = CodeMap(op_name="toy", architecture="arch35")
    _add_tpl_key(cm, name="SplitAxis", order=0, bw=2, domain=[0, 1])
    _add_tpl_group(cm, index=0, fixed={"SplitAxis": 1})
    product = tmp_path / "toy.arch35.uo"
    forged = {
        "schema": "uo-legal-key-index/v1",
        "rows": [{"key_id": "forged", "dims": {"SplitAxis": 99}}],
    }
    write_codemap(
        cm,
        product,
        views={"tiling/legal_key_index.jsonl": forged},
    )
    blob = load_view_blob(product, "tiling/legal_key_index.jsonl")
    assert isinstance(blob, dict)
    assert blob["provenance"]["canonical_graph_digest"]
    assert blob["count"] == 1
    assert blob["rows"][0]["dims"]["SplitAxis"] == "1"
    assert "key_id" not in blob["rows"][0]


def test_tiling_key_does_not_implicitly_enumerate_legal_keys(tmp_path: Path) -> None:
    cm = CodeMap(op_name="toy", architecture="arch35")
    _add_tpl_key(cm, name="SplitAxis", order=0, bw=3, domain=[0, 1, 5])
    key = cm.by_name("SplitAxis", kind=EntityKind.TILING_KEY)[0]
    key.attrs["packing_value_sites"] = [{"file": "op_host/x.cpp", "line": 10}]
    product = tmp_path / ".ascendc-pilot" / "arch35" / "uo" / "toy.arch35.uo"
    product.parent.mkdir(parents=True, exist_ok=True)
    write_codemap(cm, product)
    q = open_query(tmp_path)
    out = q.aggregate_tiling_key("SplitAxis")
    assert out["count"] == 1
    assert "legal_key_sample" not in out
    assert out["keys"][0]["name"] == "SplitAxis"


def test_template_match_filters_fixed_fields_and_domains(tmp_path: Path) -> None:
    cm = CodeMap(op_name="toy", architecture="arch35")
    _add_tpl_key(cm, name="SplitAxis", order=0, bw=2, domain=[0, 1])
    _add_tpl_key(cm, name="IsTnd", order=1, bw=1, domain=[0, 1], kind="BOOL")
    _add_tpl_key(cm, name="DTemplate", order=2, bw=3, domain=[64, 128, 256])
    _add_tpl_group(
        cm,
        index=20,
        fixed={"SplitAxis": 1, "IsTnd": 0},
        domains={"DTemplate": [64, 128]},
    )
    _add_tpl_group(
        cm,
        index=21,
        fixed={"SplitAxis": 1, "IsTnd": 1},
        domains={"DTemplate": [64, 128, 256]},
    )
    product = tmp_path / ".ascendc-pilot" / "arch35" / "uo" / "toy.arch35.uo"
    product.parent.mkdir(parents=True, exist_ok=True)
    write_codemap(cm, product)
    q = open_query(tmp_path)
    out = q.aggregate_template_match("SplitAxis=1,IsTnd=1,DTemplate=128")
    assert out["ok"] is True
    assert out["filters"] == {"SplitAxis": "1", "IsTnd": "1", "DTemplate": "128"}
    assert out["count"] == 1
    assert out["template_blocks"][0]["name"] == "ARGS_SEL_21"
    assert out["template_blocks"][0]["id"] == named_id("TemplateBinding", "sel21")
    assert out["matching_block_count"] == 1
    assert "128" in (out.get("dim_coverage") or {}).get("DTemplate", [])


def test_aggregate_modes(tmp_path: Path) -> None:
    cm = CodeMap(op_name="toy", architecture="arch35")
    cm.add_entity(
        Entity(
            id="TK",
            kind=EntityKind.TILING_KEY,
            name="SplitAxis",
            attrs={"source_declared": True, "decl_order": 0},
        )
    )
    cm.add_entity(
        Entity(id="BUF", kind=EntityKind.BUFFER, name="local_q", attrs={"scope": "main"})
    )
    cm.add_entity(
        Entity(id="U1", kind=EntityKind.OTHER, name="gap", attrs={}, status="unresolved")
    )
    product = tmp_path / ".ascendc-pilot" / "arch35" / "uo" / "toy.arch35.uo"
    product.parent.mkdir(parents=True, exist_ok=True)
    write_codemap(cm, product)
    q = open_query(tmp_path)
    assert q.aggregate_tiling_key("SplitAxis")["count"] >= 1
    assert q.aggregate_buffer("local")["count"] >= 1
    assert q.aggregate_gaps()["total"] >= 1


def test_type_search_is_exact_and_skips_info_manager(tmp_path: Path) -> None:
    cm = CodeMap(op_name="toy", architecture="arch35")
    cm.add_entity(
        Entity(
            id="SRCTYPE::mutex_buffer.h::MutexBuffer",
            kind=EntityKind.TYPE,
            name="MutexBuffer",
            attrs={"cpp_kind": "class", "role": "storage_wrapper_type", "root": "AscendC::LocalTensor"},
            file="mutex_buffer.h",
            line_start=52,
            line_end=52,
            status="confirmed",
        )
    )
    cm.add_entity(
        Entity(
            id="TYPE_INFO",
            kind=EntityKind.TYPE,
            name="MutexBufferInfo",
            attrs={"cpp_kind": "struct"},
            file="mutex_buffer.h",
            line_start=10,
            status="confirmed",
        )
    )
    cm.add_entity(
        Entity(
            id="TYPE_MGR",
            kind=EntityKind.TYPE,
            name="MutexBufferManager",
            attrs={"cpp_kind": "class"},
            file="mutex_buffer.h",
            line_start=80,
            status="confirmed",
        )
    )
    product = tmp_path / ".ascendc-pilot" / "arch35" / "uo" / "toy.arch35.uo"
    product.parent.mkdir(parents=True, exist_ok=True)
    write_codemap(cm, product)
    q = open_query(tmp_path)
    rows = q.search("MutexBuffer", kinds=["TYPE"])
    names = [str(row.get("name") or "") for row in rows]
    assert names == ["MutexBuffer"]
    assert rows[0]["file"].endswith("mutex_buffer.h")
    assert int(rows[0]["line_start"] or 0) == 52
    assert (rows[0].get("facts") or {}).get("role") == "storage_wrapper_type"
    buf = q.aggregate_buffer("MutexBuffer")
    assert buf["count"] >= 1
    assert any(row["name"] == "MutexBuffer" for row in buf["buffers"])


def test_template_match_dim_coverage_is_global_not_first_block(tmp_path: Path) -> None:
    cm = CodeMap(op_name="toy", architecture="arch35")
    _add_tpl_key(cm, name="DeterType", order=0, bw=2, domain=[0, 1])
    _add_tpl_key(cm, name="InputDType", order=1, bw=3, domain=[1, 2, 3])
    _add_tpl_key(cm, name="DTemplateNum", order=2, bw=4, domain=[64, 128, 192, 256, 768])
    _add_tpl_group(
        cm,
        index=0,
        fixed={"DeterType": 0, "InputDType": 3},
        domains={"DTemplateNum": [64, 192, 256, 768]},
    )
    _add_tpl_group(
        cm,
        index=1,
        fixed={"DeterType": 0, "InputDType": 3},
        domains={"DTemplateNum": [128]},
    )
    product = tmp_path / ".ascendc-pilot" / "arch35" / "uo" / "toy.arch35.uo"
    product.parent.mkdir(parents=True, exist_ok=True)
    write_codemap(cm, product)
    q = open_query(tmp_path)

    all_d = q.aggregate_template_match("DeterType=0,InputDType=3")
    assert all_d["matching_block_count"] == 2
    assert all_d["count"] == 2
    assert set(all_d["dim_coverage"]["DTemplateNum"]) == {"64", "128", "192", "256", "768"}

    hit = q.aggregate_template_match("DTemplateNum=128,DeterType=0,InputDType=3")
    assert hit["matching_block_count"] == 1
    assert "128" in hit["dim_coverage"]["DTemplateNum"]
    assert hit["template_blocks"][0]["name"] == "ARGS_SEL_1"

    miss = q.aggregate_template_match("DTemplateNum=80,DeterType=0,InputDType=3")
    assert miss["matching_block_count"] == 0
    nearby = {row["dropped"]: row for row in miss["nearby"]}
    assert "128" in nearby["DTemplateNum"]["values"]
    assert "64" in nearby["DTemplateNum"]["values"]

    keys = query_legal_keys(
        product, pattern="DTemplateNum=128,DeterType=0,InputDType=3", limit=8
    )
    assert keys["indexed"] is True
    assert keys["total_matched"] >= 1
    assert keys["sel_group_ids"]
    zero = query_legal_keys(
        product, pattern="DTemplateNum=80,DeterType=0,InputDType=3", limit=8
    )
    assert zero["total_matched"] == 0
    dropped = {row["dropped"]: row for row in zero["nearby"]}
    assert "128" in dropped["DTemplateNum"]["values"]


def test_locate_ors_tokens_and_regex_gets_hint(tmp_path: Path) -> None:
    cm = CodeMap(op_name="toy", architecture="arch35")
    cm.add_entity(
        Entity(
            id="FN_A",
            kind=EntityKind.FUNCTION,
            name="RegbaseFAG",
            file="op_kernel/flash_attention_score_grad_apt.cpp",
            line_start=40,
            status="confirmed",
        )
    )
    cm.add_entity(
        Entity(
            id="FN_B",
            kind=EntityKind.FUNCTION,
            name="CalcleTNDDeterParam",
            file="op_host/arch35/varlen.cpp",
            line_start=42,
            status="confirmed",
        )
    )
    product = tmp_path / ".ascendc-pilot" / "arch35" / "uo" / "toy.arch35.uo"
    product.parent.mkdir(parents=True, exist_ok=True)
    write_codemap(cm, product)
    q = open_query(tmp_path)
    both = q.aggregate_locate("REGISTER_TILING_DEFAULT RegbaseFAG")
    names = {str(row.get("name") or "") for row in both["locations"]}
    assert "RegbaseFAG" in names
    assert both["count"] >= 1
    assert "pattern_tokens" in both

    regex = q.aggregate_locate(r"DeterComputeDq\|DeterComputeDkv")
    assert regex["empty_reason"] == "pattern_looks_like_regex"
    assert regex["hint"]
    assert "DeterComputeDq" in regex["suggested_retries"]

    missing = q.aggregate_locate("NoSuchSymbolAtAll")
    assert missing["count"] == 0
    assert missing["empty_reason"] == "no_substring_match"


def test_locate_function_returns_all_definition_sites(tmp_path: Path) -> None:
    cm = CodeMap(op_name="toy", architecture="arch35")
    cm.upsert(
        EntityKind.FUNCTION,
        "CalcleTNDDeterParam",
        file="op_host/flash_attention_score_grad_tiling.h",
        line=80,
        status="extracted",
    )
    cm.upsert(
        EntityKind.FUNCTION,
        "CalcleTNDDeterParam",
        file="op_host/arch35/flash_attention_score_grad_tiling_varlen.cpp",
        line=412,
        status="extracted",
    )
    product = tmp_path / ".ascendc-pilot" / "arch35" / "uo" / "toy.arch35.uo"
    product.parent.mkdir(parents=True, exist_ok=True)
    write_codemap(cm, product)
    q = open_query(tmp_path)
    out = q.aggregate_locate("CalcleTNDDeterParam")
    files = {str(row.get("file") or "").replace("\\", "/") for row in out["locations"]}
    assert any(p.endswith("flash_attention_score_grad_tiling.h") for p in files)
    assert any("varlen.cpp" in p for p in files)
    assert out["count"] >= 2


def test_legal_key_unindexed_freetext_hint(tmp_path: Path) -> None:
    cm = CodeMap(op_name="toy", architecture="arch35")
    _add_tpl_key(cm, name="SplitAxis", order=0, bw=2, domain=[0, 1])
    _add_tpl_group(cm, index=0, fixed={"SplitAxis": 1})
    product = tmp_path / "toy.arch35.uo"
    write_codemap(cm, product)
    clear_legal_key_cache()
    out = query_legal_keys(product, pattern="not-a-dim-filter", limit=8)
    assert out["indexed"] is False
    assert "Dim=V" in (out.get("hint") or "")
