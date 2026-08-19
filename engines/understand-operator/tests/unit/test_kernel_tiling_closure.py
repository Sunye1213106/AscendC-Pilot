from __future__ import annotations

from pathlib import Path

from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import EntityKind
from uo_init.ir.relation import RelationKind
from uo_init.ir.type_identity import macro_type_aliases
from uo_init.passes.kernel_tiling_closure import finalize_kernel_tiling_closure
from uo_init.passes.tiling_host_writes import enrich_tiling_host_writes


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "toy"
    (root / "op_kernel" / "arch35").mkdir(parents=True)
    (root / "op_host" / "arch35").mkdir(parents=True)
    return root


def _base_cm() -> CodeMap:
    cm = CodeMap(op_name="toy", architecture="arch35")
    cm.upsert(EntityKind.INPUT, "q", attrs={"api_kind": "tensor", "api_index": 0})
    cm.upsert(EntityKind.OUTPUT, "out", attrs={"api_index": 0})
    cm.upsert(EntityKind.TILING_KEY, "A", attrs={"source_declared": True, "decl_order": 0})
    cm.upsert(EntityKind.TILING_KEY, "B", attrs={"source_declared": True, "decl_order": 1})
    return cm


def test_object_macro_aliases_only_when_type_is_unique() -> None:
    known = {"OuterTiling", "OtherTiling"}
    text = (
        "#define FagTilingType \\\n"
        "    const __gm__ OuterTiling<A, B> *__restrict\n"
        "#define Mixed OuterTiling OtherTiling\n"
        "#define FOO(x) OuterTiling\n"
    )
    got = macro_type_aliases(text, known)
    assert got["FagTilingType"] == {"OuterTiling"}
    assert "Mixed" not in got
    assert "FOO" not in got


def test_selected_arch_rebuilds_template_abi_and_drops_foreign_top_level(tmp_path: Path) -> None:
    root = _root(tmp_path)
    (root / "op_kernel" / "toy_apt.cpp").write_text(
        '''
        #include "arch35/entry.h"
        template <bool A, bool B>
        __global__ __aicore__ void toy_kernel(
            __gm__ uint8_t *q, __gm__ uint8_t *out,
            __gm__ uint8_t *workspace, __gm__ uint8_t *tiling_data) {
          RegbaseFAG<A, B>(q, out, tiling_data);
        }
        ''',
        encoding="utf-8",
    )
    (root / "op_kernel" / "old.cpp").write_text(
        '''
        #include "arch22/entry.h"
        template <bool X, bool Y, bool Z>
        __global__ __aicore__ void toy_kernel(__gm__ uint8_t *q) { OldOnly(q); }
        ''',
        encoding="utf-8",
    )
    (root / "op_kernel" / "arch35" / "entry.h").write_text(
        '''
        template <bool A, bool B>
        inline __aicore__ void
        RegbaseFAG(__gm__ uint8_t *q, __gm__ uint8_t *out, __gm__ uint8_t *tiling_data) {
          Helper(q);
        }
        inline __aicore__ void Helper(__gm__ uint8_t *q) { (void)q; }
        ''',
        encoding="utf-8",
    )

    cm = _base_cm()
    kernel = cm.upsert(
        EntityKind.KERNEL,
        "toy_kernel",
        attrs={"provenance": "source_kernel_signature"},
        file="toy/op_kernel/old.cpp",
    )
    stale = cm.upsert(
        EntityKind.METHOD,
        "OldOnly",
        eid="stale-old-call",
        attrs={"provenance": "source_call_site"},
        file="toy/op_kernel/old.cpp",
    )
    cm.link(
        RelationKind.CALLS,
        kernel.id,
        stale.id,
        attrs={"provenance": "source_call_site", "file": "toy/op_kernel/old.cpp"},
    )

    finalize_kernel_tiling_closure(cm, root, architecture="arch35")
    meta = cm.meta["kernel_tiling_closure"]

    assert meta["architecture_pure"] is True
    assert meta["kernel_template_args"] == 2
    assert meta["kernel_abi_links"] == 2
    assert all("old.cpp" not in f for f in meta["selected_kernel_files"])
    assert not any(
        str(r.attrs.get("provenance") or "") == "source_call_site"
        for r in cm.relations.values()
    )

    template_args = [
        e for e in cm.by_kind(EntityKind.TEMPLATE_ARG)
        if e.attrs.get("provenance") == "source_kernel_template_verified"
    ]
    assert [e.name for e in sorted(template_args, key=lambda x: int(x.attrs["order"]))] == ["A", "B"]
    abi = [
        r for r in cm.relations.values()
        if r.attrs.get("provenance") == "source_kernel_abi_position_verified"
    ]
    assert abi
    assert all(str(r.attrs.get("file") or "").endswith("toy_apt.cpp") for r in abi)

    regbase = next(e for e in cm.entities.values() if e.name == "RegbaseFAG")
    assert any(
        r.kind_name() == RelationKind.CALLS.value
        and r.src == kernel.id and r.dst == regbase.id
        and r.attrs.get("provenance") == "source_kernel_call_bound"
        for r in cm.relations.values()
    )


