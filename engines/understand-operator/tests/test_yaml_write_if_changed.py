from __future__ import annotations

from pathlib import Path

from uo.scripts._ir_io import (
    _stable_payload_hash,
    read_yaml,
    write_yaml,
    write_yaml_if_changed,
)


def test_write_yaml_if_changed_skips_identical(tmp_path: Path) -> None:
    path = tmp_path / "ir" / "operator_graph.yaml"
    payload = {"version": 1, "nodes": [{"id": "N1"}]}
    assert write_yaml_if_changed(path, payload) is True
    hash_path = path.with_name(path.name + ".content-hash")
    assert hash_path.is_file()
    mtime = path.stat().st_mtime_ns
    assert write_yaml_if_changed(path, payload) is False
    assert path.stat().st_mtime_ns == mtime


def test_write_yaml_if_changed_writes_on_delta(tmp_path: Path) -> None:
    path = tmp_path / "ir" / "bridge.yaml"
    assert write_yaml_if_changed(path, {"version": 1, "nodes": []}) is True
    assert write_yaml_if_changed(path, {"version": 1, "nodes": [{"id": "B1"}]}) is True
    doc = read_yaml(path)
    assert len(doc.get("nodes") or []) == 1


def test_plain_write_yaml_invalidates_content_hash_sidecar(tmp_path: Path) -> None:
    path = tmp_path / "ir" / "operator_graph.yaml"
    payload = {"version": 1, "nodes": [{"id": "N1"}]}
    assert write_yaml_if_changed(path, payload) is True
    hash_path = path.with_name(path.name + ".content-hash")
    assert hash_path.is_file()
    # Out-of-band rewrite must drop sidecar so the next if_changed cannot skip.
    write_yaml(path, {"version": 1, "nodes": [{"id": "N2"}]})
    assert not hash_path.is_file()
    assert write_yaml_if_changed(path, payload) is True
    assert read_yaml(path).get("nodes") == [{"id": "N1"}]


def test_stale_sidecar_cannot_skip_wrong_yaml(tmp_path: Path) -> None:
    """YAML replaced but sidecar not → must not skip on next write."""
    path = tmp_path / "ir" / "graph.yaml"
    payload = {"version": 1, "nodes": [{"id": "N1"}]}
    assert write_yaml_if_changed(path, payload) is True
    hash_path = path.with_name(path.name + ".content-hash")
    sidecar_text = hash_path.read_text(encoding="utf-8")
    # Simulate crash: YAML replaced, sidecar left pointing at old desired hash.
    path.write_text("version: 1\nnodes: [{id: CORRUPT}]\n", encoding="utf-8")
    hash_path.write_text(sidecar_text, encoding="utf-8")
    assert write_yaml_if_changed(path, payload) is True
    assert read_yaml(path).get("nodes") == [{"id": "N1"}]


def test_sidecar_actual_yaml_sha_mismatch_rewrites(tmp_path: Path) -> None:
    path = tmp_path / "ir" / "graph.yaml"
    payload = {"version": 1, "x": 1}
    assert write_yaml_if_changed(path, payload) is True
    hash_path = path.with_name(path.name + ".content-hash")
    # External modify YAML while leaving sidecar desired hash intact but wrong actual sha.
    path.write_text("version: 1\nx: 99\n", encoding="utf-8")
    # Keep sidecar claiming the original desired digest + wrong actual sha.
    desired = _stable_payload_hash(payload)
    hash_path.write_text(
        f"schema_version: 1\ndesired_content_hash: {desired}\nactual_yaml_sha256: {'0' * 64}\n",
        encoding="utf-8",
    )
    assert write_yaml_if_changed(path, payload) is True
    assert read_yaml(path).get("x") == 1
