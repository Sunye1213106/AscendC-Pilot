from __future__ import annotations

from pathlib import Path

from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import EntityKind
from uo_init.passes.frontier_resolution import resolve_class_frontiers
from uo_init.passes.tiling_registration import enrich_tiling_registrations


def test_constant_packed_key_mask_selects_exact_tiling_data(tmp_path: Path) -> None:
    op = tmp_path / "toy"
    kernel = op / "op_kernel" / "arch35"
    kernel.mkdir(parents=True)
    (kernel / "tiling_registration.h").write_text(
        'REGISTER_TILING_FOR_TILINGKEY("(TILING_KEY_VAR & 0x1)", EmptyData);\n',
        encoding="utf-8",
    )

    cm = CodeMap(op_name="toy", architecture="arch35")
    key0 = cm.upsert(
        EntityKind.TILING_KEY,
        "FirstFlag",
        attrs={"source_declared": True, "decl_order": 0, "bit_width": 1},
    )
    key1 = cm.upsert(
        EntityKind.TILING_KEY,
        "SecondFlag",
        attrs={"source_declared": True, "decl_order": 1, "bit_width": 1},
    )
    data = cm.upsert(EntityKind.TILING_DATA, "EmptyData")

    enrich_tiling_registrations(cm, op, architecture="arch35")

    predicates = [
        e for e in cm.by_kind(EntityKind.PREDICATE)
        if e.attrs.get("predicate_role") == "packed_tiling_key_registration"
    ]
    assert len(predicates) == 1
    predicate = predicates[0]
    assert any(r.src == key0.id and r.dst == predicate.id and r.kind_name() == "CONTROLS" for r in cm.relations.values())
    assert not any(r.src == key1.id and r.dst == predicate.id and r.kind_name() == "CONTROLS" for r in cm.relations.values())
    assert any(r.src == predicate.id and r.dst == data.id and r.kind_name() == "SELECTS" for r in cm.relations.values())
    assert key0.attrs["bit_offset"] == 0
    assert key1.attrs["bit_offset"] == 1


def test_class_declaration_gap_follows_out_of_class_method_body(tmp_path: Path) -> None:
    op = tmp_path / "toy"
    kernel = op / "op_kernel" / "arch35"
    kernel.mkdir(parents=True)
    source = kernel / "kernel_deter.h"
    source.write_text(
        "template <typename T> class Worker { public: void Process(); };\n"
        "template <typename T>\n"
        "void Worker<T>::Process() {\n"
        "  if constexpr (sizeof(T) > 1) { return; }\n"
        "}\n",
        encoding="utf-8",
    )

    cm = CodeMap(op_name="toy", architecture="arch35")
    gap = cm.upsert(
        EntityKind.OTHER,
        "frontier-gap",
        attrs={
            "role": "unresolved",
            "reason": "frontier_sites",
            "candidate_sources": [
                {
                    "file": "toy/op_kernel/arch35/kernel_deter.h",
                    "symbol": "Worker",
                    "span": {"start_line": 1, "end_line": 1},
                    "anchor_kind": "class_declaration",
                }
            ],
        },
        status="unresolved",
        confidence=0.0,
    )

    resolve_class_frontiers(cm, op, architecture="arch35")

    assert gap.status == "resolved"
    assert gap.attrs["resolved_by"] == "source_class_frontier"
    assert gap.attrs["resolved_frontier_branch_count"] == 1
    assert any(e.kind_name() == EntityKind.BRANCH.value and e.attrs.get("owner") == "Worker" for e in cm.entities.values())
