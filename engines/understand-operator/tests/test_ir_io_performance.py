from __future__ import annotations

import os
import time
from pathlib import Path

from uo.scripts._ir_io import atomic_write_yaml, read_yaml, write_yaml_if_changed


def test_write_yaml_if_changed_preserves_mtime(tmp_path: Path) -> None:
    path = tmp_path / "large.yaml"
    payload = {"version": 1, "nodes": [{"id": f"N{i}", "value": i} for i in range(100)]}

    assert write_yaml_if_changed(path, payload) is True
    first = path.stat().st_mtime_ns
    assert write_yaml_if_changed(path, payload) is False
    assert path.stat().st_mtime_ns == first
    assert read_yaml(path) == payload


def test_external_edit_invalidates_semantic_sidecar(tmp_path: Path) -> None:
    path = tmp_path / "graph.yaml"
    payload = {"version": 1, "value": 1}
    assert write_yaml_if_changed(path, payload) is True

    time.sleep(0.002)
    path.write_text("version: 1\nvalue: 9\n", encoding="utf-8")
    os.utime(path, None)

    assert write_yaml_if_changed(path, payload) is True
    assert read_yaml(path) == payload


def test_atomic_write_yaml_skips_unchanged_payload(tmp_path: Path) -> None:
    path = tmp_path / "atomic.yaml"
    payload = {"version": 1, "items": [1, 2, 3]}
    assert atomic_write_yaml(path, payload) is True
    first = path.stat().st_mtime_ns
    assert atomic_write_yaml(path, payload) is False
    assert path.stat().st_mtime_ns == first
