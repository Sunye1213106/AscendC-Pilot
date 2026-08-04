from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from typing import Any

from .io import read_yaml
from .validation import OPTIONAL_KB_EXPORT_FILES, REQUIRED_KB_EXPORT_FILES


class UnderstandExportError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


def add_understand_to_path(repo_root: Path) -> None:
    candidates = [
        repo_root / "understand-operator" / "understand-operator-plugin",
        repo_root.parent / "understand-operator" / "understand-operator-plugin",
        Path.cwd() / "understand-operator" / "understand-operator-plugin",
        # AscendC-Pilot-upload layout
        repo_root.parent / "AscendC-Pilot-upload" / "understand-operator" / "understand-operator-plugin",
        Path(r"d:\PR-review\AscendC-Pilot-upload\understand-operator\understand-operator-plugin"),
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


def understand_root(project_root: Path, op_name: str, *, arch: str | None = None) -> Path:
    del op_name
    try:
        from ascendc_pilot.paths import uo_root

        return uo_root(project_root, arch=arch)
    except Exception:
        arch_name = (arch or "").strip() or "arch35"
        return project_root / ".ascendc-pilot" / arch_name / "uo"


def built_kb_ready(uo_root: Path) -> bool:
    """KB ready when layered export + quality + tiling materialize exist."""
    required = (
        uo_root / "manifest.yaml",
        uo_root / "quality.yaml",
        uo_root / "tiling" / "key_space.yaml",
        uo_root / "tiling" / "exhaustive_key_space.yaml",
        uo_root / "tiling" / "coverage_model.yaml",
        uo_root / "kernel" / "branches.yaml",
    )
    if not all(path.is_file() for path in required):
        return False
    integrity_path = uo_root / "checks" / "integrity.yaml"
    if integrity_path.is_file():
        integrity = read_yaml(integrity_path)
        if isinstance(integrity, dict) and str(integrity.get("status") or "").lower() == "fail":
            return False
    exhaustive = read_yaml(uo_root / "tiling" / "exhaustive_key_space.yaml")
    coverage = read_yaml(uo_root / "tiling" / "coverage_model.yaml")
    if not isinstance(exhaustive, dict) or not (exhaustive.get("template_blocks") or []):
        return False
    if not isinstance(coverage, dict) or not (coverage.get("key_field_obligations") or {}):
        return False
    if (uo_root / "checks" / "artifact_hashes.yaml").is_file():
        return True
    if (uo_root / "indexes" / "kb_graph.sqlite").is_file():
        return True
    return all((uo_root / Path(rel)).is_file() for rel in REQUIRED_KB_EXPORT_FILES)


def load_built_kb(uo_root: Path, op_name: str) -> dict[str, Any]:
    """Load a pre-built Understand KB from disk. No understand_operator plugin required."""
    if not built_kb_ready(uo_root):
        raise UnderstandExportError(
            "BUILT_KB_MISSING",
            f"Pre-built KB incomplete under {uo_root} (need manifest/quality/tiling/kernel; not UO contracts)",
        )

    files: dict[str, Any] = {}
    missing: list[str] = []
    for rel in REQUIRED_KB_EXPORT_FILES:
        path = uo_root / Path(rel)
        if not path.is_file():
            missing.append(rel)
            continue
        files[rel] = read_yaml(path)

    # Optional legacy residue (UO no longer writes key_cards by default).
    key_cards_dir = uo_root / "tiling" / "key_cards"
    if key_cards_dir.is_dir():
        for path in sorted(key_cards_dir.glob("*.yaml")):
            files[f"tiling/key_cards/{path.name}"] = read_yaml(path)

    for optional in (
        "manifest.yaml",
        "registry/aliases.yaml",
        "registry/variables.yaml",
        "query/terminology.yaml",
        "tiling/key_predicates.yaml",
        "checks/final.yaml",
        "checks/artifact_hashes.yaml",
        "checks/integrity.yaml",
        "ir/operator_graph.yaml",
        "ir/input_derivable.yaml",
        "summary/keys_table.yaml",
        *OPTIONAL_KB_EXPORT_FILES,
    ):
        path = uo_root / Path(optional)
        if path.is_file():
            files[optional] = read_yaml(path)

    if missing:
        raise UnderstandExportError(
            "BUILT_KB_INCOMPLETE",
            "Pre-built KB missing required files: " + ", ".join(missing),
        )

    # Never load historical UO contracts into intake authority.
    context_slice = _context_slice_from_files(files, {})
    return {
        "op_name": op_name,
        "uo_root": uo_root.as_posix(),
        "view": "kb-export",
        "files": files,
        "context_slice": context_slice,
        "intake_mode": "built_kb_filesystem",
    }


def synth_final_validation(uo_root: Path, export_payload: dict[str, Any]) -> dict[str, Any]:
    """Synthesize final-validation report from built KB artifacts (no plugin)."""
    files = export_payload.get("files") if isinstance(export_payload.get("files"), dict) else {}
    quality = files.get("quality.yaml") if isinstance(files.get("quality.yaml"), dict) else {}
    hashes = _load_source_hashes(uo_root, {}, files)
    if not hashes:
        hashes = {rel: _file_sha256(uo_root / Path(rel)) for rel in files if (uo_root / Path(rel)).is_file()}
    status = str(quality.get("status") or quality.get("quality_status") or "pass")
    entities = export_payload.get("context_slice", {}).get("entities") if isinstance(export_payload.get("context_slice"), dict) else []
    final_doc = files.get("checks/final.yaml") if isinstance(files.get("checks/final.yaml"), dict) else {}
    if final_doc.get("status") in {"pass", "warn", "fail"}:
        status = str(final_doc.get("status"))
    return {
        "status": status if status in {"pass", "warn", "fail"} else "pass",
        "phase": "final",
        "issues": [],
        "source_artifact_hashes": dict(sorted(hashes.items())),
        "entity_count": len(entities or []),
        "relation_count": 0,
        "unresolved_count": 0,
        "conflict_count": 0,
        "intake_mode": "built_kb_filesystem",
        "manifest_ok": (uo_root / "manifest.yaml").is_file(),
    }


def _load_source_hashes(uo_root: Path, contract: dict[str, Any], files: dict[str, Any]) -> dict[str, str]:
    """Prefer checks/artifact_hashes.yaml. Legacy contract hashes ignored."""
    del contract  # retired UO contract path
    artifact = files.get("checks/artifact_hashes.yaml")
    if isinstance(artifact, dict) and isinstance(artifact.get("hashes"), dict):
        return {str(k): str(v) for k, v in artifact["hashes"].items()}

    path = uo_root / "checks" / "artifact_hashes.yaml"
    if path.is_file():
        payload = read_yaml(path)
        if isinstance(payload, dict) and isinstance(payload.get("hashes"), dict):
            return {str(k): str(v) for k, v in payload["hashes"].items()}
    return {}


def run_final_validation(project_root: Path, op_name: str, uo_root: Path) -> dict[str, Any]:
    # Prefer pre-built KB: do not require understand_operator plugin.
    if built_kb_ready(uo_root):
        export_payload = load_built_kb(uo_root, op_name)
        return synth_final_validation(uo_root, export_payload)

    add_understand_to_path(project_root)
    try:
        from understand_operator._operator.kb_compiler import validate_kb
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            f"Understand final validation unavailable and no pre-built KB at {uo_root}: {exc}"
        ) from exc

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
    # Prefer pre-built on-disk KB (user already built knowledge base).
    if built_kb_ready(uo_root):
        return load_built_kb(uo_root, op_name)

    add_understand_to_path(project_root)
    try:
        from understand_operator.scripts.kb_query_export import export_context_slice, export_view
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            f"uo-kb-export unavailable and no pre-built KB at {uo_root}: {exc}"
        ) from exc

    try:
        contract_view = export_view(uo_root, op_name, "testcase-contract")
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        raise UnderstandExportError("CONTRACT_VIEW_EXPORT_FAILED", str(exc)) from exc

    try:
        context_slice = export_context_slice(uo_root, op_name, view="testcase-contract", detail_level="full")
    except (ImportError, AttributeError) as exc:
        raise UnderstandExportError("CONTEXT_EXPORT_FAILED", f"Full context API is unavailable: {exc}") from exc
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        raise UnderstandExportError("CONTEXT_EXPORT_FAILED", str(exc)) from exc

    files = contract_view.get("files") if isinstance(contract_view.get("files"), dict) else {}
    files.pop("contracts/testcase.yaml", None)

    return {
        "op_name": op_name,
        "uo_root": uo_root.as_posix(),
        "view": "kb-export",
        "files": files,
        "context_slice": context_slice if isinstance(context_slice, dict) else {},
        "intake_mode": "plugin_export",
    }


