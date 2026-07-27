"""integrity ok must match overall_status."""

from __future__ import annotations

from pathlib import Path

from uo.scripts._ir_io import write_yaml
from uo.scripts.check_kb_integrity import check_kb_integrity


def test_ok_false_when_consumer_not_ready(tmp_path: Path, monkeypatch) -> None:
    op = "DemoOp"
    repo = tmp_path / op
    repo.mkdir()
    uo = repo / ".ascendc-pilot" / "uo"
    for d in ("ir", "checks", "tiling"):
        (uo / d).mkdir(parents=True)
    write_yaml(uo / "manifest.yaml", {"op_name": op})
    write_yaml(
        uo / "ir" / "entrypoint_graph.yaml",
        {"closure": {"host_main_chain": "closed", "kernel_main_chain": "closed", "blocking_unresolved": []}},
    )
    write_yaml(uo / "ir" / "host_subgraph.yaml", {"nodes": [], "edges": []})
    write_yaml(uo / "ir" / "kernel_subgraph.yaml", {"nodes": [], "edges": []})
    write_yaml(uo / "ir" / "operator_boundary.yaml", {"inputs": [{"name": "x"}], "outputs": [{"name": "y"}]})
    write_yaml(uo / "ir" / "unresolved.yaml", {"items": []})
    write_yaml(
        uo / "ir" / "bridge.yaml",
        {
            "bridge_metrics": {
                "kernel_loaded_field_count": 100,
                "host_produced_count": 1,
                "unknown_type_count": 0,
                "unresolved_count": 90,
            }
        },
    )
    write_yaml(uo / "ir" / "input_derivable.yaml", {"keys": {"KEY_1": {"input_derivable": True}}})
    # Avoid key gate import hard-fail noise
    monkeypatch.setitem(__import__("sys").modules, "ascendc_pilot.gates", type("G", (), {"run_key_gates": staticmethod(lambda *a, **k: {"ok": True, "gates": []})})())
    payload = check_kb_integrity(repo, op, write_outputs=True)
    assert payload.get("overall_status") == "fail"
    assert payload.get("ok") is False
    quality = __import__("uo.scripts._ir_io", fromlist=["read_yaml"]).read_yaml(uo / "quality.yaml")
    assert quality.get("status") == "fail"
