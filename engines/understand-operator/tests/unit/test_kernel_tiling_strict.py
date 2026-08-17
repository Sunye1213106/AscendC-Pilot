from __future__ import annotations

from pathlib import Path

from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import EntityKind
from uo_init.ir.relation import RelationKind
from uo_init.passes.kernel_call_boundaries import classify_kernel_call_boundaries
from uo_init.passes.tiling_field_complete import complete_tiling_fields
from uo_init.passes.tiling_host_writes import enrich_tiling_host_writes


def test_conditional_and_array_tiling_fields_are_real_abi_fields(tmp_path: Path) -> None:
    root = tmp_path / "toy"
    td = root / "op_kernel" / "arch35" / "toy_tiling_data.h"
    td.parent.mkdir(parents=True)
    (root / "op_host" / "arch35").mkdir(parents=True)
    td.write_text(
        '''
        class Child { public: int64_t values[8]; };
        template <bool Enabled>
        class Root {
        public:
          typename std::conditional<!Enabled, Child, std::nullptr_t>::type child;
        };
        ''', encoding="utf-8"
    )
    cm = CodeMap(op_name="toy", architecture="arch35")
    child = cm.upsert(EntityKind.TILING_DATA, "Child")
    root_ent = cm.upsert(EntityKind.TILING_DATA, "Root")
    complete_tiling_fields(cm, root, architecture="arch35")
    values = cm.entities["TDF::Child::values"]
    nested = cm.entities["TDF::Root::child"]
    assert values.attrs["is_array"] is True
    assert values.attrs["array_extent"] == "[8]"
    assert "Child" in nested.attrs["cpp_type"]
    assert any(r.src == child.id and r.kind_name() == RelationKind.DECLARES.value for r in cm.relations.values())
    assert any(r.src == root_ent.id and r.kind_name() == RelationKind.DECLARES.value for r in cm.relations.values())


def test_clang_field_decl_fills_registered_owner_members(tmp_path: Path) -> None:
    from uo_init.clang_walk import FieldDecl
    from uo_init.host_ir import HostIR

    root = tmp_path / "toy"
    (root / "op_kernel" / "arch35").mkdir(parents=True)
    (root / "op_host" / "arch35").mkdir(parents=True)
    (root / "op_kernel" / "arch35" / "toy_tiling_data.h").write_text(
        "class Root { public: int leftover; };\n",
        encoding="utf-8",
    )
    cm = CodeMap(op_name="toy", architecture="arch35")
    owner = cm.upsert(EntityKind.TILING_DATA, "Root")
    host_ir = HostIR(
        field_decls={
            ("Root", "child"): FieldDecl(
                host="Root",
                name="child",
                init=None,
                file="op_kernel/arch35/toy_tiling_data.h",
                line=4,
                type_text="Child",
            )
        }
    )
    complete_tiling_fields(cm, root, architecture="arch35", host_ir=host_ir)
    child = cm.entities["TDF::Root::child"]
    assert child.attrs.get("provenance") == "clang_field_decl"
    leftover = cm.entities["TDF::Root::leftover"]
    assert leftover.attrs.get("provenance") == "source_tiling_data_member_complete"
    assert owner.id


def test_shared_host_file_referencing_arch35_supplies_tiling_writer(tmp_path: Path) -> None:
    root = tmp_path / "toy"
    (root / "op_host" / "arch35").mkdir(parents=True)
    (root / "op_kernel" / "arch35").mkdir(parents=True)
    (root / "op_host" / "shared.cpp").write_text(
        '''
        #include "../op_kernel/arch35/toy_tiling_data.h"
        void Fill(AData *data, int v) { data->set_x(v); }
        ''', encoding="utf-8"
    )
    cm = CodeMap(op_name="toy", architecture="arch35")
    owner = cm.upsert(EntityKind.TILING_DATA, "AData")
    field = cm.upsert(EntityKind.TILING_FIELD, "x", eid="TDF::AData::x",
                      attrs={"owner":"AData","qualified_name":"AData::x","cpp_type":"int"})
    cm.link(RelationKind.DECLARES, owner.id, field.id)
    enrich_tiling_host_writes(cm, root, architecture="arch35")
    writes = [r for r in cm.relations.values() if r.kind_name() == RelationKind.WRITES.value]
    assert any(r.dst == field.id and r.attrs.get("provenance") == "source_tilingdata_host_write_verified" for r in writes)
    assert cm.meta["kernel_tiling_closure"]["tiling_ambiguous_writer_sites"] == 0


def test_unbound_dependent_call_becomes_explicit_boundary_not_fake_target() -> None:
    cm = CodeMap(op_name="toy", architecture="arch35")
    kernel = cm.upsert(EntityKind.KERNEL, "kernel", attrs={"source_signature": True})
    ref = cm.upsert(EntityKind.METHOD, "buf.Get", attrs={
        "call_target":"Get", "receiver":"buf", "candidate_definitions":[],
        "provenance":"source_kernel_call_unresolved_v2",
    }, status="partial", confidence=0.5)
    rel = cm.link(RelationKind.CALLS, kernel.id, ref.id,
                  attrs={"provenance":"source_kernel_call_unresolved_v2","file":"x.h","line":9},
                  status="partial", confidence=0.5)
    classify_kernel_call_boundaries(cm)
    assert rel.attrs["provenance"] == "source_kernel_call_boundary"
    assert rel.attrs["boundary_kind"] == "static_target_not_proven"
    assert ref.attrs["role"] == "kernel_call_boundary"
    assert ref.status == "confirmed"
    assert cm.meta["kernel_tiling_closure"]["kernel_reachable_unresolved_internal_call_sites"] == 0