def test_tiling_reads_are_owner_qualified_and_entry_reachable(tmp_path: Path) -> None:
    root = _root(tmp_path)
    (root / "op_kernel" / "toy_apt.cpp").write_text(
        '''
        #include "arch35/entry.h"
        template <bool A, bool B>
        __global__ __aicore__ void toy_kernel(
            __gm__ uint8_t *q, __gm__ uint8_t *out,
            __gm__ uint8_t *workspace, __gm__ uint8_t *tiling_data) {
          RegbaseFAG<A, B>(q, out, tiling_data);
        }
        ''',
        encoding="utf-8",
    )
    (root / "op_kernel" / "arch35" / "entry.h").write_text(
        '''
        class AData { public: int x; };
        class BData { public: int x; };
        template <bool A, bool B>
        inline __aicore__ void
        RegbaseFAG(__gm__ uint8_t *q, __gm__ uint8_t *out, __gm__ uint8_t *tiling_data) {
          ReadA((AData *)tiling_data);
        }
        inline __aicore__ void ReadA(AData *tilingData) {
          int v = tilingData->x;
          (void)v;
        }
        ''',
        encoding="utf-8",
    )

    cm = _base_cm()
    a = cm.upsert(EntityKind.TILING_DATA, "AData")
    b = cm.upsert(EntityKind.TILING_DATA, "BData")
    ax = cm.upsert(EntityKind.TILING_FIELD, "x", eid="TDF::AData::x", attrs={"owner": "AData", "qualified_name": "AData::x", "cpp_type": "int"})
    bx = cm.upsert(EntityKind.TILING_FIELD, "x", eid="TDF::BData::x", attrs={"owner": "BData", "qualified_name": "BData::x", "cpp_type": "int"})
    cm.link(RelationKind.DECLARES, a.id, ax.id)
    cm.link(RelationKind.DECLARES, b.id, bx.id)

    finalize_kernel_tiling_closure(cm, root, architecture="arch35")

    reads = [
        r for r in cm.relations.values()
        if r.kind_name() == RelationKind.READS.value
        and r.attrs.get("provenance") == "source_tilingdata_read_qualified"
    ]
    assert reads
    assert {r.dst for r in reads} == {ax.id}
    assert all(r.attrs.get("entry_reachable") is True for r in reads)
    meta = cm.meta["kernel_tiling_closure"]
    assert meta["tiling_ambiguous_read_sites"] == 0
    assert meta["tiling_entry_reachable_fields"] == 1


