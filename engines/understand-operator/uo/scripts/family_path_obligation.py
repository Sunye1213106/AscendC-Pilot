"""Family → kernel_path → obligation consistency (UO export surface).

Used by Pilot/TG gates so every FAM/KPATH obligation ref is locally consistent.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from uo.scripts._ir_io import read_yaml, write_yaml


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _iter_items(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [x for x in value if isinstance(x, dict)]
    if isinstance(value, dict):
        for key in ("items", "obligations", "families", "kernel_paths", "paths"):
            if isinstance(value.get(key), list):
                return [x for x in value[key] if isinstance(x, dict)]
    return []


def build_family_path_index_from_uo(uo_root: Path) -> dict[str, set[str]]:
    """Map KPATH → set(FAM) from UO layered exports."""
    index: dict[str, set[str]] = {}

    def add(path_ref: str, family_ref: str) -> None:
        if path_ref and family_ref:
            index.setdefault(str(path_ref), set()).add(str(family_ref))

    paths_doc = read_yaml(uo_root / "kernel" / "paths.yaml") or {}
    for item in _iter_items(paths_doc.get("kernel_paths") or paths_doc.get("paths") or paths_doc):
        path_ref = str(item.get("id") or item.get("stable_id") or item.get("path_ref") or "")
        for family_ref in _as_list(item.get("family_refs") or item.get("families") or item.get("family_ref")):
            add(path_ref, str(family_ref))

    fam_doc = read_yaml(uo_root / "tiling" / "families.yaml") or {}
    for item in _iter_items(fam_doc.get("families") or fam_doc.get("family_obligations") or fam_doc):
        family_ref = str(item.get("id") or item.get("stable_id") or item.get("family_id") or "")
        for path_ref in _as_list(item.get("kernel_path_refs") or item.get("path_refs") or item.get("paths")):
            add(str(path_ref), family_ref)

    cross = read_yaml(uo_root / "cross_layer" / "tiling_to_kernel.yaml") or {}
    for item in _iter_items(cross.get("edges") or cross.get("relations") or cross.get("mappings") or cross):
        source = str(item.get("source") or item.get("source_ref") or item.get("family_ref") or "")
        target = str(item.get("target") or item.get("target_ref") or item.get("kernel_path_ref") or "")
        relation = str(item.get("relation") or item.get("type") or item.get("kind") or "").casefold()
        if source.startswith("KPATH_") and target.startswith("FAM_"):
            source, target = target, source
        if source.startswith("FAM_") and target.startswith("KPATH_") and (
            not relation
            or relation in {"dispatches_to", "uses_path", "maps_to", "selects", "family_to_path"}
        ):
            add(target, source)
    return index


def check_family_path_obligation(uo_root: Path, *, write: bool = True) -> dict[str, Any]:
    """Validate FAM/KPATH refs used by obligations exist and are cross-linked when both declared."""
    uo_root = Path(uo_root)
    fam_doc = read_yaml(uo_root / "tiling" / "families.yaml") or {}
    paths_doc = read_yaml(uo_root / "kernel" / "paths.yaml") or {}
    cov_doc = read_yaml(uo_root / "coverage" / "obligations.yaml") or {}
    # Fallbacks
    if not cov_doc:
        cov_doc = read_yaml(uo_root / "tiling" / "obligations.yaml") or {}

    families = {
        str(i.get("id") or i.get("stable_id") or i.get("family_id") or "")
        for i in _iter_items(fam_doc.get("families") or fam_doc)
        if str(i.get("id") or i.get("stable_id") or i.get("family_id") or "")
    }
    paths = {
        str(i.get("id") or i.get("stable_id") or i.get("path_ref") or "")
        for i in _iter_items(paths_doc.get("kernel_paths") or paths_doc.get("paths") or paths_doc)
        if str(i.get("id") or i.get("stable_id") or i.get("path_ref") or "")
    }
    index = build_family_path_index_from_uo(uo_root)

    issues: list[dict[str, Any]] = []
    # Missing export surfaces are soft when UO has not exported yet.
    if not families and not paths:
        payload = {
            "version": 1,
            "ok": True,
            "status": "skipped",
            "message": "tiling/families.yaml and kernel/paths.yaml absent; skip until export",
            "issues": [],
            "stats": {"family_count": 0, "path_count": 0, "obligation_count": 0},
        }
        if write:
            (uo_root / "checks").mkdir(parents=True, exist_ok=True)
            write_yaml(uo_root / "checks" / "family_path_obligation.yaml", payload)
        return payload

    obligations = _iter_items(
        cov_doc.get("obligations")
        or cov_doc.get("items")
        or cov_doc.get("family_obligations")
        or cov_doc.get("kernel_paths")
        or cov_doc
    )
    for ob in obligations:
        ob_id = str(ob.get("id") or ob.get("obligation_id") or "?")
        fam_refs = [str(x) for x in _as_list(ob.get("family_refs") or ob.get("families") or [])]
        path_refs = [
            str(x)
            for x in _as_list(ob.get("kernel_path_refs") or ob.get("path_refs") or ob.get("target_refs") or [])
            if str(x).startswith("KPATH_") or "PATH" in str(x).upper()
        ]
        # Also treat kind=kernel_path target_refs
        if str(ob.get("kind") or "") == "kernel_path":
            path_refs.extend(str(x) for x in _as_list(ob.get("target_refs") or []))
        if str(ob.get("kind") or "") == "family":
            fam_refs.extend(str(x) for x in _as_list(ob.get("target_refs") or []))

        for fr in fam_refs:
            if families and fr and fr not in families:
                issues.append(
                    {
                        "code": "FAM_REF_UNKNOWN",
                        "obligation_id": ob_id,
                        "family_ref": fr,
                        "severity": "error",
                        "message": f"obligation {ob_id} references unknown family {fr}",
                    }
                )
        for pr in path_refs:
            if paths and pr and pr not in paths:
                issues.append(
                    {
                        "code": "KPATH_REF_UNKNOWN",
                        "obligation_id": ob_id,
                        "kernel_path_ref": pr,
                        "severity": "error",
                        "message": f"obligation {ob_id} references unknown kernel_path {pr}",
                    }
                )
        # When both sides declared, require index compatibility.
        for fr in fam_refs:
            for pr in path_refs:
                if not fr or not pr or not index:
                    continue
                allowed = index.get(pr)
                if allowed is not None and fr not in allowed:
                    issues.append(
                        {
                            "code": "FAM_PATH_INCOMPATIBLE",
                            "obligation_id": ob_id,
                            "family_ref": fr,
                            "kernel_path_ref": pr,
                            "severity": "error",
                            "message": f"obligation {ob_id}: {fr} not linked to {pr} in family/path index",
                        }
                    )

    # Structural: every path with family_refs must reference known families.
    for item in _iter_items(paths_doc.get("kernel_paths") or paths_doc.get("paths") or []):
        path_ref = str(item.get("id") or "")
        for fr in _as_list(item.get("family_refs") or []):
            if families and str(fr) not in families:
                issues.append(
                    {
                        "code": "PATH_FAM_REF_UNKNOWN",
                        "kernel_path_ref": path_ref,
                        "family_ref": str(fr),
                        "severity": "error",
                        "message": f"path {path_ref} references unknown family {fr}",
                    }
                )

    errors = [i for i in issues if i.get("severity") == "error"]
    payload = {
        "version": 1,
        "ok": not errors,
        "status": "pass" if not errors else "fail",
        "message": "ok" if not errors else f"family/path/obligation issues={len(errors)}",
        "issues": issues,
        "stats": {
            "family_count": len(families),
            "path_count": len(paths),
            "obligation_count": len(obligations),
            "index_edges": sum(len(v) for v in index.values()),
            "error_count": len(errors),
        },
    }
    if write:
        (uo_root / "checks").mkdir(parents=True, exist_ok=True)
        write_yaml(uo_root / "checks" / "family_path_obligation.yaml", payload)
    return payload
