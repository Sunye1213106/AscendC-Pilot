from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]


def build_update_plan(change_set: dict[str, Any], base: Path | None = None) -> dict[str, Any]:
    files = [f.lower().replace("\\", "/") for f in change_set.get("changed_files") or []]
    symbols = [s.lower() for s in change_set.get("changed_symbols") or []]
    blob = " ".join(files + symbols)

    areas: list[str] = []
    phases: list[str] = []
    invalidations: dict[str, list[str]] = {}

    def hit(*needles: str) -> bool:
        return any(n in blob for n in needles)

    if hit("proto", "op_api", "acl_op", "operator_io", "def.cpp", "def.h"):
        areas.append("boundary_io")
        phases.append("phase1")
        invalidations["operator_interface"] = [
            "operator.yaml",
            "registry/symbols.yaml",
            "registry/variables.yaml",
            "contracts/query.yaml",
        ]
    if hit("tiling", "op_host", "tilingdata", "tiling_key"):
        areas.append("tiling_host")
        phases.append("phase2_host")
        invalidations["host_tiling"] = [
            "tiling/variables.yaml",
            "tiling/constraints.yaml",
            "tiling/key_space.yaml",
            "tiling/families.yaml",
            "tiling/data_model.yaml",
            "registry/variables.yaml",
            "cross_layer/input_to_tiling.yaml",
            "cross_layer/variable_lineage.yaml",
        ]
        if _tiling_change_requires_kernel(blob, base, change_set):
            areas.append("kernel_impacted_by_tiling")
            phases.extend(["phase3", "phase3.5", "phase4", "phase5"])
            invalidations["kernel_from_tiling"] = [
                "kernel/compile_model.yaml",
                "kernel/variables.yaml",
                "kernel/paths.yaml",
                "kernel/branches.yaml",
                "kernel/pipeline.yaml",
                "kernel/resources.yaml",
                "cross_layer/tiling_to_kernel.yaml",
                "cross_layer/impact_graph.yaml",
                "cross_layer/behavior_graph.yaml",
                "contracts/testcase.yaml",
            ]
        else:
            areas.append("tilingdata_numeric_local")
            invalidations["tilingdata_numeric_local"] = [
                "tiling/data_model.yaml",
                "flow/numerical_model.yaml",
            ]
    if hit("datacopy", "setflag", "waitflag", "pipe_", "dataflow", "compute"):
        areas.append("compute_dataflow")
        phases.append("phase2_flow")
        invalidations["flow_dataflow"] = [
            "flow/compute_graph.yaml",
            "flow/dataflow.yaml",
            "flow/golden_model.yaml",
            "flow/numerical_model.yaml",
            "cross_layer/behavior_graph.yaml",
        ]
    if hit("op_kernel", "kernel", "process(", "init("):
        areas.append("kernel")
        phases.extend(["phase3", "phase3.5", "phase4", "phase5"])
        invalidations["kernel"] = [
            "kernel/compile_model.yaml",
            "kernel/variables.yaml",
            "kernel/paths.yaml",
            "kernel/branches.yaml",
            "kernel/pipeline.yaml",
            "kernel/resources.yaml",
            "cross_layer/tiling_to_kernel.yaml",
            "cross_layer/behavior_graph.yaml",
            "cross_layer/impact_graph.yaml",
        ]
    if hit("golden", "test", "accuracy"):
        areas.append("test_contract")
        phases.append("phase7")
        invalidations["test_contract"] = [
            "test/contract.yaml",
            "contracts/testcase.yaml",
            "contracts/pr_review.yaml",
        ]

    if not areas and change_set.get("status") != "empty":
        areas.append("unknown_needs_review")
        phases.extend(["phase1", "phase2_host", "phase2_flow"])
        invalidations["unknown_needs_review"] = [
            "operator.yaml",
            "registry/symbols.yaml",
            "registry/variables.yaml",
            "cross_layer/impact_graph.yaml",
        ]

    phases = _unique(phases)
    if phases:
        phases.extend(["phase6", "phase7", "phase8"])
        phases = _unique(phases)

    derived_stale = _derived_stale_from_invalidations(invalidations)
    graph_impacts = _impact_graph_invalidations(change_set, base)
    if graph_impacts:
        invalidations["behavior_graph_dependency"] = graph_impacts
        derived_stale = sorted(set(derived_stale) | set(graph_impacts))
    return {
        "version": 1,
        "status": "planned",
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
        "impacted_areas": areas,
        "phases_to_rerun": phases,
        "artifact_invalidations": invalidations,
        "derived_views_to_mark_stale": derived_stale,
        "stale_classification": _stale_classification(invalidations, derived_stale),
        "dependency_hash": _dependency_hash(change_set),
        "generator_version": "understand-operator-update-v2",
        "preserve_untouched_artifacts": True,
        "full_rebuild_recommended": False,
        "notes": [
            "Agent should re-run only listed phases using the same prompts as /uo-init.",
            "Keep human review gates when boundary or kernel dispatch plans change.",
            "Source lookups remain CBM-first; whole-file Read only after CBM failure.",
            "Only the deterministic KB compiler should promote proposal/intermediate artifacts into canonical v2 slices.",
        ],
    }