def test_nested_read_and_trailing_underscore_host_setter_resolve(tmp_path: Path) -> None:
    """Generic packing: nested member types + host ``sub_`` mirroring ``sub``."""
    root = _root(tmp_path)
    (root / "op_kernel" / "toy_apt.cpp").write_text(
        '''
        #include "arch35/entry.h"
        template <bool A, bool B>
        __global__ __aicore__ void toy_kernel(
            __gm__ uint8_t *q, __gm__ uint8_t *out,
            __gm__ uint8_t *workspace, __gm__ uint8_t *tiling_data) {
          RunKernel(q, out, tiling_data);
        }
        ''',
        encoding="utf-8",
    )
    (root / "op_kernel" / "arch35" / "entry.h").write_text(
        '''
        class InnerParams { public: int scale; };
        class OuterTiling {
         public:
          InnerParams base;
          typename std::conditional<A, InnerParams, std::nullptr_t>::type opt;
        };
        inline __aicore__ void RunKernel(
            __gm__ uint8_t *q, __gm__ uint8_t *out, __gm__ uint8_t *tiling_data) {
          OuterTiling *tilingData = (OuterTiling *)tiling_data;
          int v = tilingData->base.scale;
          (void)v;
        }
        ''',
        encoding="utf-8",
    )
    (root / "op_host" / "arch35" / "host.cpp").write_text(
        '''
        void Fill(OuterTiling *td, int value) {
          InnerParams base_;
          base_.set_scale(value);
        }
        ''',
        encoding="utf-8",
    )

    cm = _base_cm()
    outer = cm.upsert(EntityKind.TILING_DATA, "OuterTiling")
    inner = cm.upsert(EntityKind.TILING_DATA, "InnerParams")
    base = cm.upsert(
        EntityKind.TILING_FIELD,
        "base",
        eid="TDF::OuterTiling::base",
        attrs={"owner": "OuterTiling", "qualified_name": "OuterTiling::base", "cpp_type": "InnerParams"},
    )
    opt = cm.upsert(
        EntityKind.TILING_FIELD,
        "opt",
        eid="TDF::OuterTiling::opt",
        attrs={
            "owner": "OuterTiling",
            "qualified_name": "OuterTiling::opt",
            "cpp_type": "typename std::conditional<A, InnerParams, std::nullptr_t>::type",
        },
    )
    scale = cm.upsert(
        EntityKind.TILING_FIELD,
        "scale",
        eid="TDF::InnerParams::scale",
        attrs={"owner": "InnerParams", "qualified_name": "InnerParams::scale", "cpp_type": "int"},
    )
    cm.link(RelationKind.DECLARES, outer.id, base.id)
    cm.link(RelationKind.DECLARES, outer.id, opt.id)
    cm.link(RelationKind.DECLARES, inner.id, scale.id)

    finalize_kernel_tiling_closure(cm, root, architecture="arch35")
    enrich_tiling_host_writes(cm, root, architecture="arch35")

    reads = [
        r for r in cm.relations.values()
        if r.kind_name() == RelationKind.READS.value
        and r.attrs.get("provenance") == "source_tilingdata_read_qualified"
    ]
    assert {r.dst for r in reads} == {scale.id}
    writes = [
        r for r in cm.relations.values()
        if r.kind_name() == RelationKind.WRITES.value
        and r.attrs.get("provenance") in {
            "source_tilingdata_host_write",
            "source_tilingdata_host_write_verified",
        }
    ]
    assert {r.dst for r in writes} == {scale.id}
    assert cm.meta["kernel_tiling_closure"]["tiling_ambiguous_read_sites"] == 0


