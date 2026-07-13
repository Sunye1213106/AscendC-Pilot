from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]


ERROR_CODES = {
    "YAML_SYNTAX_ERROR",
    "YAML_ROOT_NOT_MAPPING",
    "YAML_SCHEMA_ERROR",
    "REQUIRED_SECTION_MISSING",
    "REQUIRED_SECTION_EMPTY",
    "INVALID_STABLE_ID",
    "UNRESOLVED_EVIDENCE_REF",
    "ARTIFACT_OWNER_MISMATCH",
    "SEMANTIC_DRIFT",
    "ENTRY_COUNT_CHANGED",
    "RESOURCE_NAME_CHANGED",
    "CONDITION_DROPPED",
    "CANONICAL_DIRECT_WRITE",
    "PROPOSAL_NOT_PROMOTED",
    "MANIFEST_INCOMPLETE",
    "INTERMEDIATE_ID_IN_CANONICAL",
    "EVIDENCE_REGISTRY_MISSING_ENTRY",
    "FACT_INDEX_REGISTRY_MISMATCH",
    "SOURCE_INDEX_REGISTRY_MISMATCH",
    "INSTALLED_SKILL_VERSION_MISMATCH",
    "RED_GATE_REMEDIATION_INCOMPLETE",
    "PATH_OPERATION_TARGET_MISMATCH",
    "SOURCE_INDEX_BAD_PREFIX",
    "BAD_ID_MIGRATION_KIND",
    "ID_KIND_PREFIX_MISMATCH",
}

DIRECT_CANONICAL_WRITERS = {"kb-promoter", "promoter", "compiler"}
QUALITY_CANONICAL_WRITERS = {"quality-gate", "quality_gate", "quality_gate.py"}
PROPOSAL_PRODUCER_ROLES = {
    "uo-host-extraction",
    "uo-flow-extraction",
    "uo-kernel-path",
    "host-compiler",
    "evidence-compiler",
    "registry-compiler",
    "route-compiler",
}
FORBIDDEN_CANONICAL_PROPOSERS = {"orchestrator", "quality-agent", "quality_agent", "quality_gate", "quality_gate.py"}

ARTIFACT_SOURCE_OWNERS: dict[str, str] = {
    "kernel/resources.yaml": "uo-kernel-path",
    "kernel/pipeline.yaml": "uo-kernel-path",
    "kernel/paths.yaml": "uo-kernel-path",
    "kernel/branches.yaml": "uo-kernel-path",
    "kernel/compile_model.yaml": "uo-kernel-path",
    "kernel/variables.yaml": "uo-kernel-path",
    "tiling/variables.yaml": "uo-host-extraction",
    "tiling/key_space.yaml": "uo-host-extraction",
    "tiling/exhaustive_key_space.yaml": "uo-host-extraction",
    "tiling/constraints.yaml": "uo-host-extraction",
    "tiling/families.yaml": "uo-host-extraction",
    "tiling/data_model.yaml": "uo-host-extraction",
    "tiling/coverage_model.yaml": "uo-host-extraction",
    "tiling/evidence_index.yaml": "uo-host-extraction",
    "flow/compute_graph.yaml": "uo-flow-extraction",
    "flow/dataflow.yaml": "uo-flow-extraction",
    "flow/golden_model.yaml": "uo-flow-extraction",
    "flow/numerical_model.yaml": "uo-flow-extraction",
    "cross_layer/input_to_tiling.yaml": "host-compiler",
    "cross_layer/tiling_to_kernel.yaml": "host-compiler",
    "cross_layer/variable_lineage.yaml": "host-compiler",
    "cross_layer/behavior_graph.yaml": "host-compiler",
    "cross_layer/impact_graph.yaml": "host-compiler",
    "registry/evidence.yaml": "evidence-source-router",
    "registry/variables.yaml": "registry-source-router",
    "registry/symbols.yaml": "registry-source-router",
}

