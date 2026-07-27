"""Bridge blocking gaps → llm_task + typed field identity/metadata."""

from __future__ import annotations

from pathlib import Path

from uo.scripts._ir_io import write_yaml
from uo.scripts.evidence_score import score_bridge_blocking_gaps
from uo.scripts.llm_tasks import load_llm_tasks, upsert_tasks_from_score_items
from uo.scripts.reconcile_bridge import _collect_typed_fields


def test_blocking_bridge_gap_generates_llm_task(tmp_path: Path) -> None:
    bridge = {
        "unresolved": [
            {
                "code": "missing_tiling_field_producer",
                "severity": "blocking",
                "field": "blockDim",
                "field_path": "blockDim",
                "owning_type": "TilingData",
            }
        ],
        "diagnostics": [],
        "field_classifications": [],
        "tilingdata_bridges": [],
    }
    items = score_bridge_blocking_gaps(bridge)
    assert items
    assert all(i.get("disposition") == "llm_task" for i in items)
    assert all(i.get("object_type") == "tilingdata_bridge" for i in items)

    uo = tmp_path / "uo"
    (uo / "ir").mkdir(parents=True)
    upsert_tasks_from_score_items(
        uo,
        items,
        checkpoint="extract.post_semantic",
        run_id="r1",
        source_snapshot_hash="snap",
        score_phase="post_semantic",
    )
    tasks = [t for t in load_llm_tasks(uo)["tasks"] if t.get("status") == "open"]
    assert tasks
    assert tasks[0]["type"] in {"evidence_enrichment", "candidate_generation", "tilingdata_bridge"}


def test_typed_field_metadata_propagation() -> None:
    layer = {
        "nodes": [
            {
                "node_type": "TilingDataField",
                "id": "TDF_x",
                "name": "blockDim",
                "field_path": "blockDim",
                "owning_type": "TilingData",
                "determinant_source": "derived_from_tiling_field",
                "source_kind": "derived",
                "expression": "tiling.blockDim",
                "producer_kind": "derived_from_tiling_field",
                "runtime_domain": "host",
                "architecture": "arch35",
                "file_path": "op_kernel/a.cpp",
            }
        ]
    }
    fields = _collect_typed_fields(layer, side="kernel")
    assert fields[0]["determinant_source"] == "derived_from_tiling_field"
    assert fields[0]["expression"] == "tiling.blockDim"
    assert fields[0]["producer_kind"] == "derived_from_tiling_field"


def test_anonymous_field_stable_ids_do_not_collide() -> None:
    layer = {"nodes": []}
    fields = _collect_typed_fields(
        layer,
        side="kernel",
        also=["alpha", "beta"],
    )
    ids = [f["id"] for f in fields]
    assert None not in ids
    assert "" not in ids
    assert ids[0] != ids[1]
    assert all(str(i).startswith("TDF") or "TDF" in str(i) for i in ids)