def test_object_macro_tiling_type_types_nested_reads(tmp_path: Path) -> None:
    """FAG-style ``#define FagTilingType RealTiling<...> *`` must type tilingData.

    The macro lives in a shared header; the member and the read live elsewhere.
    """
    root = _root(tmp_path)
    (root / "op_kernel" / "toy_apt.cpp").write_text(
        '#include "arch35/entry.h"\n'
        "template <bool A, bool B>\n"
        "__global__ __aicore__ void toy_kernel(\n"
        "    __gm__ uint8_t *q, __gm__ uint8_t *out,\n"
        "    __gm__ uint8_t *workspace, __gm__ uint8_t *tiling_data) {\n"
        "  RunKernel(q, out, tiling_data);\n"
        "}\n",
        encoding="utf-8",
    )
    (root / "op_kernel" / "arch35" / "common.h").write_text(
        "class InnerParams { public: int coreNum; };\n"
        "class OuterTiling { public: InnerParams s1s2BNGS1S2BaseParams; };\n"
        "#define FagTilingType \\\n"
        "    const __gm__ OuterTiling<A, B> *__restrict\n",
        encoding="utf-8",
    )
    (root / "op_kernel" / "arch35" / "entry.h").write_text(
        '#include "common.h"\n'
        "inline __aicore__ void RunKernel(\n"
        "    __gm__ uint8_t *q, __gm__ uint8_t *out, __gm__ uint8_t *tiling_data) {\n"
        "  FagTilingType tilingData = (FagTilingType)tiling_data;\n"
        "  int v = tilingData->s1s2BNGS1S2BaseParams.coreNum;\n"
        "  (void)v;\n"
        "}\n",
        encoding="utf-8",
    )
    cm = _base_cm()
    outer = cm.upsert(EntityKind.TILING_DATA, "OuterTiling")
    inner = cm.upsert(EntityKind.TILING_DATA, "InnerParams")
    parent = cm.upsert(
        EntityKind.TILING_FIELD,
        "s1s2BNGS1S2BaseParams",
        eid="TDF::OuterTiling::s1s2BNGS1S2BaseParams",
        attrs={
            "owner": "OuterTiling",
            "qualified_name": "OuterTiling::s1s2BNGS1S2BaseParams",
            "cpp_type": "InnerParams",
        },
    )
    field = cm.upsert(
        EntityKind.TILING_FIELD,
        "coreNum",
        eid="TDF::InnerParams::coreNum",
        attrs={"owner": "InnerParams", "qualified_name": "InnerParams::coreNum", "cpp_type": "int"},
    )
    cm.link(RelationKind.DECLARES, outer.id, parent.id)
    cm.link(RelationKind.DECLARES, inner.id, field.id)
    finalize_kernel_tiling_closure(cm, root, architecture="arch35")
    from uo_init.passes.tiling_kernel_reads import rebuild_verified_tiling_reads

    rebuild_verified_tiling_reads(cm, root, architecture="arch35")
    reads = [
        r
        for r in cm.relations.values()
        if r.kind_name() == RelationKind.READS.value
        and r.dst == field.id
    ]
    assert reads
    assert all(
        str((r.attrs or {}).get("provenance") or "")
        in {"source_tilingdata_read_verified", "source_tilingdata_read_qualified"}
        for r in reads
    )


def test_inherited_tilingdata_member_read_in_other_tu(tmp_path: Path) -> None:
    """``this->tilingData->nested.x`` in a derived TU; member declared on the base.

    An empty-tensor Init parameter may reuse the name ``tilingData`` with a
    different TilingData type; that must not drop the base-class member type.
    """
    root = _root(tmp_path)
    (root / "op_kernel" / "toy_apt.cpp").write_text(
        '#include "arch35/derived.h"\n'
        "__global__ __aicore__ void toy_kernel(\n"
        "    __gm__ uint8_t *q, __gm__ uint8_t *out,\n"
        "    __gm__ uint8_t *workspace, __gm__ uint8_t *tiling_data) {\n"
        "  RunKernel(q, out, tiling_data);\n"
        "}\n",
        encoding="utf-8",
    )
    (root / "op_kernel" / "arch35" / "common.h").write_text(
        "class InnerParams { public: int deterMaxRound; };\n"
        "class OuterTiling { public: InnerParams baseDeterParam; };\n"
        "#define FagTilingType const __gm__ OuterTiling *__restrict\n",
        encoding="utf-8",
    )
    (root / "op_kernel" / "arch35" / "base.h").write_text(
        '#include "common.h"\n'
        "class KernelBase {\n"
        " public:\n"
        "  FagTilingType tilingData;\n"
        "};\n",
        encoding="utf-8",
    )
    (root / "op_kernel" / "arch35" / "empty.h").write_text(
        "class EmptyTiling { public: int isRope; };\n"
        "inline __aicore__ void InitEmpty(\n"
        "    const EmptyTiling *__restrict tilingData) {\n"
        "  int v = tilingData->isRope;\n"
        "  (void)v;\n"
        "}\n",
        encoding="utf-8",
    )
    (root / "op_kernel" / "arch35" / "derived.h").write_text(
        '#include "base.h"\n'
        "class KernelDeter : public KernelBase {\n"
        " public:\n"
        "  inline __aicore__ void Init() {\n"
        "    int v = this->tilingData->baseDeterParam.deterMaxRound;\n"
        "    (void)v;\n"
        "  }\n"
        "};\n"
        "inline __aicore__ void RunKernel(\n"
        "    __gm__ uint8_t *q, __gm__ uint8_t *out, __gm__ uint8_t *tiling_data) {\n"
        "  KernelDeter op;\n"
        "  op.Init();\n"
        "}\n",
        encoding="utf-8",
    )
    cm = _base_cm()
    outer = cm.upsert(EntityKind.TILING_DATA, "OuterTiling")
    inner = cm.upsert(EntityKind.TILING_DATA, "InnerParams")
    parent = cm.upsert(
        EntityKind.TILING_FIELD,
        "baseDeterParam",
        eid="TDF::OuterTiling::baseDeterParam",
        attrs={
            "owner": "OuterTiling",
            "qualified_name": "OuterTiling::baseDeterParam",
            "cpp_type": "InnerParams",
        },
    )
    field = cm.upsert(
        EntityKind.TILING_FIELD,
        "deterMaxRound",
        eid="TDF::InnerParams::deterMaxRound",
        attrs={
            "owner": "InnerParams",
            "qualified_name": "InnerParams::deterMaxRound",
            "cpp_type": "int",
        },
    )
    empty = cm.upsert(EntityKind.TILING_DATA, "EmptyTiling")
    empty_field = cm.upsert(
        EntityKind.TILING_FIELD,
        "isRope",
        eid="TDF::EmptyTiling::isRope",
        attrs={"owner": "EmptyTiling", "qualified_name": "EmptyTiling::isRope", "cpp_type": "int"},
    )
    cm.link(RelationKind.DECLARES, outer.id, parent.id)
    cm.link(RelationKind.DECLARES, inner.id, field.id)
    cm.link(RelationKind.DECLARES, empty.id, empty_field.id)
    finalize_kernel_tiling_closure(cm, root, architecture="arch35")
    from uo_init.passes.tiling_kernel_reads import rebuild_verified_tiling_reads

    rebuild_verified_tiling_reads(cm, root, architecture="arch35")
    reads = [
        r
        for r in cm.relations.values()
        if r.kind_name() == RelationKind.READS.value and r.dst == field.id
    ]
    assert reads