ARTIFACT_CANONICAL_WRITERS: dict[str, set[str]] = {
    "kernel/resources.yaml": {"host-compiler", "kb-promoter", "promoter", "compiler"},
    "kernel/pipeline.yaml": {"host-compiler", "kb-promoter", "promoter", "compiler"},
    "kernel/paths.yaml": {"host-compiler", "kb-promoter", "promoter", "compiler"},
    "kernel/branches.yaml": {"host-compiler", "kb-promoter", "promoter", "compiler"},
    "kernel/compile_model.yaml": {"host-compiler", "kb-promoter", "promoter", "compiler"},
    "kernel/variables.yaml": {"host-compiler", "kb-promoter", "promoter", "compiler"},
    "tiling/variables.yaml": {"kb-promoter", "promoter", "compiler"},
    "tiling/key_space.yaml": {"kb-promoter", "promoter", "compiler"},
    "tiling/exhaustive_key_space.yaml": {"kb-promoter", "promoter", "compiler"},
    "tiling/constraints.yaml": {"kb-promoter", "promoter", "compiler"},
    "tiling/families.yaml": {"kb-promoter", "promoter", "compiler"},
    "tiling/data_model.yaml": {"kb-promoter", "promoter", "compiler"},
    "tiling/coverage_model.yaml": {"kb-promoter", "promoter", "compiler"},
    "tiling/evidence_index.yaml": {"kb-promoter", "promoter", "compiler"},
    "flow/compute_graph.yaml": {"kb-promoter", "promoter", "compiler"},
    "flow/dataflow.yaml": {"kb-promoter", "promoter", "compiler"},
    "flow/golden_model.yaml": {"kb-promoter", "promoter", "compiler"},
    "flow/numerical_model.yaml": {"kb-promoter", "promoter", "compiler"},
    "registry/evidence.yaml": {"evidence-compiler", "kb-promoter", "promoter", "compiler"},
    "registry/variables.yaml": {"registry-compiler", "kb-promoter", "promoter", "compiler"},
    "registry/symbols.yaml": {"registry-compiler", "kb-promoter", "promoter", "compiler"},
    "registry/aliases.yaml": {"registry-compiler", "kb-promoter", "promoter", "compiler"},
}

REQUIRED_SECTIONS: dict[str, tuple[str, ...]] = {
    "kernel/paths.yaml": ("kernel_paths",),
    "kernel/pipeline.yaml": ("pipelines", "stages", "resources", "compute_step_alignment"),
    "kernel/resources.yaml": ("buffers", "workspaces", "sync_events", "resources"),
    "kernel/branches.yaml": ("branches",),
    "tiling/variables.yaml": ("variables", "tiling_mechanism"),
    "tiling/constraints.yaml": ("relations", "variable_constraints", "input_realization"),
    "flow/compute_graph.yaml": ("compute_steps",),
    "flow/dataflow.yaml": ("dataflow_edges",),
}

REQUIRED_SECTION_POLICIES: dict[str, str] = {
    "kernel/paths.yaml.kernel_paths": "non_empty_collection",
    "kernel/branches.yaml.branches": "present_collection",
    "tiling/variables.yaml.variables": "non_empty_collection",
    "tiling/variables.yaml.tiling_mechanism": "present",
    "tiling/constraints.yaml.relations": "present_collection",
    "tiling/constraints.yaml.variable_constraints": "present_collection",
    "tiling/constraints.yaml.input_realization": "present_mapping",
    "flow/compute_graph.yaml.compute_steps": "non_empty_collection",
    "flow/dataflow.yaml.dataflow_edges": "present_collection",
}

NON_STABLE_ID_PATH_MARKERS = {
    "dtype_layout_domains[",
    "layout_dtype_domains[",
    "dtype_domains[",
    "layout_domains[",
    "terms.",
}

STABLE_ID_RE = re.compile(
    r"^(SYM|VAR|REL|EV|SRC|KEY|FAM|COMP|GOLD|KPATH|KBR|KTPL|CL|CON|VIEW|BUF|SYNC|RES|TDF|KVAR|KDEC|PIPE|COV|NUM)_[A-Z0-9_]+$"
)
LEGACY_ID_RE = re.compile(r"^(TF\d+|K\d+|C\d+|D\d+|P\d+)$")


@dataclass(frozen=True)
class YamlGateError:
    code: str
    message: str
    artifact: str
    phase: str = ""
    owner: str = ""
    line: int | None = None
    column: int | None = None
    allowed_repair_scope: str = "owner_retry"
    retry_task_id: str = ""
    run_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "owner": self.owner or artifact_owner(self.artifact),
            "artifact": self.artifact,
            "line": self.line,
            "column": self.column,
            "error_code": self.code,
            "error_message": self.message,
            "allowed_repair_scope": self.allowed_repair_scope,
            "retry_task_id": self.retry_task_id or retry_task_id(self.artifact, self.phase),
            "run_id": self.run_id,
        }


def artifact_owner(rel: str) -> str:
    return artifact_source_owner(rel)


