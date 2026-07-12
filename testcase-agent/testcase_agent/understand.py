from __future__ import annotations

import sys
from pathlib import Path
from typing import Any


def add_understand_to_path(repo_root: Path) -> None:
    candidates = [
        repo_root / "understand-operator" / "understand-operator-plugin",
        repo_root.parent / "understand-operator" / "understand-operator-plugin",
    ]
    for candidate in candidates:
        if candidate.exists() and str(candidate) not in sys.path:
            sys.path.insert(0, str(candidate))


def safe_op_name(project_root: Path, op_name: str) -> str:
    add_understand_to_path(project_root)
    try:
        from understand_operator._operator.artifacts import safe_op_name as _safe_op_name

        return _safe_op_name(op_name, project_root)
    except Exception:
        return "".join(ch for ch in op_name if ch.isalnum() or ch in {"_", "-", "."}).strip(".") or op_name


def understand_root(project_root: Path, op_name: str) -> Path:
    return project_root / ".understand-operator" / op_name


def run_final_validation(project_root: Path, op_name: str, uo_root: Path) -> dict[str, Any]:
    add_understand_to_path(project_root)
    try:
        from understand_operator._operator.kb_compiler import validate_kb
    except Exception as exc:  # pragma: no cover - only hit when dependency is missing in user env
        raise RuntimeError(f"Understand final validation is unavailable: {exc}") from exc

    result = validate_kb(uo_root, op_name, phase="final", write_outputs=False)
    return {
        "status": result.status,
        "phase": result.phase,
        "issues": [issue.to_dict() for issue in result.issues],
        "source_artifact_hashes": dict(sorted(result.artifact_hashes.items())),
        "entity_count": result.entity_count,
        "relation_count": result.relation_count,
        "unresolved_count": result.unresolved_count,
        "conflict_count": result.conflict_count,
    }


def export_testcase_contract(project_root: Path, op_name: str, uo_root: Path) -> dict[str, Any]:
    add_understand_to_path(project_root)
    try:
        from understand_operator.scripts.kb_query_export import export_context_slice

        payload = export_context_slice(uo_root, op_name, view="testcase-contract", detail_level="full")
        if isinstance(payload, dict) and "files" in payload:
            payload.setdefault("context_slice", {key: payload.get(key) for key in ("testcase_contract", "entities", "relations", "upstream", "downstream", "paths", "evidence", "unresolved", "conflicts", "source_artifacts") if key in payload})
            return payload
        if isinstance(payload, dict):
            contract = payload.get("testcase_contract") or payload.get("contract") or {}
            return {
                "op_name": op_name,
                "uo_root": uo_root.as_posix(),
                "view": "testcase-contract",
                "context_slice": payload,
                "files": {
                    "contracts/testcase.yaml": contract,
                    "__context_slice__": payload,
                },
            }
    except Exception:
        pass
    try:
        from understand_operator.scripts.kb_query_export import export_view
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(f"uo-kb-export testcase-contract view is unavailable: {exc}") from exc
    try:
        return export_view(uo_root, op_name, "testcase-contract")
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"testcase-contract export failed: {exc}") from exc
