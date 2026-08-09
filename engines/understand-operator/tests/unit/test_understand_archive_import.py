from __future__ import annotations

import zipfile
from pathlib import Path

import yaml

from uo_init.ir.entity import EntityKind
from uo_init.ir.relation import RelationKind
from uo_init.store.understand_archive import read_understand_archive


def _write_archive(path: Path) -> None:
    root = ".understand-operator/toy"
    host = {
        "sections": {
            "variables": {
                "items": [
                    {
                        "id": "v_split",
                        "kind": "runtime_variable",
                        "name": "splitAxis",
                        "status": "confirmed",
                        "identity": {"normalized": {"source_name": "splitAxis"}},
                        "sources": [
                            {
                                "file": "toy/op_host/arch35/tiling.cpp",
                                "span": {"start_line": 10, "end_line": 10},
                            }
                        ],
                    }
                ],
                "relations": [],
                "unresolved": [],
            },
            "tiling_key": {
                "items": [
                    {
                        "id": "k_split",
                        "kind": "tiling_key_field",
                        "name": "SplitAxis",
                        "runtime_source_name": "splitAxis",
                        "status": "confirmed",
                        "sources": [
                            {
                                "file": "toy/op_kernel/arch35/key.h",
                                "span": {"start_line": 20, "end_line": 20},
                            }
                        ],
                    },
                    {
                        "id": "k_free_text",
                        "kind": "tiling_key_field",
                        "name": "IsTnd",
                        "derivation": "layoutType == TND",
                        "status": "confirmed",
                        "sources": [
                            {
                                "file": "toy/op_kernel/arch35/key.h",
                                "span": {"start_line": 21, "end_line": 21},
                            }
                        ],
                    },
                ],
                "relations": [],
                "unresolved": [],
            },
        }
    }
    kernel = {
        "sections": {
            "entries": {
                "items": [
                    {
                        "id": "kernel_main",
                        "kind": "kernel_global_entry",
                        "name": "toy_kernel",
                        "architecture_variant": "arch35",
                        "status": "confirmed",
                        "sources": [
                            {
                                "file": "toy/op_kernel/kernel.cpp",
                                "span": {"start_line": 1, "end_line": 20},
                            }
                        ],
                    }
                ],
                "relations": [],
                "unresolved": [
                    {
                        "id": "gap_call",
                        "reason": "kernel_call_edges",
                        "question": "call graph not structured",
                        "candidate_sources": [
                            {
                                "file": "toy/op_kernel/arch35/kernel.h",
                                "span": {"start_line": 30, "end_line": 40},
                            }
                        ],
                    }
                ],
            }
        }
    }
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(f"{root}/manifest.yaml", yaml.safe_dump({"op_name": "toy"}))
        zf.writestr(f"{root}/facts/host.yaml", yaml.safe_dump(host))
        zf.writestr(f"{root}/facts/kernel/overview.yaml", yaml.safe_dump(kernel))


def test_understand_archive_import_keeps_only_structured_relations(tmp_path: Path) -> None:
    archive = tmp_path / "facts.zip"
    _write_archive(archive)
    cm = read_understand_archive(archive, op_name="toy", architecture="arch35")

    assert len(cm.by_kind(EntityKind.TILING_KEY)) == 2
    assert len(cm.by_kind(EntityKind.KERNEL)) == 1
    assert len([e for e in cm.entities.values() if e.status == "unresolved"]) == 1

    derives = [r for r in cm.relations.values() if r.kind_name() == RelationKind.DERIVES.value]
    assert len(derives) == 1
    assert cm.entities[derives[0].src].name == "splitAxis"
    assert cm.entities[derives[0].dst].name == "SplitAxis"

    # The free-text IsTnd derivation and node presence must not create a
    # key→kernel edge.
    assert not any(
        r.kind_name() in {RelationKind.SELECTS.value, RelationKind.LAUNCHES.value}
        for r in cm.relations.values()
    )