def artifact_source_owner(rel: str) -> str:
    rel = rel.replace("\\", "/")
    if rel in ARTIFACT_SOURCE_OWNERS:
        return ARTIFACT_SOURCE_OWNERS[rel]
    if rel.startswith("kernel/"):
        return "uo-kernel-path"
    if rel.startswith("tiling/"):
        return "uo-host-extraction"
    if rel.startswith("flow/"):
        return "uo-flow-extraction"
    if rel.startswith(("registry/", "evidence/")):
        return "source-evidence-owner"
    if rel.startswith(("cross_layer/", "query/", "contracts/", "test/")):
        return "host-compiler"
    if rel == "quality.yaml":
        return "quality_gate.py"
    return "host-compiler"


def allowed_canonical_writers(rel: str) -> set[str]:
    rel = rel.replace("\\", "/")
    if rel == "quality.yaml":
        return set(QUALITY_CANONICAL_WRITERS)
    if rel in ARTIFACT_CANONICAL_WRITERS:
        return set(ARTIFACT_CANONICAL_WRITERS[rel])
    if rel.startswith("cross_layer/"):
        return {"host-compiler", "kb-promoter", "promoter", "compiler"}
    if rel.startswith(("query/", "contracts/", "test/")):
        return {"route-compiler", "kb-promoter", "promoter", "compiler"}
    if rel.startswith("evidence/"):
        return {"evidence-compiler", "kb-promoter", "promoter", "compiler"}
    if rel.startswith("registry/"):
        return {"registry-compiler", "kb-promoter", "promoter", "compiler"}
    return {"kb-promoter", "promoter", "compiler"}


def validate_canonical_writer(writer: str, rel: str) -> None:
    rel = rel.replace("\\", "/")
    if rel.startswith("archive/"):
        return
    allowed = allowed_canonical_writers(rel)
    if writer not in allowed:
        raise PermissionError(
            YamlGateError(
                "CANONICAL_DIRECT_WRITE",
                f"{writer} is not allowed to write {rel}; allowed canonical writers: {', '.join(sorted(allowed))}",
                rel,
                owner=artifact_source_owner(rel),
            ).message
        )


def retry_task_id(rel: str, phase: str = "") -> str:
    owner = artifact_owner(rel)
    slug = re.sub(r"[^A-Za-z0-9]+", "_", rel).strip("_").lower() or "artifact"
    phase_slug = re.sub(r"[^A-Za-z0-9]+", "_", phase).strip("_").lower()
    return f"retry_{owner}_{phase_slug + '_' if phase_slug else ''}{slug}"


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def yaml_text(data: Any) -> str:
    if yaml is None:
        raise RuntimeError("PyYAML is required for checked YAML serialization")

    class _NoAliasDumper(yaml.SafeDumper):
        def ignore_aliases(self, data: Any) -> bool:  # type: ignore[override]
            return True

    return yaml.dump(data, Dumper=_NoAliasDumper, allow_unicode=True, sort_keys=False)


def validate_yaml_document(
    text: str,
    artifact: str,
    *,
    phase: str = "",
    run_id: str = "",
    required_sections: tuple[str, ...] | None = None,
) -> tuple[Any, list[YamlGateError]]:
    owner = artifact_owner(artifact)
    if yaml is None:
        return {}, [YamlGateError("YAML_SCHEMA_ERROR", "PyYAML is required", artifact, phase, owner, run_id=run_id)]
    if not text.strip():
        return {}, [YamlGateError("REQUIRED_SECTION_EMPTY", "YAML document must not be empty", artifact, phase, owner, run_id=run_id)]
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        return {}, [
            YamlGateError(
                "YAML_SYNTAX_ERROR",
                str(exc),
                artifact,
                phase,
                owner,
                line=(getattr(mark, "line", None) + 1) if mark is not None else None,
                column=(getattr(mark, "column", None) + 1) if mark is not None else None,
                allowed_repair_scope="syntax_only_repair_or_owner_retry",
                run_id=run_id,
            )
        ]
    if not isinstance(data, dict):
        return data, [YamlGateError("YAML_ROOT_NOT_MAPPING", "YAML root must be a mapping", artifact, phase, owner, run_id=run_id)]

    errors: list[YamlGateError] = []
    for section in required_sections if required_sections is not None else REQUIRED_SECTIONS.get(artifact, ()):
        if section not in data:
            errors.append(YamlGateError("REQUIRED_SECTION_MISSING", f"required section missing: {section}", artifact, phase, owner, run_id=run_id))
            continue
        section_errors = _validate_required_section_policy(data.get(section), REQUIRED_SECTION_POLICIES.get(f"{artifact}.{section}", "present"), section)
        for message in section_errors:
            errors.append(YamlGateError("REQUIRED_SECTION_EMPTY", message, artifact, phase, owner, run_id=run_id))
    _append_id_errors(data, artifact, phase, owner, run_id, errors)
    return data, errors