def build_stale_artifacts(update_plan: dict[str, Any]) -> dict[str, Any]:
    now = datetime.now(tz=timezone.utc).isoformat()
    artifacts = sorted(
        {
            item
            for values in (update_plan.get("artifact_invalidations") or {}).values()
            for item in (values or [])
        }
        | set(update_plan.get("derived_views_to_mark_stale") or [])
    )
    return {
        "version": 1,
        "created_at": now,
        "dependency_hash": update_plan.get("dependency_hash"),
        "stale_artifacts": [
            {
                "path": artifact,
                "stale": True,
                "owner_phase": _owner_phase_for_artifact(artifact),
                "expected_refresh_run_id": update_plan.get("run_id"),
                "invalidated_by": update_plan.get("dependency_hash"),
                "dependency_hash": update_plan.get("dependency_hash"),
                "old_artifact_hash": None,
                "validation_status": "pending",
                "validated_by_run_id": None,
                "validated_at": None,
                "resolution_reason": None,
                "reason": "source change may affect this KB slice",
                "source_dependencies": [],
                "source_hash_before": None,
                "source_hash_after": None,
                "canonical_hash_before": None,
                "invalidated_at": now,
                "resolved_at": None,
                "resolved_by_run_id": None,
                "must_refresh_before": ["phase6", "phase7", "phase8"]
                if artifact.startswith(("cross_layer/", "contracts/", "query/"))
                else ["owning_phase", "phase6", "phase8"],
            }
            for artifact in artifacts
        ],
        "resolution_history": [],
    }


def tilingdata_numeric_only_proven(base: Path | None, change_set: dict[str, Any] | None = None) -> bool:
    if base is None or yaml is None:
        return False
    field_ids = _resolve_changed_tilingdata_fields(base, change_set or {})
    if not field_ids:
        return False
    data_model = _read_yaml_file(base / "tiling" / "data_model.yaml")
    lineage = _read_yaml_file(base / "cross_layer" / "variable_lineage.yaml")
    impact = _read_yaml_file(base / "cross_layer" / "impact_graph.yaml")
    behavior = _read_yaml_file(base / "cross_layer" / "behavior_graph.yaml")
    for field_id in field_ids:
        field_meta = _find_tilingdata_field_meta(data_model, field_id)
        if not field_meta:
            return False
        impact_class = str(field_meta.get("impact_class") or field_meta.get("impact_scope") or "").strip()
        if impact_class != "numeric_only":
            return False
        if _as_list(field_meta.get("downstream_control_refs")) or _as_list(field_meta.get("downstream_kernel_refs")):
            return False
        if _field_has_non_numeric_downstream(field_id, lineage, impact, behavior):
            return False
    return True


_build_update_plan = build_update_plan
_build_stale_artifacts = build_stale_artifacts
_tilingdata_numeric_only_proven = tilingdata_numeric_only_proven


def _tiling_change_requires_kernel(blob: str, base: Path | None, change_set: dict[str, Any] | None = None) -> bool:
    if any(token in blob for token in ("tiling_key", "family", "template", "dispatch", "kernel_entry")):
        return True
    if "tilingdata" in blob and not any(token in blob for token in ("key", "family", "template", "dispatch")):
        return not tilingdata_numeric_only_proven(base, change_set)
    if "op_host" in blob or "tiling" in blob:
        return True
    return False