def _context_slice_from_files(files: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    del contract  # TG owns testcase contract; context slice is KB entities only
    entities: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(entity_id: str, **extra: Any) -> None:
        if not entity_id or entity_id in seen:
            return
        seen.add(entity_id)
        entities.append({"id": entity_id, "stable_id": entity_id, **extra})

    for item in _iter_dicts(_as_dict(files.get("tiling/families.yaml")).get("families")):
        add(str(item.get("id") or item.get("family_id") or ""), kind="family")
    for item in _iter_dicts(_as_dict(files.get("kernel/paths.yaml")).get("kernel_paths") or _as_dict(files.get("kernel/paths.yaml")).get("paths")):
        add(str(item.get("id") or item.get("stable_id") or ""), kind="kernel_path")
    for item in _iter_dicts(_as_dict(files.get("kernel/branches.yaml")).get("branches")):
        add(str(item.get("id") or item.get("branch_id") or ""), kind="kernel_branch", data_type="bool")
    for item in _iter_dicts(_as_dict(files.get("tiling/variables.yaml")).get("variables")):
        vid = str(item.get("id") or item.get("stable_id") or "")
        if vid:
            add(vid, kind="variable", data_type=item.get("data_type") or item.get("type"), domain=item.get("domain") or item.get("values"))
    for key, card in files.items():
        if isinstance(key, str) and key.startswith("tiling/key_cards/") and isinstance(card, dict):
            cid = str(card.get("id") or Path(key).stem)
            add(cid, kind="key_field", domain=card.get("domain"), data_type="int")

    # Coverage family refs
    for item in _iter_dicts(_as_dict(files.get("tiling/coverage_model.yaml")).get("family_obligations")):
        add(str(item.get("family_id") or item.get("id") or ""), kind="family")

    return {
        "view": "kb-export",
        "entities": entities,
        "testcase_contract": None,
        "intake_mode": "built_kb_filesystem",
    }


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _iter_dicts(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        out = []
        for key, item in value.items():
            if isinstance(item, dict):
                out.append({"id": str(key), **item} if "id" not in item else item)
            else:
                out.append({"id": str(key), "value": item})
        return out
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