def _validate_required_section_policy(value: Any, policy: str, section: str) -> list[str]:
    if value == "" or value is None:
        return [f"required section is empty: {section}"]
    if policy == "present":
        return []
    if policy == "present_collection":
        if not isinstance(value, (list, dict)):
            return [f"required section must be a list or mapping: {section}"]
        return []
    if policy == "present_mapping":
        if not isinstance(value, dict):
            return [f"required section must be a mapping: {section}"]
        return []
    if policy == "non_empty_collection":
        if not isinstance(value, (list, dict)):
            return [f"required section must be a list or mapping: {section}"]
        if len(value) == 0:
            return [f"required section must not be empty: {section}"]
    return []


def serialize_yaml_checked(
    artifact: str,
    data: Any,
    *,
    phase: str = "",
    run_id: str = "",
    schema_validator: Callable[[Any], list[YamlGateError] | list[str] | None] | None = None,
    semantic_validator: Callable[[Any], list[YamlGateError] | list[str] | None] | None = None,
) -> tuple[str, list[YamlGateError]]:
    owner = artifact_owner(artifact)
    if not isinstance(data, dict):
        return "", [YamlGateError("YAML_ROOT_NOT_MAPPING", "canonical YAML data must be a mapping before serialization", artifact, phase, owner, run_id=run_id)]
    text = yaml_text(data)
    loaded, errors = validate_yaml_document(text, artifact, phase=phase, run_id=run_id)
    if loaded != data:
        errors.append(YamlGateError("YAML_SCHEMA_ERROR", "YAML round-trip changed the document", artifact, phase, owner, run_id=run_id))
    for validator in (schema_validator, semantic_validator):
        if validator is None:
            continue
        for item in validator(loaded) or []:
            if isinstance(item, YamlGateError):
                errors.append(item)
            else:
                errors.append(YamlGateError("YAML_SCHEMA_ERROR", str(item), artifact, phase, owner, run_id=run_id))
    return text, errors


def write_yaml_checked(
    path: Path,
    data: Any,
    *,
    artifact: str | None = None,
    writer: str = "promoter",
    phase: str = "",
    run_id: str = "",
    schema_validator: Callable[[Any], list[YamlGateError] | list[str] | None] | None = None,
    semantic_validator: Callable[[Any], list[YamlGateError] | list[str] | None] | None = None,
) -> None:
    artifact = (artifact or path.as_posix()).replace("\\", "/")
    validate_canonical_writer(writer, artifact)
    text, errors = serialize_yaml_checked(
        artifact,
        data,
        phase=phase,
        run_id=run_id,
        schema_validator=schema_validator,
        semantic_validator=semantic_validator,
    )
    if errors:
        raise ValueError("; ".join(f"{err.code}: {err.message}" for err in errors))
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def syntax_only_repair(text: str, artifact: str, *, phase: str = "", run_id: str = "") -> tuple[str, list[YamlGateError]]:
    data, errors = validate_yaml_document(text, artifact, phase=phase, run_id=run_id, required_sections=())
    if any(err.code == "YAML_SYNTAX_ERROR" for err in errors):
        repaired_candidate = _repair_mixed_list_item_flow_mapping(text)
        if repaired_candidate == text:
            return text, errors
        if yaml is None:
            return text, errors
        candidate_data, candidate_errors = validate_yaml_document(repaired_candidate, artifact, phase=phase, run_id=run_id)
        if artifact == "kernel/resources.yaml" and not candidate_errors:
            candidate_errors.extend(resource_semantic_errors(candidate_data, artifact, phase=phase, run_id=run_id))
        if candidate_errors:
            return text, candidate_errors
        before = semantic_summary(_restricted_summary_parse_mixed_list_item_flow_mapping(text))
        after = semantic_summary(candidate_data)
        drift = compare_semantic_summaries(before, after, artifact, phase=phase, run_id=run_id)
        if drift:
            return text, drift
        return repaired_candidate, []
    if data in (None, ""):
        return text, errors or [YamlGateError("REQUIRED_SECTION_EMPTY", "document is empty", artifact, phase, artifact_owner(artifact), run_id=run_id)]
    before = semantic_summary(data)
    repaired = yaml_text(data)
    after_data = yaml.safe_load(repaired) if yaml is not None else data
    after = semantic_summary(after_data)
    drift = compare_semantic_summaries(before, after, artifact, phase=phase, run_id=run_id)
    if drift:
        return text, drift
    return repaired, []