def _resolve_changed_tilingdata_fields(base: Path, change_set: dict[str, Any]) -> list[str]:
    symbols = {str(s) for s in change_set.get("changed_symbols") or []}
    files = {str(f).replace("\\", "/") for f in change_set.get("changed_files") or []}
    data_model = _read_yaml_file(base / "tiling" / "data_model.yaml")
    found: list[str] = []
    structs = data_model.get("structs") if isinstance(data_model.get("structs"), dict) else {}
    for struct_name, struct in structs.items():
        fields = struct.get("fields") if isinstance(struct, dict) else {}
        if not isinstance(fields, dict):
            continue
        for field_name, field in fields.items():
            if not isinstance(field, dict):
                continue
            field_id = str(field.get("id") or field.get("stable_id") or f"TDF_{_slug(struct_name)}_{_slug(field_name)}")
            source = field.get("source") if isinstance(field.get("source"), dict) else {}
            src_file = str(source.get("file") or "").replace("\\", "/")
            src_symbol = str(source.get("symbol") or field.get("symbol") or "")
            names = {field_id, field_name, str(field.get("canonical_name") or ""), src_symbol}
            if any(sym and sym in names for sym in symbols) or (src_file and src_file in files):
                found.append(field_id)
            elif any("tilingdata" in f.lower() for f in files) and field.get("impact_class") == "numeric_only":
                found.append(field_id)
    overlay = data_model.get("numeric_overlay") if isinstance(data_model.get("numeric_overlay"), dict) else {}
    for key, item in overlay.items():
        payload = item if isinstance(item, dict) else {}
        field_id = str(payload.get("id") or f"TDF_NUM_{_slug(key)}")
        if field_id not in found and (payload.get("impact_class") == "numeric_only" or any("tilingdata" in f.lower() for f in files)):
            if payload.get("impact_class") == "numeric_only":
                found.append(field_id)
    return sorted(set(found))


def _find_tilingdata_field_meta(data_model: dict[str, Any], field_id: str) -> dict[str, Any] | None:
    structs = data_model.get("structs") if isinstance(data_model.get("structs"), dict) else {}
    for struct_name, struct in structs.items():
        fields = struct.get("fields") if isinstance(struct, dict) else {}
        if not isinstance(fields, dict):
            continue
        for field_name, field in fields.items():
            if not isinstance(field, dict):
                continue
            item_id = str(field.get("id") or field.get("stable_id") or f"TDF_{_slug(struct_name)}_{_slug(field_name)}")
            if item_id == field_id:
                return field
    overlay = data_model.get("numeric_overlay") if isinstance(data_model.get("numeric_overlay"), dict) else {}
    for key, item in overlay.items():
        payload = item if isinstance(item, dict) else {}
        item_id = str(payload.get("id") or f"TDF_NUM_{_slug(key)}")
        if item_id == field_id:
            return payload
    return None


def _field_has_non_numeric_downstream(
    field_id: str,
    lineage: dict[str, Any],
    impact: dict[str, Any],
    behavior: dict[str, Any],
) -> bool:
    control_kinds = {
        "kernel_branch",
        "kernel_path",
        "template_binding",
        "kernel_decision_point",
        "pipeline_stage",
        "buffer",
        "sync",
        "resource",
        "compile_decision",
        "compile_variable",
    }
    control_prefixes = ("KBR_", "KPATH_", "KTPL_", "KDEC_", "PIPE_", "BUF_", "SYNC_", "RES_")
    edges = []
    for doc in (lineage, impact, behavior):
        for section in ("edges", "impacts", "relations", "links", "lineage"):
            value = doc.get(section)
            if isinstance(value, list):
                edges.extend(item for item in value if isinstance(item, dict))
            elif isinstance(value, dict):
                edges.extend(item for item in value.values() if isinstance(item, dict))
    for edge in edges:
        src = str(edge.get("source_id") or edge.get("source") or "")
        dst = str(edge.get("target_id") or edge.get("target") or "")
        sources = [str(x) for x in (edge.get("source_ids") or [])] + ([src] if src else [])
        targets = [str(x) for x in (edge.get("target_ids") or [])] + ([dst] if dst else [])
        if field_id not in sources:
            continue
        for target in targets:
            if target.startswith(control_prefixes):
                return True
            kind = str(edge.get("target_kind") or edge.get("kind") or "")
            if kind in control_kinds:
                return True
    return False


