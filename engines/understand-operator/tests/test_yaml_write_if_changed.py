from __future__ import annotations

from pathlib import Path

from uo.scripts._ir_io import read_yaml, write_yaml, write_yaml_if_changed


def test_write_yaml_if_changed_skips_identical(tmp_path: Path) -> None:
    path = tmp_path / "ir" / "operator_graph.yaml"
    payload = {"version": 1, "nodes": [{"id": "N1"}]}
    write_yaml(path, payload)
    mtime = path.stat().st_mtime_ns
    assert write_yaml_if_changed(path, payload) is False
    assert path.stat().st_mtime_ns == mtime


def test_write_yaml_if_changed_writes_on_delta(tmp_path: Path) -> None:
    path = tmp_path / "ir" / "bridge.yaml"
    write_yaml(path, {"version": 1, "nodes": []})
    assert write_yaml_if_changed(path, {"version": 1, "nodes": [{"id": "B1"}]}) is True
    doc = read_yaml(path)
    assert len(doc.get("nodes") or []) == 1