def semantic_summary(data: Any) -> dict[str, Any]:
    sections: dict[str, int] = {}
    stable_ids: set[str] = set()
    resource_names: set[str] = set()
    producer_consumer_edges: set[str] = set()
    conditions: set[str] = set()
    evidence_refs: set[str] = set()
    reference_edges: set[str] = set()
    item_hashes: dict[str, str] = {}

    def visit(value: Any, path: str = "$") -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if isinstance(child, (list, dict)):
                    sections[f"{path}.{key}"] = len(_entries(child))
                if key in {"id", "stable_id"} and isinstance(child, str):
                    stable_ids.add(child)
                if key == "name" and isinstance(child, str):
                    resource_names.add(child)
                if key == "condition" and child not in (None, ""):
                    conditions.add(str(child))
                if key == "evidence_refs":
                    for ref in _as_list(child):
                        evidence_refs.add(str(ref))
                if str(key).endswith(("_id", "_ref")) and isinstance(child, str):
                    reference_edges.add(f"{path}.{key}->{child}")
                visit(child, f"{path}.{key}")
            item_id = value.get("id") or value.get("stable_id") or value.get("name")
            if item_id:
                item_hashes[f"{path}::{item_id}"] = hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
            producer = value.get("producer")
            consumer = value.get("consumer")
            if producer or consumer:
                item_id = value.get("id") or value.get("stable_id") or value.get("name") or ""
                producer_consumer_edges.add(f"{path}:{item_id}:{producer}->{consumer}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, f"{path}[{index}]")

    visit(data)
    return {
        "section_entry_counts": dict(sorted(sections.items())),
        "stable_ids": sorted(stable_ids),
        "resource_names": sorted(resource_names),
        "producer_consumer_edges": sorted(producer_consumer_edges),
        "conditions": sorted(conditions),
        "evidence_refs": sorted(evidence_refs),
        "reference_edges": sorted(reference_edges),
        "item_hashes": dict(sorted(item_hashes.items())),
    }


def compare_semantic_summaries(
    before: dict[str, Any],
    after: dict[str, Any],
    artifact: str,
    *,
    phase: str = "",
    run_id: str = "",
) -> list[YamlGateError]:
    owner = artifact_owner(artifact)
    checks = (
        ("section_entry_counts", "ENTRY_COUNT_CHANGED", "entry counts changed"),
        ("stable_ids", "SEMANTIC_DRIFT", "stable ids changed"),
        ("resource_names", "RESOURCE_NAME_CHANGED", "resource names changed"),
        ("producer_consumer_edges", "SEMANTIC_DRIFT", "producer/consumer edges changed"),
        ("conditions", "CONDITION_DROPPED", "conditions changed or dropped"),
        ("evidence_refs", "SEMANTIC_DRIFT", "evidence refs changed"),
        ("reference_edges", "SEMANTIC_DRIFT", "structured references changed"),
        ("item_hashes", "SEMANTIC_DRIFT", "canonical semantic hashes changed"),
    )
    errors: list[YamlGateError] = []
    for key, code, message in checks:
        if before.get(key) != after.get(key):
            errors.append(YamlGateError(code, message, artifact, phase, owner, run_id=run_id))
    return errors


def owner_retry_report(error: YamlGateError | dict[str, Any], *, artifact: str | None = None, phase: str = "", run_id: str = "") -> dict[str, Any]:
    payload = error.to_dict() if isinstance(error, YamlGateError) else dict(error)
    rel = artifact or str(payload.get("artifact") or "")
    owner = artifact_owner(rel)
    payload.update(
        {
            "phase": payload.get("phase") or phase,
            "owner": payload.get("owner") or owner,
            "artifact": rel,
            "allowed_repair_scope": payload.get("allowed_repair_scope") or "owner_retry",
            "retry_task_id": payload.get("retry_task_id") or retry_task_id(rel, phase),
            "run_id": payload.get("run_id") or run_id,
        }
    )
    return payload


def resource_semantic_errors(data: Any, artifact: str = "kernel/resources.yaml", *, phase: str = "", run_id: str = "") -> list[YamlGateError]:
    errors: list[YamlGateError] = []
    doc = data if isinstance(data, dict) else {}
    for section, category in (("buffers", "buffer"), ("workspaces", "workspace"), ("sync_events", "sync_event"), ("resources", "resource")):
        for index, item in enumerate(_entries(doc.get(section))):
            missing = []
            if not (item.get("id") or item.get("stable_id") or item.get("name")):
                missing.append("name_or_stable_id")
            for key in ("producer", "consumer", "condition", "direction", "evidence_refs"):
                if item.get(key) in (None, "", []):
                    missing.append(key)
            if section != "sync_events" and not (item.get("type") or item.get("dtype") or item.get("size")):
                missing.append("type_or_dtype_or_size")
            if not (item.get("category") or item.get("resource_category")):
                item["resource_category"] = category
            if missing:
                errors.append(
                    YamlGateError(
                        "YAML_SCHEMA_ERROR",
                        f"{section}[{index}] missing required resource fields: {', '.join(missing)}",
                        artifact,
                        phase,
                        artifact_owner(artifact),
                        run_id=run_id,
                    )
                )
    return errors


def _append_id_errors(data: Any, artifact: str, phase: str, owner: str, run_id: str, errors: list[YamlGateError]) -> None:
    def visit(value: Any, path: str) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                child_path = f"{path}.{key}" if path else str(key)
                if key in {"id", "stable_id"} and child:
                    if _is_domain_value_id_path(child_path) or ".schema" in child_path:
                        visit(child, child_path)
                        continue
                    if not isinstance(child, str) or not (STABLE_ID_RE.fullmatch(child) or LEGACY_ID_RE.fullmatch(child)):
                        errors.append(YamlGateError("INVALID_STABLE_ID", f"invalid stable id: {child!r}", artifact, phase, owner, run_id=run_id))
                if key == "evidence_refs" and ".schema" not in child_path and not isinstance(child, (list, dict)):
                    errors.append(YamlGateError("YAML_SCHEMA_ERROR", f"{child_path} must be a YAML list", artifact, phase, owner, run_id=run_id))
                visit(child, child_path)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, f"{path}[{index}]")

    visit(data, "")


