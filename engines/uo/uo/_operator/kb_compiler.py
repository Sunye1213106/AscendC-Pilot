from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]


@dataclass
class Issue:
    code: str
    severity: str
    message: str
    path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "severity": self.severity, "message": self.message, "path": self.path}


@dataclass
class ValidateResult:
    status: str
    phase: str
    issues: list[Issue] = field(default_factory=list)
    artifact_hashes: dict[str, str] = field(default_factory=dict)
    entity_count: int = 0
    relation_count: int = 0
    unresolved_count: int = 0
    conflict_count: int = 0


def validate_kb(uo_root: Path, op_name: str, phase: str = "final", write_outputs: bool = False) -> ValidateResult:
    if yaml is None:
        return ValidateResult(status="fail", phase=phase, issues=[Issue("PYYAML_MISSING", "error", "PyYAML is required")])

    uo_root = Path(uo_root)
    issues: list[Issue] = []
    graph_path = uo_root / "ir" / "operator_graph.yaml"
    if not graph_path.exists():
        issues.append(Issue("OPERATOR_GRAPH_MISSING", "error", "ir/operator_graph.yaml missing", graph_path.as_posix()))
    graph = _read(graph_path)
    if graph and graph.get("op_name") not in (None, op_name) and str(graph.get("op_name")) != op_name:
        issues.append(Issue("OP_NAME_MISMATCH", "warning", f"graph op_name={graph.get('op_name')} expected={op_name}"))

    nodes = graph.get("nodes") if isinstance(graph.get("nodes"), list) else []
    edges = graph.get("edges") if isinstance(graph.get("edges"), list) else []
    unresolved = graph.get("unresolved") if isinstance(graph.get("unresolved"), list) else []
    if not nodes:
        issues.append(Issue("EMPTY_GRAPH_NODES", "error", "operator_graph has no nodes"))
    if not any(n.get("layer") == "host" for n in nodes):
        issues.append(Issue("HOST_LAYER_MISSING", "error", "no host-layer nodes"))
    if not any(n.get("layer") == "kernel" for n in nodes):
        issues.append(Issue("KERNEL_LAYER_MISSING", "warning", "no kernel-layer nodes"))
    if not any(n.get("node_type") == "TilingKey" for n in nodes):
        issues.append(Issue("TILINGKEY_BRIDGE_MISSING", "error", "no TilingKey bridge node"))

    tiling = graph.get("tilingkey") or {}
    if int(tiling.get("args_sel_count") or 0) <= 0:
        issues.append(Issue("TILINGKEY_SEL_EMPTY", "warning", "args_sel_count is 0"))

    # contracts/testcase.yaml is retired (TG-owned). Historical residue is ignored.

    required_exports = [
        uo_root / "tiling" / "key_space.yaml",
        uo_root / "tiling" / "exhaustive_key_space.yaml",
        uo_root / "tiling" / "coverage_model.yaml",
        uo_root / "kernel" / "branches.yaml",
        uo_root / "cross_layer" / "impact_graph.yaml",
        uo_root / "quality.yaml",
    ]
    for path in required_exports:
        if not path.exists():
            issues.append(Issue("EXPORT_MISSING", "error", f"missing export {path.relative_to(uo_root)}", path.as_posix()))

    conflict_count = sum(1 for item in unresolved if str(item.get("kind") or "").startswith("missing_") or str(item.get("kind") or "").startswith("unused_"))
    hashes = {}
    for rel in (
        "ir/operator_graph.yaml",
        "ir/input_derivable.yaml",
        "tiling/key_space.yaml",
        "tiling/exhaustive_key_space.yaml",
        "tiling/coverage_model.yaml",
        "kernel/branches.yaml",
        "cross_layer/impact_graph.yaml",
        "quality.yaml",
    ):
        path = uo_root / rel
        if path.exists():
            hashes[rel] = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()

    error_count = sum(1 for issue in issues if issue.severity == "error")
    status = "pass" if error_count == 0 else "fail"
    result = ValidateResult(
        status=status,
        phase=phase,
        issues=issues,
        artifact_hashes=hashes,
        entity_count=len(nodes),
        relation_count=len(edges),
        unresolved_count=len(unresolved),
        conflict_count=conflict_count,
    )
    if write_outputs:
        out = uo_root / "checks" / "final.yaml"
        out.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "status": result.status,
            "phase": result.phase,
            "entity_count": result.entity_count,
            "relation_count": result.relation_count,
            "unresolved_count": result.unresolved_count,
            "conflict_count": result.conflict_count,
            "source_artifact_hashes": result.artifact_hashes,
            "issues": [issue.to_dict() for issue in result.issues],
        }
        out.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return result


def _read(path: Path) -> dict[str, Any]:
    if yaml is None or not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}