def test_host_setter_is_bound_to_receiver_tiling_type_not_short_name(tmp_path: Path) -> None:
    root = _root(tmp_path)
    (root / "op_kernel" / "toy_apt.cpp").write_text(
        '#include "arch35/entry.h"\n', encoding="utf-8"
    )
    (root / "op_kernel" / "arch35" / "entry.h").write_text("// selected\n", encoding="utf-8")
    (root / "op_host" / "arch35" / "host.cpp").write_text(
        '''
        void Fill(AData *a, BData *b, int value) {
          a->set_x(value);
        }
        ''',
        encoding="utf-8",
    )

    cm = _base_cm()
    a = cm.upsert(EntityKind.TILING_DATA, "AData")
    b = cm.upsert(EntityKind.TILING_DATA, "BData")
    ax = cm.upsert(EntityKind.TILING_FIELD, "x", eid="TDF::AData::x", attrs={"owner": "AData", "qualified_name": "AData::x", "cpp_type": "int"})
    bx = cm.upsert(EntityKind.TILING_FIELD, "x", eid="TDF::BData::x", attrs={"owner": "BData", "qualified_name": "BData::x", "cpp_type": "int"})
    cm.link(RelationKind.DECLARES, a.id, ax.id)
    cm.link(RelationKind.DECLARES, b.id, bx.id)

    finalize_kernel_tiling_closure(cm, root, architecture="arch35")
    enrich_tiling_host_writes(cm, root, architecture="arch35")

    writes = [
        r for r in cm.relations.values()
        if r.kind_name() == RelationKind.WRITES.value
        and r.attrs.get("provenance") == "source_tilingdata_host_write_verified"
    ]
    assert {r.dst for r in writes} == {ax.id}
    assert cm.meta["kernel_tiling_closure"]["tiling_ambiguous_writer_sites"] == 0