def _entries(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        return [item for item in value.values() if isinstance(item, dict)]
    return []


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value in (None, "", {}, []):
        return []
    return [value]


def _repair_mixed_list_item_flow_mapping(text: str) -> str:
    lines: list[str] = []
    changed = False
    for line in text.splitlines():
        match = re.match(r"^(\s*)-\s+([^:][^:]*:\s*.+,\s+[^:]+:\s*.+)$", line)
        if not match:
            lines.append(line)
            continue
        indent, payload = match.groups()
        pairs = _split_unquoted_commas(payload)
        if len(pairs) < 2 or any(":" not in pair for pair in pairs):
            lines.append(line)
            continue
        first_key, first_value = pairs[0].split(":", 1)
        lines.append(f"{indent}- {first_key.strip()}: {first_value.strip()}")
        for pair in pairs[1:]:
            key, value = pair.split(":", 1)
            lines.append(f"{indent}  {key.strip()}: {value.strip()}")
        changed = True
    if not changed:
        return text
    suffix = "\n" if text.endswith("\n") else ""
    return "\n".join(lines) + suffix


def _restricted_summary_parse_mixed_list_item_flow_mapping(text: str) -> Any:
    repaired = _repair_mixed_list_item_flow_mapping(text)
    if yaml is None:
        return {}
    try:
        return yaml.safe_load(repaired)
    except yaml.YAMLError:
        return {}


def _split_unquoted_commas(value: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    quote = ""
    escape = False
    for char in value:
        if escape:
            current.append(char)
            escape = False
            continue
        if char == "\\":
            current.append(char)
            escape = True
            continue
        if quote:
            current.append(char)
            if char == quote:
                quote = ""
            continue
        if char in {"'", '"'}:
            quote = char
            current.append(char)
            continue
        if char == ",":
            parts.append("".join(current).strip())
            current = []
            continue
        current.append(char)
    parts.append("".join(current).strip())
    return parts


def _looks_like_machine_id(value: str) -> bool:
    if LEGACY_ID_RE.fullmatch(value):
        return True
    return bool(re.match(r"^[A-Z][A-Z0-9]*_", value))


def _is_domain_value_id_path(path: str) -> bool:
    return any(marker in path for marker in NON_STABLE_ID_PATH_MARKERS)
