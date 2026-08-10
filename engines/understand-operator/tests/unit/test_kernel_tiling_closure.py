from __future__ import annotations

from pathlib import Path

from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import EntityKind
from uo_init.ir.relation import RelationKind
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