def test_closure_binds_tiling_key_is_catalog_to_kernel(tmp_path: Path) -> None:
    """Long commented ABI lists used to hide the entry from GLOBAL_KERNEL_RE."""
    from uo_init.passes.source_contract import enrich_codemap_from_operator_source
    from uo_init.diagnostics.audit import _path_exists

    root = tmp_path / "toy"
    (root / "op_graph").mkdir(parents=True)
    (root / "op_host").mkdir(parents=True)
    (root / "op_kernel").mkdir(parents=True)
    params = ",\n".join(
        f"                            GM_ADDR arg{i},  // input {i}: {'x' * 80}"
        for i in range(16)
    )
    (root / "op_kernel" / "toy.cpp").write_text(
        "#define TILING_KEY_BH_BF16 20000\n"
        "#define TILING_KEY_BH_FP16 20001\n"
        "extern \"C\" __global__ __aicore__ void\n"
        f"toy({params},\n"
        "                            GM_ADDR tiling)  // tiling\n"
        "{\n"
        "  if (TILING_KEY_IS(TILING_KEY_BH_BF16)) { return; }\n"
        "  if (TILING_KEY_IS(TILING_KEY_BH_FP16)) { return; }\n"
        "}\n",
        encoding="utf-8",
    )
    cm = CodeMap(op_name="toy", architecture="arch35")
    enrich_codemap_from_operator_source(cm, root, architecture="arch35")
    finalize_kernel_tiling_closure(cm, root, architecture="arch35")
    keys = [
        e
        for e in cm.by_kind(EntityKind.TILING_KEY)
        if e.attrs.get("source_declared")
    ]
    assert {e.name for e in keys} == {"TILING_KEY_BH_BF16", "TILING_KEY_BH_FP16"}
    kernels = cm.by_kind(EntityKind.KERNEL)
    assert [k.name for k in kernels] == ["toy"]
    selects = {
        (cm.entities[r.src].name, cm.entities[r.dst].name)
        for r in cm.relations.values()
        if r.kind_name() == RelationKind.SELECTS.value
        and cm.entities[r.src].kind_name() == EntityKind.TILING_KEY.value
        and cm.entities[r.dst].kind_name() == EntityKind.KERNEL.value
    }
    assert selects == {
        ("TILING_KEY_BH_BF16", "toy"),
        ("TILING_KEY_BH_FP16", "toy"),
    }
    assert _path_exists(
        cm, start_kind=EntityKind.TILING_KEY, end_kind=EntityKind.KERNEL
    )


def test_source_resolution_host_constexpr_alias_and_field_assign(tmp_path: Path) -> None:
    from uo_init.passes.source_resolution import resolve_source_gaps

    root = _root(tmp_path)
    (root / "op_kernel" / "toy_apt.cpp").write_text(
        '#include "arch35/entry.h"\n'
        "template <bool A, bool B>\n"
        "__global__ __aicore__ void toy_kernel(\n"
        "    __gm__ uint8_t *q, __gm__ uint8_t *out,\n"
        "    __gm__ uint8_t *workspace, __gm__ uint8_t *tiling_data) {\n"
        "  InitConst();\n"
        "}\n",
        encoding="utf-8",
    )
    (root / "op_kernel" / "arch35" / "entry.h").write_text(
        "using ToyTilingFFFF =\n"
        "    optiling::ToyTilingData<false, false>;\n"
        "struct ConstInfo { uint32_t aicCoreNum; };\n"
        "inline void InitConst() {\n"
        "  ConstInfo constInfo;\n"
        "  constInfo.aicCoreNum = tilingData->base.coreNum >> 1;\n"
        "}\n",
        encoding="utf-8",
    )
    (root / "op_host" / "arch35" / "common.h").write_text(
        "constexpr uint32_t CORE_LIST_NUM = 36;\n",
        encoding="utf-8",
    )
    cm = _base_cm()
    resolve_source_gaps(cm, root, architecture="arch35")
    consts = [e for e in cm.by_kind(EntityKind.COMPILE_VAR) if e.name == "CORE_LIST_NUM"]
    assert consts
    assert "36" in str(consts[0].attrs.get("value_expr") or "")
    aliases = [
        e
        for e in cm.by_kind(EntityKind.TYPE)
        if e.name == "ToyTilingFFFF" and e.attrs.get("role") == "type_alias"
    ]
    assert aliases
    fields = [e for e in cm.by_kind(EntityKind.FIELD) if e.name == "aicCoreNum"]
    assert fields
    sites = fields[0].attrs.get("definition_sites") or []
    assert any(
        isinstance(site, dict)
        and "entry.h" in str(site.get("file") or "").replace("\\", "/")
        and "tiling_assign" in str(site.get("kind") or site.get("provenance") or "")
        for site in sites
    )