def _impact_graph_invalidations(change_set: dict[str, Any], base: Path | None) -> list[str]:
    if base is None or yaml is None:
        return []
    symbols = {str(s).lower() for s in change_set.get("changed_symbols") or []}
    files = {str(f).lower().replace("\\", "/") for f in change_set.get("changed_files") or []}
    if not symbols and not files:
        return []
    graph = _read_yaml_file(base / "cross_layer" / "impact_graph.yaml")
    impacts = []
    for item in (graph.get("impacts") or graph.get("edges") or []) if isinstance(graph, dict) else []:
        blob = json.dumps(item, ensure_ascii=False).lower()
        if any(sym and sym in blob for sym in symbols) or any(path and path in blob for path in files):
            target = str(item.get("target_id") or item.get("target") or "")
            if target.startswith(("KPATH_", "KTPL_", "KBR_")):
                impacts.extend(["kernel/paths.yaml", "kernel/branches.yaml", "cross_layer/tiling_to_kernel.yaml"])
            elif target.startswith(("VAR_", "KEY_", "FAM_")):
                impacts.extend(["registry/variables.yaml", "cross_layer/variable_lineage.yaml", "cross_layer/behavior_graph.yaml"])
            else:
                impacts.append("cross_layer/impact_graph.yaml")
    return sorted(set(impacts))


def _read_yaml_file(path: Path) -> dict[str, Any]:
    if not path.exists() or yaml is None:
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8", errors="ignore")) or {}
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _stale_classification(invalidations: dict[str, list[str]], derived_stale: list[str]) -> dict[str, list[str]]:
    invalidated = sorted({item for values in invalidations.values() for item in values})
    needs_review = sorted(
        item
        for item in invalidated
        if item.startswith(("kernel/", "cross_layer/")) or item in {"operator.yaml", "registry/variables.yaml"}
    )
    return {
        "invalidated": invalidated,
        "stale": sorted(derived_stale),
        "needs_review": needs_review,
        "safe_to_preserve": [],
        "safe_to_preserve_computed": False,
    }


def _derived_stale_from_invalidations(invalidations: dict[str, list[str]]) -> list[str]:
    stale: set[str] = set()
    for artifacts in invalidations.values():
        blob = " ".join(artifacts)
        if "tiling/" in blob or "operator.yaml" in blob:
            stale.update(
                [
                    "cross_layer/input_to_tiling.yaml",
                    "cross_layer/variable_lineage.yaml",
                    "contracts/testcase.yaml",
                    "query/routes.yaml",
                ]
            )
        if "kernel/" in blob:
            stale.update(
                [
                    "cross_layer/tiling_to_kernel.yaml",
                    "cross_layer/behavior_graph.yaml",
                    "cross_layer/impact_graph.yaml",
                    "contracts/code_change.yaml",
                    "contracts/pr_review.yaml",
                    "contracts/testcase.yaml",
                    "query/routes.yaml",
                ]
            )
        if "flow/" in blob:
            stale.update(["cross_layer/behavior_graph.yaml", "contracts/testcase.yaml", "query/routes.yaml"])
    return sorted(stale)


def _dependency_hash(change_set: dict[str, Any]) -> str:
    payload = {
        "changed_files": change_set.get("changed_files") or [],
        "changed_symbols": change_set.get("changed_symbols") or [],
        "raw_preview": change_set.get("raw_preview") or "",
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _owner_phase_for_artifact(path: str) -> str:
    if path.startswith("kernel/"):
        return "phase4"
    if path.startswith("cross_layer/") and not path.startswith(("cross_layer/input_to_tiling", "cross_layer/variable_lineage")):
        return "phase5"
    if path.startswith(("query/", "contracts/", "test/")):
        return "phase7"
    return "phase2"


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = item.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def _slug(value: Any) -> str:
    text = re.sub(r"[^A-Za-z0-9]+", "_", str(value or "")).strip("_").upper()
    return text or "UNKNOWN"


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value in (None, "", {}, []):
        return []
    return [value]
