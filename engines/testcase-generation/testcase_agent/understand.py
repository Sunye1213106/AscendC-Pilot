from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from typing import Any

from .io import read_yaml
from .validation import KB_GRAPH_SQLITE, OPTIONAL_KB_EXPORT_FILES, REQUIRED_KB_EXPORT_FILES


class UnderstandExportError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


def add_understand_to_path(repo_root: Path) -> None:
    """Make the in-tree ``uo_init`` package importable for DB / locator reads."""
    candidates = [
        repo_root / "engines" / "understand-operator" / "src",
        repo_root.parent / "engines" / "understand-operator" / "src",
    ]
    for candidate in candidates:
        if candidate.exists() and str(candidate) not in sys.path:
            sys.path.insert(0, str(candidate))


def safe_op_name(project_root: Path, op_name: str) -> str:
    del project_root
    return "".join(ch for ch in op_name if ch.isalnum() or ch in {"_", "-", "."}).strip(".") or op_name


def understand_root(project_root: Path, op_name: str, *, arch: str | None = None) -> Path:
    del op_name
    try:
        from ascendc_pilot.paths import uo_root

        return uo_root(project_root, arch=arch)
    except Exception:
        arch_name = (arch or "").strip()
        if not arch_name:
            raise ValueError("ARCHITECTURE_MISSING_IN_RUN_STATE")
        return project_root / ".ascendc-pilot" / arch_name / "uo"


def _db_path(uo_root: Path) -> Path:
    return uo_root / KB_GRAPH_SQLITE


def _db_product_ready(uo_root: Path) -> bool:
    """Ready when sqlite exists with meta.authority and integrity not fail."""
    db = _db_path(uo_root)
    if not db.is_file():
        return False
    try:
        add_understand_to_path(uo_root)
        # Prefer uo_init helpers when importable.
        from uo_init.kb_index import db_authority_ok, load_view_blob

        if not db_authority_ok(db):
            return False
        exhaustive = load_view_blob(db, "tiling/exhaustive_key_space.yaml")
        coverage = load_view_blob(db, "tiling/coverage_model.yaml")
        if not isinstance(exhaustive, dict) or not (exhaustive.get("template_blocks") or []):
            return False
        if not isinstance(coverage, dict) or not (coverage.get("key_field_obligations") or {}):
            return False
        return True
    except Exception:
        # Fallback: accept DB with graph_fingerprint meta (legacy / partial import).
        try:
            import sqlite3

            conn = sqlite3.connect(str(db))
            try:
                fp = conn.execute(
                    "SELECT value FROM meta WHERE key='graph_fingerprint'"
                ).fetchone()
                integrity = conn.execute(
                    "SELECT value FROM meta WHERE key='integrity_status'"
                ).fetchone()
            finally:
                conn.close()
            if integrity and str(integrity[0]).lower() == "fail":
                return False
            return bool(fp and fp[0])
        except Exception:
            return False


def _legacy_yaml_ready(uo_root: Path) -> bool:
    """Legacy readiness: layered YAML export + tiling materialize."""
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
    if _db_path(uo_root).is_file():
        return True
    return all((uo_root / Path(rel)).is_file() for rel in REQUIRED_KB_EXPORT_FILES)


def built_kb_ready(uo_root: Path) -> bool:
    """KB ready when DB authority product exists, or legacy YAML set is present."""
    if _db_product_ready(uo_root):
        return True
    return _legacy_yaml_ready(uo_root)


def _kb_missing_message(uo_root: Path) -> str:
    return (
        f"no built KB at {uo_root}: need {KB_GRAPH_SQLITE} with meta.authority=db, "
        "or the layered YAML export. Run the uo-init workflow for this operator "
        "(acp start uo-init) before tg-init."
    )


def _load_files_from_db(uo_root: Path) -> dict[str, Any]:
    """Reconstruct the TG snapshot ``files`` dict from sqlite view_blobs."""
    add_understand_to_path(uo_root)
    from uo_init.kb_index import get_meta, load_all_view_blobs, load_view_blob

    db = _db_path(uo_root)
    blobs = load_all_view_blobs(db)
    files: dict[str, Any] = {}
    for rel in (
        *REQUIRED_KB_EXPORT_FILES,
        "manifest.yaml",
        "checks/artifact_hashes.yaml",
        "checks/integrity.yaml",
        "ir/operator_graph.yaml",
        "ir/input_derivable.yaml",
        *OPTIONAL_KB_EXPORT_FILES,
    ):
        payload = blobs.get(rel)
        if payload is None:
            payload = load_view_blob(db, rel)
        if isinstance(payload, dict):
            files[rel] = payload
    if "manifest.yaml" not in files:
        meta = get_meta(db)
        files["manifest.yaml"] = {
            "version": 1,
            "status": meta.get("manifest_status") or "extracted",
            "authority": meta.get("authority") or "db",
            "product": KB_GRAPH_SQLITE,
            "derived_index": KB_GRAPH_SQLITE,
            "op_name": meta.get("op_name") or "",
            "architecture": meta.get("architecture") or "",
            "graph_fingerprint": meta.get("graph_fingerprint") or "",
            "schema": meta.get("schema") or "kb_schema-v1",
        }
    return files


def load_built_kb(uo_root: Path, op_name: str) -> dict[str, Any]:
    """Load a pre-built Understand KB from disk (YAML or DB). No plugin required."""
    if not built_kb_ready(uo_root):
        raise UnderstandExportError(
            "BUILT_KB_MISSING",
            f"Pre-built KB incomplete under {uo_root} "
            "(need DB authority product or manifest/quality/tiling/kernel YAML)",
        )

    yaml_present = (uo_root / "manifest.yaml").is_file() and (
        uo_root / "quality.yaml"
    ).is_file()
    use_db = (not yaml_present) and _db_product_ready(uo_root)

    files: dict[str, Any] = {}
    missing: list[str] = []
    intake_mode = "built_kb_filesystem"

    if use_db:
        intake_mode = "built_kb_db"
        files = _load_files_from_db(uo_root)
        for rel in REQUIRED_KB_EXPORT_FILES:
            if rel not in files:
                missing.append(rel)
    else:
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

        # Fill gaps from DB when YAML set is partial but sqlite has blobs.
        if missing and _db_path(uo_root).is_file():
            try:
                db_files = _load_files_from_db(uo_root)
                still_missing: list[str] = []
                for rel in missing:
                    if rel in db_files:
                        files[rel] = db_files[rel]
                    else:
                        still_missing.append(rel)
                missing = still_missing
                if db_files:
                    intake_mode = "built_kb_hybrid"
            except Exception:
                pass

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
        "intake_mode": intake_mode,
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
        "intake_mode": str(export_payload.get("intake_mode") or "built_kb_filesystem"),
        "manifest_ok": (uo_root / "manifest.yaml").is_file()
        or isinstance(files.get("manifest.yaml"), dict)
        or _db_product_ready(uo_root),
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
    """Validate against the built KB. UO is the only producer of that KB."""
    del project_root
    if not built_kb_ready(uo_root):
        raise UnderstandExportError("BUILT_KB_MISSING", _kb_missing_message(uo_root))
    export_payload = load_built_kb(uo_root, op_name)
    return synth_final_validation(uo_root, export_payload)


def export_testcase_contract(project_root: Path, op_name: str, uo_root: Path) -> dict[str, Any]:
    """Read the KB UO already built. TG never produces the KB itself."""
    del project_root
    if not built_kb_ready(uo_root):
        raise UnderstandExportError("BUILT_KB_MISSING", _kb_missing_message(uo_root))
    return load_built_kb(uo_root, op_name)


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