def test_non_tiling_info_member_is_not_a_tiling_read(tmp_path: Path) -> None:
    root = _root(tmp_path)
    (root / "op_kernel" / "toy_apt.cpp").write_text(
        '#include "arch35/entry.h"\n'
        "template <bool A, bool B>\n"
        "__global__ __aicore__ void toy_kernel(\n"
        "    __gm__ uint8_t *q, __gm__ uint8_t *out,\n"
        "    __gm__ uint8_t *workspace, __gm__ uint8_t *tiling_data) {\n"
        "  RunKernel(q, out, tiling_data);\n"
        "}\n",
        encoding="utf-8",
    )
    (root / "op_kernel" / "arch35" / "entry.h").write_text(
        "struct Info { int x; };\n"
        "inline __aicore__ void RunKernel(\n"
        "    __gm__ uint8_t *q, __gm__ uint8_t *out, __gm__ uint8_t *tiling_data) {\n"
        "  Info info;\n"
        "  int v = info.x;\n"
        "  (void)v;\n"
        "}\n",
        encoding="utf-8",
    )
    cm = _base_cm()
    owner = cm.upsert(EntityKind.TILING_DATA, "BData")
    field = cm.upsert(
        EntityKind.TILING_FIELD,
        "x",
        eid="TDF::BData::x",
        attrs={"owner": "BData", "qualified_name": "BData::x", "cpp_type": "int"},
    )
    cm.link(RelationKind.DECLARES, owner.id, field.id)
    finalize_kernel_tiling_closure(cm, root, architecture="arch35")
    reads = [
        r
        for r in cm.relations.values()
        if r.kind_name() == RelationKind.READS.value
        and r.dst == field.id
    ]
    assert reads == []


def test_unique_short_field_does_not_bind_wrong_receiver_type(tmp_path: Path) -> None:
    root = _root(tmp_path)
    (root / "op_kernel" / "toy_apt.cpp").write_text(
        '#include "arch35/entry.h"\n', encoding="utf-8"
    )
    (root / "op_kernel" / "arch35" / "entry.h").write_text("// selected\n", encoding="utf-8")
    (root / "op_host" / "arch35" / "host.cpp").write_text(
        "void Fill(AData *a, int value) { a->set_x(value); }\n",
        encoding="utf-8",
    )
    cm = _base_cm()
    a = cm.upsert(EntityKind.TILING_DATA, "AData")
    b = cm.upsert(EntityKind.TILING_DATA, "BData")
    bx = cm.upsert(
        EntityKind.TILING_FIELD,
        "x",
        eid="TDF::BData::x",
        attrs={"owner": "BData", "qualified_name": "BData::x", "cpp_type": "int"},
    )
    cm.link(RelationKind.DECLARES, b.id, bx.id)
    finalize_kernel_tiling_closure(cm, root, architecture="arch35")
    enrich_tiling_host_writes(cm, root, architecture="arch35")
    writes = [
        r
        for r in cm.relations.values()
        if r.kind_name() == RelationKind.WRITES.value
        and r.dst == bx.id
    ]
    assert writes == []
    assert a.id


def test_rebuild_bodies_false_skips_v1_call_graph(tmp_path: Path) -> None:
    root = _root(tmp_path)
    (root / "op_kernel" / "toy_apt.cpp").write_text(
        '''
        #include "arch35/entry.h"
        template <bool A, bool B>
        __global__ __aicore__ void toy_kernel(
            __gm__ uint8_t *q, __gm__ uint8_t *out,
            __gm__ uint8_t *workspace, __gm__ uint8_t *tiling_data) {
          Helper(q);
        }
        ''',
        encoding="utf-8",
    )
    (root / "op_kernel" / "arch35" / "entry.h").write_text(
        "inline __aicore__ void Helper(__gm__ uint8_t *q) { (void)q; }\n",
        encoding="utf-8",
    )
    cm = _base_cm()
    cm.upsert(EntityKind.KERNEL, "toy_kernel", attrs={"provenance": "source_kernel_signature"})
    finalize_kernel_tiling_closure(cm, root, architecture="arch35", rebuild_bodies=False)
    meta = cm.meta["kernel_tiling_closure"]
    assert meta["kernel_scopes"] == 0
    assert meta["kernel_bound_call_sites"] == 0
    assert not any(
        str(e.attrs.get("provenance") or "") == "source_kernel_definition"
        for e in cm.entities.values()
    )
    assert meta["kernel_entries"] >= 1
