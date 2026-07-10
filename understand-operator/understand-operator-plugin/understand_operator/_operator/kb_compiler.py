from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from understand_operator._operator.artifacts import operator_root, read_text, safe_op_name, write_text

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]


STABLE_ID_RE = re.compile(
    r"^(SYM|VAR|REL|EV|SRC|KEY|FAM|KPATH|KBR|KTPL|CL|CON|VIEW|BUF|SYNC|RES)_[A-Z0-9_]+$"
)
LEGACY_ID_RE = re.compile(r"^(TF\d+|K\d+|C\d+|D\d+|P\d+)$")
STATUS_ENUM = {"confirmed", "proposed", "uncertain", "conflicting", "unresolved", "deprecated"}
RELATION_TYPES = {
    "derives",
    "reads",
    "writes",
    "controls",
    "determines",
    "implies",
    "requires",
    "conflicts_with",
    "compatible_with",
    "encodes",
    "binds",
    "dispatches_to",
    "enables",
    "maps_to",
    "affects",
    "consumes",
    "produces",
    "mutex",
    "compatible_set",
    "compile_time_fixed",
    "runtime_guard",
    "other",
}

REGISTRY_FILES = (
    "registry/symbols.yaml",
    "registry/variables.yaml",
    "registry/aliases.yaml",
    "registry/evidence.yaml",
)
CROSS_LAYER_FILES = (
    "cross_layer/input_to_tiling.yaml",
    "cross_layer/tiling_to_kernel.yaml",
    "cross_layer/variable_lineage.yaml",
    "cross_layer/behavior_graph.yaml",
    "cross_layer/impact_graph.yaml",
)
CONTRACT_FILES = (
    "contracts/query.yaml",
    "contracts/code_change.yaml",
    "contracts/pr_review.yaml",
    "contracts/testcase.yaml",
)
QUERY_FILES = (
    "query/routes.yaml",
    "query/terminology.yaml",
)
KERNEL_FILES = (
    "kernel/compile_model.yaml",
    "kernel/variables.yaml",
    "kernel/branches.yaml",
    "kernel/paths.yaml",
    "kernel/pipeline.yaml",
    "kernel/resources.yaml",
)
TILING_FILES = (
    "tiling/variables.yaml",
    "tiling/constraints.yaml",
    "tiling/key_space.yaml",
    "tiling/families.yaml",
    "tiling/data_model.yaml",
    "tiling/coverage_model.yaml",
    "tiling/evidence_index.yaml",
)
FLOW_FILES = (
    "flow/compute_graph.yaml",
    "flow/dataflow.yaml",
    "flow/golden_model.yaml",
    "flow/numerical_model.yaml",
)
EVIDENCE_FILES = (
    "evidence/fact_index.yaml",
    "evidence/source_index.yaml",
    "evidence/artifact_dependencies.yaml",
    "evidence/issues.yaml",
)
ROOT_FILES = ("manifest.yaml", "index.yaml", "operator.yaml")

PHASE_FILES: dict[str, tuple[str, ...]] = {
    "phase2": ROOT_FILES + REGISTRY_FILES + TILING_FILES + FLOW_FILES + EVIDENCE_FILES,
    "phase4": ROOT_FILES + REGISTRY_FILES + TILING_FILES + FLOW_FILES + EVIDENCE_FILES + KERNEL_FILES,
    "phase5": ROOT_FILES + REGISTRY_FILES + TILING_FILES + FLOW_FILES + EVIDENCE_FILES + KERNEL_FILES + CROSS_LAYER_FILES,
    "phase7": ROOT_FILES
    + REGISTRY_FILES
    + TILING_FILES
    + FLOW_FILES
    + EVIDENCE_FILES
    + KERNEL_FILES
    + CROSS_LAYER_FILES
    + QUERY_FILES
    + CONTRACT_FILES,
    "final": ROOT_FILES
    + REGISTRY_FILES
    + TILING_FILES
    + FLOW_FILES
    + EVIDENCE_FILES
    + KERNEL_FILES
    + CROSS_LAYER_FILES
    + QUERY_FILES
    + CONTRACT_FILES
    + ("test/contract.yaml", "quality.yaml"),
}

PROMOTION_TARGET_PREFIXES = (
    "registry/",
    "tiling/",
    "flow/",
    "kernel/",
    "cross_layer/",
    "query/",
    "contracts/",
    "evidence/",
)
FORBIDDEN_TARGET_PREFIXES = ("archive/", "cbm/", ".git/", "../")
MERGE_MODES = {"by_id", "replace_section", "merge_mapping"}
REPLACE_SECTION_ALLOWLIST = {
    ("query/routes.yaml", "routes"),
    ("query/terminology.yaml", "terms"),
    ("contracts/query.yaml", "required_response_fields"),
    ("contracts/testcase.yaml", "kernel_branch_obligations"),
}

MATURITY_RULES: dict[str, tuple[str, ...]] = {
    "registry/variables.yaml": ("variables",),
    "registry/symbols.yaml": ("symbols",),
    "registry/evidence.yaml": ("evidence",),
    "tiling/variables.yaml": ("variables", "tiling_mechanism"),
    "tiling/constraints.yaml": ("relations", "variable_constraints", "input_realization"),
    "tiling/key_space.yaml": ("fields", "derived_fields", "constants"),
    "flow/compute_graph.yaml": ("compute_steps", "outputs"),
    "flow/dataflow.yaml": ("dataflow_edges", "tensor_lifecycle"),
    "kernel/compile_model.yaml": ("template_bindings", "compile_time_configs", "compile_variables", "compile_decisions"),
    "kernel/variables.yaml": ("runtime_variables", "tilingdata_reads", "path_decision_points"),
    "kernel/branches.yaml": ("branches", "path_semantics", "dataflow_links", "resource_links"),
    "kernel/paths.yaml": ("kernel_paths",),
    "cross_layer/input_to_tiling.yaml": ("nodes", "edges", "relations", "links"),
    "cross_layer/tiling_to_kernel.yaml": ("nodes", "edges", "relations", "links"),
    "cross_layer/variable_lineage.yaml": ("variables", "lineage", "relations", "edges"),
    "cross_layer/behavior_graph.yaml": ("nodes", "edges"),
    "cross_layer/impact_graph.yaml": ("nodes", "edges", "impacts"),
    "query/routes.yaml": ("routes",),
    "contracts/query.yaml": ("required_response_fields", "routes"),
    "contracts/code_change.yaml": ("target", "upstream", "downstream"),
    "contracts/pr_review.yaml": ("review_slices", "recommended_checks"),
    "contracts/testcase.yaml": ("input_domain", "typed_constraints", "kernel_branch_obligations"),
}


@dataclass
class Issue:
    code: str
    severity: str
    message: str
    artifact: str = ""
    target: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "severity": self.severity,
            "artifact": self.artifact,
            "target": self.target,
            "message": self.message,
        }


@dataclass
class CompileResult:
    op_name: str
    phase: str = "final"
    status: str = "pass"
    issues: list[Issue] = field(default_factory=list)
    artifact_hashes: dict[str, str] = field(default_factory=dict)
    entity_index: dict[str, dict[str, Any]] = field(default_factory=dict)
    maturity: dict[str, str] = field(default_factory=dict)
    promotion_report: dict[str, Any] = field(default_factory=dict)
    relation_count: int = 0
    unresolved_count: int = 0
    conflict_count: int = 0

    @property
    def entity_count(self) -> int:
        return len(self.entity_index)

    @property
    def alias_count(self) -> int:
        return sum(len(v.get("aliases") or []) for v in self.entity_index.values())

    @property
    def evidence_count(self) -> int:
        return len([k for k in self.entity_index if k.startswith(("EV_", "SRC_"))])

    def add(self, code: str, severity: str, message: str, artifact: str = "", target: str = "") -> None:
        self.issues.append(Issue(code, severity, message, artifact, target))
        if severity == "error":
            self.status = "fail"
        elif severity == "warning" and self.status == "pass":
            self.status = "warn"


def compile_kb(
    uo_root: Path,
    op_name: str,
    *,
    write_outputs: bool = True,
    phase: str = "final",
) -> CompileResult:
    return validate_kb(uo_root, op_name, phase=phase, write_outputs=write_outputs)


def validate_kb(
    uo_root: Path,
    op_name: str,
    *,
    phase: str = "final",
    write_outputs: bool = True,
) -> CompileResult:
    phase = _normalize_phase(phase)
    result = CompileResult(op_name=op_name, phase=phase)
    docs = _load_phase_docs(uo_root, phase, result)
    _hash_artifacts(uo_root, result)
    result.maturity = _check_maturity(docs, phase, result)
    result.entity_index = build_entity_index(docs, result)
    _validate_evidence(docs, result)
    _validate_relations(docs, result)
    _validate_flow_kernel_boundary(docs, result)
    _validate_kernel_two_step(docs, result)
    _validate_cross_layer(docs, result, phase)
    _validate_contracts(docs, result, phase)
    _validate_stale(uo_root, result, phase)
    if write_outputs:
        _write_compile_outputs(uo_root, result)
    return result


def promote_kb(
    uo_root: Path,
    op_name: str,
    *,
    phase: str = "phase2",
    proposal_paths: list[Path] | None = None,
    write_outputs: bool = True,
) -> CompileResult:
    phase = _normalize_phase(phase)
    result = CompileResult(op_name=op_name, phase=phase)
    docs = _load_all_existing_docs(uo_root, result)
    before_hashes = _hash_docs(docs)
    proposals = _load_proposals(uo_root, result, proposal_paths)
    candidate = copy.deepcopy(docs)

    applied: list[dict[str, Any]] = []
    for proposal_path, proposal in proposals:
        if not _validate_proposal_envelope(proposal_path, proposal, op_name, phase, result):
            continue
        for update in _as_list(proposal.get("canonical_updates")):
            if not isinstance(update, dict):
                result.add("BAD_PROPOSAL_UPDATE", "error", "canonical_updates entries must be mappings", proposal_path.as_posix())
                continue
            ok = _apply_update(candidate, update, proposal_path, result)
            if ok:
                applied.append(
                    {
                        "proposal": proposal_path.relative_to(uo_root).as_posix()
                        if _is_relative_to(proposal_path, uo_root)
                        else proposal_path.as_posix(),
                        "target": update.get("target"),
                        "section": update.get("section"),
                        "merge_mode": update.get("merge_mode"),
                        "entries": len(_as_list(update.get("entries"))),
                    }
                )

    if any(issue.severity == "error" for issue in result.issues):
        result.promotion_report = _promotion_report(op_name, phase, "failed", applied, result, before_hashes, {})
        if write_outputs:
            _write_promotion_report(uo_root, result)
        return result

    _normalize_candidate(candidate)
    _build_graphs(candidate, op_name)
    candidate_result = CompileResult(op_name=op_name, phase=phase)
    candidate_result.artifact_hashes = _hash_artifacts_from_docs(candidate)
    candidate_result.maturity = _check_maturity(candidate, phase, candidate_result)
    candidate_result.entity_index = build_entity_index(candidate, candidate_result)
    _validate_evidence(candidate, candidate_result)
    _validate_relations(candidate, candidate_result)
    _validate_flow_kernel_boundary(candidate, candidate_result)
    _validate_kernel_two_step(candidate, candidate_result)
    _validate_cross_layer(candidate, candidate_result, phase)
    _validate_contracts(candidate, candidate_result, phase)

    result.issues.extend(candidate_result.issues)
    if candidate_result.status == "fail":
        result.status = "fail"
        result.promotion_report = _promotion_report(op_name, phase, "failed", applied, result, before_hashes, {})
        if write_outputs:
            _write_promotion_report(uo_root, result)
        return result
    if candidate_result.status == "warn":
        result.status = "warn"
    result.entity_index = candidate_result.entity_index
    result.maturity = candidate_result.maturity
    result.artifact_hashes = candidate_result.artifact_hashes
    result.relation_count = candidate_result.relation_count
    result.unresolved_count = candidate_result.unresolved_count
    result.conflict_count = candidate_result.conflict_count

    after_hashes = _hash_artifacts_from_docs(candidate)
    if write_outputs:
        _atomic_write_docs(uo_root, candidate, only_changed_against=docs)
    result.promotion_report = _promotion_report(op_name, phase, "promoted", applied, result, before_hashes, after_hashes)
    if write_outputs:
        _write_compile_outputs(uo_root, result)
        _write_promotion_report(uo_root, result)
    return result


def build_entity_index(docs: dict[str, Any], result: CompileResult | None = None) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}

    def add(item_id: str, kind: str, artifact: str, section: str, meta: dict[str, Any] | None = None) -> None:
        item_id = str(item_id or "").strip()
        if not item_id:
            return
        meta = dict(meta or {})
        expected_kind = _kind_from_prefix(item_id)
        if result and not (STABLE_ID_RE.match(item_id) or LEGACY_ID_RE.match(item_id)):
            result.add("BAD_STABLE_ID", "error", f"stable id does not match convention: {item_id}", artifact, item_id)
        if result and item_id in index and index[item_id]["kind"] != kind:
            result.add("ID_KIND_CONFLICT", "error", f"{item_id} reused as {index[item_id]['kind']} and {kind}", artifact, item_id)
        if result and expected_kind and kind and expected_kind != kind and not item_id.startswith(("TF", "K", "C", "D", "P")):
            result.add("ID_KIND_PREFIX_MISMATCH", "warning", f"{item_id} prefix suggests {expected_kind}, got {kind}", artifact, item_id)
        existing = index.get(item_id)
        if existing:
            existing.setdefault("artifacts", [])
            existing["artifacts"].append({"artifact": artifact, "section": section})
            return
        aliases = _as_list(meta.get("aliases"))
        index[item_id] = {
            "stable_id": item_id,
            "kind": kind,
            "artifact": artifact,
            "section": section,
            "canonical_name": meta.get("canonical_name") or meta.get("name") or meta.get("label") or item_id,
            "aliases": aliases,
            "scope": meta.get("scope") or "",
            "data_type": meta.get("data_type") or meta.get("dtype") or "",
            "evidence_refs": _as_list(meta.get("evidence_refs")),
            "artifacts": [{"artifact": artifact, "section": section}],
        }

    for rel, data in docs.items():
        doc = _as_dict(data)
        if rel == "registry/symbols.yaml":
            for item in _iter_entries(doc.get("symbols")):
                add(str(item.get("id")), "symbol", rel, "symbols", item)
        if rel == "registry/variables.yaml":
            for item in _iter_entries(doc.get("variables")):
                add(str(item.get("id")), "variable", rel, "variables", item)
        if rel == "registry/evidence.yaml":
            for item in _iter_entries(doc.get("evidence")):
                add(str(item.get("id")), "evidence", rel, "evidence", item)
        if rel == "registry/aliases.yaml":
            for item in _iter_entries(doc.get("aliases")):
                target = str(item.get("target_id") or item.get("canonical_id") or "")
                if result and target and target not in index:
                    result.add("DANGLING_ALIAS", "error", f"alias targets unknown id {target}", rel, target)
        if rel == "tiling/key_space.yaml":
            for item in _iter_entries(doc.get("fields")):
                item_id = str(item.get("id") or item.get("stable_id") or f"KEY_{str(item.get('canonical_name') or item.get('name') or '').upper()}")
                add(item_id, "key", rel, "fields", item)
        if rel == "tiling/families.yaml":
            for item in _iter_entries(doc.get("families")):
                item_id = str(item.get("id") or item.get("family_id") or "")
                if item_id.startswith("TF"):
                    item_id = "FAM_" + item_id
                add(item_id, "family", rel, "families", item)
        if rel == "flow/compute_graph.yaml":
            for item in _iter_entries(doc.get("compute_steps")):
                add(str(item.get("id")), "compute_step", rel, "compute_steps", item)
        if rel == "kernel/compile_model.yaml":
            for item in _iter_entries(doc.get("template_bindings")):
                add(str(item.get("id")), "template_binding", rel, "template_bindings", item)
        if rel == "kernel/paths.yaml":
            for item in _iter_entries(doc.get("kernel_paths")):
                add(str(item.get("id") or item.get("stable_key")), "kernel_path", rel, "kernel_paths", item)
        if rel == "kernel/branches.yaml":
            for item in _iter_entries(doc.get("branches")):
                add(str(item.get("id")), "kernel_branch", rel, "branches", item)
        if rel == "kernel/resources.yaml":
            for section in ("buffers", "sync_events", "workspaces", "resources"):
                for item in _iter_entries(doc.get(section)):
                    kind = "sync" if section == "sync_events" else "resource"
                    add(str(item.get("id")), kind, rel, section, item)
        for section in ("relations", "links", "edges", "impacts"):
            for item in _iter_entries(doc.get(section)):
                item_id = str(item.get("id") or "")
                if item_id:
                    add(item_id, "relation", rel, section, item)

    aliases_by_scope: dict[tuple[str, str], str] = {}
    alias_targets: dict[str, str] = {}
    for item_id, meta in sorted(index.items()):
        name = str(meta.get("canonical_name") or "").strip()
        scope = str(meta.get("scope") or "").strip()
        if not name:
            continue
        key = (scope, name)
        prev = aliases_by_scope.get(key)
        if result and prev and prev != item_id:
            result.add("DUPLICATE_CANONICAL_NAME", "warning", f"{scope}.{name} defined by {prev} and {item_id}", meta.get("artifact", ""), name)
        aliases_by_scope[key] = item_id
        for alias in meta.get("aliases") or []:
            alias_key = str(alias)
            prev_alias = alias_targets.get(alias_key)
            if result and prev_alias and prev_alias != item_id:
                result.add("ALIAS_CONFLICT", "error", f"alias {alias} maps to both {prev_alias} and {item_id}", meta.get("artifact", ""), str(alias))
            alias_targets[alias_key] = item_id
    return dict(sorted(index.items()))


def _load_phase_docs(uo_root: Path, phase: str, result: CompileResult) -> dict[str, Any]:
    rels = PHASE_FILES[_normalize_phase(phase)]
    docs: dict[str, Any] = {}
    for rel in rels:
        path = uo_root / rel
        if not path.exists():
            result.add("MISSING_PHASE_ARTIFACT", "error", f"{rel} required for {phase}", rel)
            continue
        docs[rel] = _read_yaml(path, result)
    return docs


def _load_all_existing_docs(uo_root: Path, result: CompileResult) -> dict[str, Any]:
    docs: dict[str, Any] = {}
    for path in sorted(uo_root.rglob("*.yaml")):
        rel = path.relative_to(uo_root).as_posix()
        if rel.startswith(("archive/", "cbm/")):
            continue
        docs[rel] = _read_yaml(path, result)
    return docs


def _read_yaml(path: Path, result: CompileResult | None = None) -> Any:
    if yaml is None:
        if result:
            result.add("YAML_UNAVAILABLE", "error", "PyYAML is required for KB compilation", path.as_posix())
        return {}
    try:
        return yaml.safe_load(read_text(path)) or {}
    except Exception as exc:  # noqa: BLE001
        if result:
            result.add("YAML_PARSE", "error", f"YAML parse failed: {exc}", path.as_posix())
        return {}


def _load_proposals(
    uo_root: Path,
    result: CompileResult,
    proposal_paths: list[Path] | None = None,
) -> list[tuple[Path, dict[str, Any]]]:
    if proposal_paths is None:
        proposal_paths = sorted((uo_root / "archive" / "proposals").glob("*.yaml"))
    proposals: list[tuple[Path, dict[str, Any]]] = []
    for path in proposal_paths:
        if not path.exists():
            result.add("MISSING_PROPOSAL", "error", f"proposal not found: {path}", path.as_posix())
            continue
        data = _read_yaml(path, result)
        if isinstance(data, dict):
            proposals.append((path, data))
        else:
            result.add("BAD_PROPOSAL", "error", "proposal must parse to mapping", path.as_posix())
    if not proposals:
        result.add("NO_PROPOSALS", "warning", "no proposal files found", "archive/proposals")
    return proposals


def _validate_proposal_envelope(
    path: Path,
    proposal: dict[str, Any],
    op_name: str,
    phase: str,
    result: CompileResult,
) -> bool:
    required = ("version", "op_name", "proposal_id", "producer", "canonical_updates")
    ok = True
    for key in required:
        if key not in proposal:
            result.add("BAD_PROPOSAL_SCHEMA", "error", f"proposal missing {key}", path.as_posix())
            ok = False
    if str(proposal.get("op_name")) != op_name:
        result.add("PROPOSAL_OP_MISMATCH", "error", f"proposal op_name {proposal.get('op_name')} != {op_name}", path.as_posix())
        ok = False
    producer = _as_dict(proposal.get("producer"))
    prop_phase = str(producer.get("phase") or "")
    if prop_phase and _phase_rank(prop_phase) > _phase_rank(phase):
        result.add("PROPOSAL_PHASE_TOO_NEW", "error", f"proposal phase {prop_phase} cannot promote in {phase}", path.as_posix())
        ok = False
    if not _as_list(proposal.get("canonical_updates")):
        result.add("PROPOSAL_NO_UPDATES", "error", "proposal has no canonical_updates", path.as_posix())
        ok = False
    return ok


def _apply_update(candidate: dict[str, Any], update: dict[str, Any], proposal_path: Path, result: CompileResult) -> bool:
    target = str(update.get("target") or "").replace("\\", "/")
    section = str(update.get("section") or "")
    merge_mode = str(update.get("merge_mode") or "")
    entries = _as_list(update.get("entries"))

    if not _target_allowed(target):
        result.add("BAD_PROMOTION_TARGET", "error", f"target not allowed: {target}", proposal_path.as_posix(), target)
        return False
    if not section:
        result.add("MISSING_SECTION", "error", "canonical update missing section", proposal_path.as_posix(), target)
        return False
    if merge_mode not in MERGE_MODES:
        result.add("BAD_MERGE_MODE", "error", f"unsupported merge_mode {merge_mode}", proposal_path.as_posix(), target)
        return False
    if not entries and merge_mode != "replace_section":
        result.add("EMPTY_UPDATE", "warning", "canonical update has no entries", proposal_path.as_posix(), target)

    doc = copy.deepcopy(_as_dict(candidate.get(target)))
    if not doc:
        doc = {"version": 1, "op_name": _proposal_op_name(candidate)}

    if merge_mode == "by_id":
        ok = _merge_by_id(doc, section, entries, proposal_path, result, target)
    elif merge_mode == "merge_mapping":
        ok = _merge_mapping(doc, section, entries, proposal_path, result, target)
    else:
        if (target, section) not in REPLACE_SECTION_ALLOWLIST:
            result.add("REPLACE_SECTION_NOT_ALLOWED", "error", f"replace_section not allowed for {target}:{section}", proposal_path.as_posix(), target)
            return False
        doc[section] = copy.deepcopy(entries)
        ok = True
    if ok:
        candidate[target] = doc
    return ok


def _merge_by_id(
    doc: dict[str, Any],
    section: str,
    entries: list[Any],
    proposal_path: Path,
    result: CompileResult,
    target: str,
) -> bool:
    current = doc.get(section)
    if current is None:
        current = []
    mapping = _section_to_mapping(current)
    ok = True
    for entry in entries:
        if not isinstance(entry, dict):
            result.add("BAD_ENTRY", "error", "by_id entry must be mapping", proposal_path.as_posix(), target)
            ok = False
            continue
        entry = _normalize_relation_entry(entry) if section in {"relations", "links", "edges", "impacts"} else dict(entry)
        entry_id = str(entry.get("id") or entry.get("stable_id") or "").strip()
        if not entry_id:
            result.add("ENTRY_MISSING_ID", "error", "by_id entry missing id", proposal_path.as_posix(), target)
            ok = False
            continue
        old = mapping.get(entry_id)
        if old is not None:
            if _canonical_json(old) != _canonical_json(entry):
                result.add("DUPLICATE_ID_CONFLICT", "error", f"{entry_id} has conflicting content", target, entry_id)
                ok = False
            continue
        mapping[entry_id] = entry
    if ok:
        doc[section] = [mapping[key] for key in sorted(mapping)]
    return ok


def _merge_mapping(
    doc: dict[str, Any],
    section: str,
    entries: list[Any],
    proposal_path: Path,
    result: CompileResult,
    target: str,
) -> bool:
    current = _as_dict(doc.get(section))
    ok = True
    for entry in entries:
        if not isinstance(entry, dict):
            result.add("BAD_ENTRY", "error", "merge_mapping entry must be mapping", proposal_path.as_posix(), target)
            ok = False
            continue
        key = str(entry.get("key") or entry.get("id") or entry.get("name") or "").strip()
        value = entry.get("value", {k: v for k, v in entry.items() if k != "key"})
        if not key:
            result.add("ENTRY_MISSING_KEY", "error", "merge_mapping entry missing key/id/name", proposal_path.as_posix(), target)
            ok = False
            continue
        if key in current and _canonical_json(current[key]) != _canonical_json(value):
            result.add("MAPPING_KEY_CONFLICT", "error", f"{target}:{section}.{key} conflicts", target, key)
            ok = False
            continue
        current[key] = value
    if ok:
        doc[section] = {key: current[key] for key in sorted(current)}
    return ok


def _section_to_mapping(value: Any) -> dict[str, dict[str, Any]]:
    if isinstance(value, dict):
        out: dict[str, dict[str, Any]] = {}
        for key, item in value.items():
            if isinstance(item, dict):
                out[str(item.get("id") or key)] = {"id": str(item.get("id") or key), **item}
        return out
    out = {}
    for item in _as_list(value):
        if isinstance(item, dict) and item.get("id"):
            out[str(item["id"])] = item
    return out


def _target_allowed(target: str) -> bool:
    if not target or target.startswith(FORBIDDEN_TARGET_PREFIXES):
        return False
    path = Path(target)
    if path.is_absolute() or ".." in path.parts:
        return False
    if target.endswith((".py", ".md")) and not target.startswith(("query/",)):
        return False
    if not target.endswith((".yaml", ".yml")):
        return False
    return target.startswith(PROMOTION_TARGET_PREFIXES)


def _normalize_candidate(docs: dict[str, Any]) -> None:
    for rel, doc in list(docs.items()):
        if not isinstance(doc, dict):
            continue
        for section in ("relations", "links", "edges", "impacts"):
            if section in doc:
                entries = [_normalize_relation_entry(item) for item in _iter_entries(doc.get(section))]
                doc[section] = [item for item in sorted(entries, key=lambda x: str(x.get("id") or ""))]
        for section in ("variables", "symbols", "evidence", "template_bindings", "runtime_variables", "branches", "nodes"):
            if section in doc and isinstance(doc[section], list):
                doc[section] = sorted(doc[section], key=lambda x: str(x.get("id") or x.get("canonical_name") or "") if isinstance(x, dict) else str(x))
        docs[rel] = doc


def _normalize_relation_entry(item: dict[str, Any]) -> dict[str, Any]:
    out = dict(item)
    if "expression" not in out and "expr" in out:
        expr = out.pop("expr")
        out["expression"] = expr if isinstance(expr, dict) else {"op": "raw", "value": expr}
    if "source_ids" not in out:
        source = out.pop("source_id", out.pop("source", out.pop("from", None)))
        if source is not None:
            out["source_ids"] = _as_list(source)
    if "target_ids" not in out:
        target = out.pop("target_id", out.pop("target", out.pop("to", None)))
        if target is not None:
            out["target_ids"] = _as_list(target)
    if "type" not in out and "relation" in out:
        out["type"] = out.pop("relation")
    out.setdefault("status", "proposed")
    if out.get("status") not in STATUS_ENUM:
        out["status"] = "proposed"
    return out


def _check_maturity(docs: dict[str, Any], phase: str, result: CompileResult) -> dict[str, str]:
    maturity: dict[str, str] = {}
    for rel in PHASE_FILES[_normalize_phase(phase)]:
        data = _as_dict(docs.get(rel))
        if not data:
            maturity[rel] = "empty"
            result.add("EMPTY_ARTIFACT", "error", f"{rel} is empty or missing", rel)
            continue
        status = str(data.get("status") or "").strip()
        if status == "not_applicable":
            if data.get("reason") and _as_list(data.get("evidence_refs")):
                maturity[rel] = "not_applicable"
            else:
                maturity[rel] = "placeholder"
                result.add("BAD_NOT_APPLICABLE", "error", f"{rel} not_applicable requires reason and evidence_refs", rel)
            continue
        if data.get("stale") is True or status == "stale":
            maturity[rel] = "stale"
            result.add("STALE_ARTIFACT", "warning", f"{rel} is stale", rel)
            continue
        if _as_list(data.get("conflicts")) or status == "conflicting":
            maturity[rel] = "conflicting"
            result.add("CONFLICTING_ARTIFACT", "warning", f"{rel} has conflicts", rel)
            continue
        rules = MATURITY_RULES.get(rel)
        if not rules:
            maturity[rel] = "valid"
            continue
        has_real = False
        for key in rules:
            value = data.get(key)
            if isinstance(value, dict) and value:
                has_real = True
            elif isinstance(value, list) and value:
                has_real = True
            elif value not in (None, "", {}, []):
                has_real = True
        if has_real:
            maturity[rel] = "valid"
        else:
            maturity[rel] = "placeholder"
            if _phase_rank(phase) >= _required_phase_for(rel):
                result.add("PLACEHOLDER_ARTIFACT", "error", f"{rel} has only skeleton content", rel)
    return maturity


def _validate_evidence(docs: dict[str, Any], result: CompileResult) -> None:
    evidence_ids = {eid for eid in result.entity_index if eid.startswith(("EV_", "SRC_"))}
    ev_doc = _as_dict(docs.get("registry/evidence.yaml"))
    seen_content: dict[str, str] = {}
    for item in _iter_entries(ev_doc.get("evidence")):
        ev_id = str(item.get("id") or "").strip()
        file_name = str(item.get("file") or item.get("path") or "").strip()
        if not ev_id:
            result.add("MISSING_EVIDENCE_ID", "error", "evidence entry missing id", "registry/evidence.yaml")
            continue
        if not file_name or Path(file_name).is_absolute() or ".." in Path(file_name).parts:
            result.add("BAD_EVIDENCE_PATH", "error", f"evidence {ev_id} must use repo-relative file", "registry/evidence.yaml", ev_id)
        if not _valid_lines(item.get("lines")):
            result.add("BAD_EVIDENCE_LINES", "error", f"evidence {ev_id} has invalid lines", "registry/evidence.yaml", ev_id)
        fingerprint = _canonical_json({k: item.get(k) for k in ("file", "path", "lines", "symbol", "kind", "source_hash", "excerpt_hash")})
        prev = seen_content.get(ev_id)
        if prev and prev != fingerprint:
            result.add("EVIDENCE_ID_CONFLICT", "error", f"evidence {ev_id} has conflicting definitions", "registry/evidence.yaml", ev_id)
        seen_content[ev_id] = fingerprint
        if item.get("fallback_status") and not item.get("cbm_query"):
            result.add("FALLBACK_WITHOUT_CBM_QUERY", "warning", f"evidence {ev_id} fallback should record cbm_query", "registry/evidence.yaml", ev_id)

    for rel, doc in docs.items():
        for refs, path in _find_keys(doc, "evidence_refs"):
            ref_values = refs.keys() if isinstance(refs, dict) else _as_list(refs)
            for ref in ref_values:
                ref_s = str(ref).strip()
                if ref_s and ref_s not in evidence_ids:
                    result.add("DANGLING_EVIDENCE_REF", "error", f"unknown evidence ref {ref_s}", rel, path)


def _validate_relations(docs: dict[str, Any], result: CompileResult) -> None:
    relation_count = 0
    for rel, doc in docs.items():
        if rel in {"cross_layer/behavior_graph.yaml", "cross_layer/impact_graph.yaml"}:
            continue
        data = _as_dict(doc)
        for section in ("relations", "links", "edges", "impacts"):
            for raw in _iter_entries(data.get(section)):
                item = _normalize_relation_entry(raw)
                relation_count += 1
                rel_id = str(item.get("id") or "").strip()
                rel_type = str(item.get("type") or "").strip()
                if rel_id and not (STABLE_ID_RE.match(rel_id) or LEGACY_ID_RE.match(rel_id)):
                    result.add("BAD_RELATION_ID", "error", f"bad relation id {rel_id}", rel, rel_id)
                if rel_type and rel_type not in RELATION_TYPES:
                    result.add("BAD_RELATION_TYPE", "error", f"unsupported relation type {rel_type}", rel, rel_id)
                expr = item.get("expression")
                if expr is not None and not isinstance(expr, dict):
                    result.add("BAD_EXPRESSION_AST", "error", "relation expression must be mapping AST", rel, rel_id)
                status = str(item.get("status") or "proposed")
                if status not in STATUS_ENUM:
                    result.add("BAD_STATUS", "error", f"invalid status {status}", rel, rel_id)
                if status == "confirmed" and not _as_list(item.get("evidence_refs")):
                    result.add("CONFIRMED_WITHOUT_EVIDENCE", "error", "confirmed relation requires evidence_refs", rel, rel_id)
                for ref in _collect_id_like_values(item):
                    if ref == rel_id or ref.startswith(("EV_", "SRC_")):
                        continue
                    if ref not in result.entity_index:
                        result.add("DANGLING_REFERENCE", "error", f"unknown stable id {ref}", rel, rel_id)
    result.relation_count = relation_count


def _validate_flow_kernel_boundary(docs: dict[str, Any], result: CompileResult) -> None:
    compute_ids = {
        str(item.get("id") or "")
        for item in _iter_entries(_as_dict(docs.get("flow/compute_graph.yaml")).get("compute_steps"))
        if item.get("id")
    }
    hardware_terms = ("LocalTensor", "GlobalTensor", "Queue", "UB", "L1", "L0", "set/wait", "SetFlag", "WaitFlag", "event", "barrier")
    for rel in ("flow/compute_graph.yaml", "flow/dataflow.yaml", "flow/golden_model.yaml"):
        text = _canonical_json(docs.get(rel, {}))
        if any(term.lower() in text.lower() for term in hardware_terms):
            result.add("FLOW_HARDWARE_DETAIL", "warning", f"{rel} appears to contain kernel hardware/resource detail", rel)
    for rel in ("kernel/paths.yaml", "kernel/pipeline.yaml", "kernel/branches.yaml"):
        data = _as_dict(docs.get(rel))
        for refs, path in _find_keys(data, "implements_compute_steps"):
            for ref in _as_list(refs):
                if ref and ref not in compute_ids:
                    result.add("KERNEL_UNKNOWN_COMPUTE_STEP", "error", f"kernel references unknown compute step {ref}", rel, path)


def _validate_kernel_two_step(docs: dict[str, Any], result: CompileResult) -> None:
    compile_model = _as_dict(docs.get("kernel/compile_model.yaml"))
    variables = _as_dict(docs.get("kernel/variables.yaml"))
    branches = _as_dict(docs.get("kernel/branches.yaml"))
    paths = _as_dict(docs.get("kernel/paths.yaml"))
    if _has_nonplaceholder_paths(paths):
        if result.maturity.get("kernel/compile_model.yaml") in {"empty", "placeholder"}:
            result.add("KERNEL_STEP1_MISSING", "error", "kernel paths exist but compile model is not mature", "kernel/compile_model.yaml")
        if result.maturity.get("kernel/variables.yaml") in {"empty", "placeholder"}:
            result.add("KERNEL_VARIABLES_MISSING", "error", "kernel paths exist but runtime variables are not mature", "kernel/variables.yaml")
        if result.maturity.get("kernel/branches.yaml") in {"empty", "placeholder"}:
            result.add("KERNEL_STEP2_MISSING", "error", "kernel paths exist but branches/path semantics are not mature", "kernel/branches.yaml")
    template_ids = {str(item.get("id")) for item in _iter_entries(compile_model.get("template_bindings")) if item.get("id")}
    variable_ids = {str(item.get("id")) for item in _iter_entries(variables.get("runtime_variables")) if item.get("id")}
    branch_ids = {str(item.get("id")) for item in _iter_entries(branches.get("branches")) if item.get("id")}
    for item in _iter_entries(paths.get("kernel_paths")):
        path_id = str(item.get("id") or item.get("stable_key") or "")
        for binding in _as_list(item.get("template_binding_ids")):
            if binding and binding not in template_ids and binding not in result.entity_index:
                result.add("DANGLING_TEMPLATE_BINDING", "error", f"unknown template binding {binding}", "kernel/paths.yaml", path_id)
        for var in _as_list(item.get("runtime_variable_ids")):
            if var and var not in variable_ids and var not in result.entity_index:
                result.add("DANGLING_RUNTIME_VARIABLE", "error", f"unknown runtime variable {var}", "kernel/paths.yaml", path_id)
        for branch in _as_list(item.get("branch_ids")):
            if branch and branch not in branch_ids and branch not in result.entity_index:
                result.add("DANGLING_BRANCH", "error", f"unknown branch {branch}", "kernel/paths.yaml", path_id)


def _validate_cross_layer(docs: dict[str, Any], result: CompileResult, phase: str) -> None:
    if _phase_rank(phase) < _phase_rank("phase5"):
        return
    for rel in CROSS_LAYER_FILES:
        if result.maturity.get(rel) in {"empty", "placeholder"}:
            result.add("CROSS_LAYER_NOT_BUILT", "error", f"{rel} is required for {phase}", rel)
    for rel in ("cross_layer/behavior_graph.yaml", "cross_layer/impact_graph.yaml"):
        data = _as_dict(docs.get(rel))
        node_ids = {str(item.get("id")) for item in _iter_entries(data.get("nodes")) if item.get("id")}
        for item in _iter_entries(data.get("edges")):
            src = str(item.get("source_id") or item.get("source") or "")
            dst = str(item.get("target_id") or item.get("target") or "")
            if src and src not in node_ids and src not in result.entity_index:
                result.add("GRAPH_MISSING_NODE", "error", f"edge source {src} missing", rel, str(item.get("id") or ""))
            if dst and dst not in node_ids and dst not in result.entity_index:
                result.add("GRAPH_MISSING_NODE", "error", f"edge target {dst} missing", rel, str(item.get("id") or ""))


def _validate_contracts(docs: dict[str, Any], result: CompileResult, phase: str) -> None:
    if _phase_rank(phase) < _phase_rank("phase7"):
        return
    for rel in CONTRACT_FILES + QUERY_FILES:
        if result.maturity.get(rel) in {"empty", "placeholder"}:
            result.add("DERIVED_VIEW_NOT_BUILT", "error", f"{rel} is required for {phase}", rel)
    code_change = _as_dict(docs.get("contracts/code_change.yaml"))
    for key in ("target", "upstream", "downstream", "recommended_checks"):
        if key not in code_change:
            result.add("CODE_CHANGE_CONTRACT_INCOMPLETE", "error", f"contracts/code_change.yaml missing {key}", "contracts/code_change.yaml")


def _validate_stale(uo_root: Path, result: CompileResult, phase: str) -> None:
    if _phase_rank(phase) < _phase_rank("final"):
        return
    stale_path = uo_root / "archive" / "runs" / "stale_artifacts.yaml"
    if not stale_path.exists():
        return
    data = _read_yaml(stale_path, result)
    stale = [item for item in _as_list(data.get("stale_artifacts")) if isinstance(item, dict) and item.get("stale")]
    if stale:
        result.add("STALE_ARTIFACTS_REMAIN", "error", f"{len(stale)} stale artifacts remain", stale_path.as_posix())


def _build_graphs(docs: dict[str, Any], op_name: str) -> None:
    entity_result = CompileResult(op_name=op_name)
    source_docs = {
        rel: data
        for rel, data in docs.items()
        if rel not in {"cross_layer/behavior_graph.yaml", "cross_layer/impact_graph.yaml"}
    }
    entity_index = build_entity_index(source_docs, entity_result)
    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[str, dict[str, Any]] = {}

    for eid, meta in entity_index.items():
        nodes[eid] = {
            "id": eid,
            "kind": meta.get("kind"),
            "label": meta.get("canonical_name") or eid,
            "artifact": meta.get("artifact"),
            "status": "confirmed" if meta.get("evidence_refs") else "proposed",
            "evidence_refs": meta.get("evidence_refs") or [],
        }

    for rel, doc in source_docs.items():
        data = _as_dict(doc)
        for section in ("relations", "links", "edges"):
            for item in _iter_entries(data.get(section)):
                item = _normalize_relation_entry(item)
                sources = _as_list(item.get("source_ids"))
                targets = _as_list(item.get("target_ids"))
                if not sources or not targets:
                    refs = sorted(_collect_id_like_values(item))
                    if len(refs) >= 2:
                        sources = [refs[0]]
                        targets = refs[1:]
                for src in sources:
                    for dst in targets:
                        if not src or not dst or src == dst:
                            continue
                        edge_id = str(item.get("id") or f"REL_{_stable_slug(src)}_TO_{_stable_slug(dst)}")
                        edge_key = f"{edge_id}:{src}:{dst}"
                        edges[edge_key] = {
                            "id": edge_id,
                            "type": item.get("type") or "affects",
                            "source_id": src,
                            "target_id": dst,
                            "status": item.get("status") or "proposed",
                            "artifact": rel,
                            "evidence_refs": _as_list(item.get("evidence_refs")),
                        }

    behavior = _as_dict(docs.get("cross_layer/behavior_graph.yaml"))
    behavior.update(
        {
            "version": 1,
            "op_name": op_name,
            "purpose": "deterministically built behavior graph",
            "nodes": [nodes[key] for key in sorted(nodes)],
            "edges": [edges[key] for key in sorted(edges)],
            "unresolved": behavior.get("unresolved", []),
            "conflicts": behavior.get("conflicts", []),
        }
    )
    docs["cross_layer/behavior_graph.yaml"] = behavior

    impact_edges = _derive_impact_edges(edges)
    impact = _as_dict(docs.get("cross_layer/impact_graph.yaml"))
    impact.update(
        {
            "version": 1,
            "op_name": op_name,
            "purpose": "deterministically derived impact graph",
            "nodes": [nodes[key] for key in sorted(nodes)],
            "edges": impact_edges,
            "impacts": impact_edges,
            "traversal_policy": {"max_depth": 8, "cycle_protection": "visited_set", "edge_types": sorted(RELATION_TYPES)},
            "unresolved": impact.get("unresolved", []),
            "conflicts": impact.get("conflicts", []),
        }
    )
    docs["cross_layer/impact_graph.yaml"] = impact


def _derive_impact_edges(edges: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    adjacency: dict[str, list[dict[str, Any]]] = {}
    for edge in edges.values():
        adjacency.setdefault(str(edge.get("source_id")), []).append(edge)
    impacts: dict[str, dict[str, Any]] = {}
    for start in sorted(adjacency):
        queue: list[tuple[str, int, list[str]]] = [(start, 0, [])]
        visited = {start}
        while queue:
            node, depth, path = queue.pop(0)
            if depth >= 8:
                continue
            for edge in adjacency.get(node, []):
                dst = str(edge.get("target_id"))
                impact_id = f"REL_IMPACT_{_stable_slug(start)}_TO_{_stable_slug(dst)}"
                relation = "direct" if depth == 0 else "transitive"
                impacts[f"{impact_id}:{relation}"] = {
                    "id": impact_id,
                    "type": "affects",
                    "source_id": start,
                    "target_id": dst,
                    "impact_kind": relation,
                    "confidence": "confirmed" if edge.get("status") == "confirmed" else "possible",
                    "path": path + [str(edge.get("id"))],
                    "status": edge.get("status") or "proposed",
                    "evidence_refs": edge.get("evidence_refs") or [],
                }
                if dst in visited:
                    impacts[f"{impact_id}:cycle"] = {
                        "id": impact_id + "_CYCLE",
                        "type": "affects",
                        "source_id": start,
                        "target_id": dst,
                        "impact_kind": "cycle",
                        "confidence": "possible",
                        "path": path + [str(edge.get("id"))],
                        "status": "unresolved",
                        "evidence_refs": [],
                    }
                    continue
                visited.add(dst)
                queue.append((dst, depth + 1, path + [str(edge.get("id"))]))
    return [impacts[key] for key in sorted(impacts)]


def _write_compile_outputs(uo_root: Path, result: CompileResult) -> None:
    summary = {
        "entity_count": result.entity_count,
        "alias_count": result.alias_count,
        "evidence_count": result.evidence_count,
        "relation_count": result.relation_count,
        "unresolved_count": result.unresolved_count,
        "conflict_count": result.conflict_count,
    }
    out = {
        "version": 1,
        "op_name": result.op_name,
        "phase": result.phase,
        "compiled_at": _now(),
        "status": result.status,
        "summary": summary,
        "maturity": result.maturity,
        "issues": [issue.to_dict() for issue in result.issues],
    }
    write_text(uo_root / "archive" / "runs" / "kb_compile_report.yaml", _to_yaml(out))
    write_text(
        uo_root / "archive" / "runs" / "canonical_hashes.yaml",
        _to_yaml({"version": 1, "op_name": result.op_name, "generated_at": _now(), "artifact_hashes": result.artifact_hashes}),
    )
    write_text(
        uo_root / "archive" / "runs" / "entity_index.yaml",
        _to_yaml({"version": 1, "op_name": result.op_name, "generated_at": _now(), "entities": result.entity_index}),
    )


def _write_promotion_report(uo_root: Path, result: CompileResult) -> None:
    write_text(uo_root / "archive" / "runs" / "kb_promotion_report.yaml", _to_yaml(result.promotion_report))
    conflicts = [issue.to_dict() for issue in result.issues if issue.severity == "error" or "CONFLICT" in issue.code]
    if conflicts:
        out = uo_root / "archive" / "conflicts" / f"promotion_{datetime.now(tz=timezone.utc).strftime('%Y%m%d%H%M%S')}.yaml"
        write_text(out, _to_yaml({"version": 1, "op_name": result.op_name, "conflicts": conflicts}))


def _promotion_report(
    op_name: str,
    phase: str,
    status: str,
    applied: list[dict[str, Any]],
    result: CompileResult,
    before_hashes: dict[str, str],
    after_hashes: dict[str, str],
) -> dict[str, Any]:
    return {
        "version": 1,
        "op_name": op_name,
        "phase": phase,
        "status": status,
        "promoted_at": _now(),
        "applied_updates": applied,
        "changed_artifacts": sorted(path for path, digest in after_hashes.items() if before_hashes.get(path) != digest),
        "issues": [issue.to_dict() for issue in result.issues],
    }


def _atomic_write_docs(uo_root: Path, candidate: dict[str, Any], *, only_changed_against: dict[str, Any]) -> None:
    for rel, data in candidate.items():
        if rel.startswith(("archive/", "cbm/")):
            continue
        old = only_changed_against.get(rel)
        if _canonical_json(old) == _canonical_json(data):
            continue
        path = uo_root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = _to_yaml(data)
        fd, tmp_name = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as tmp:
                tmp.write(payload)
            os.replace(tmp_name, path)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)


def _hash_artifacts(uo_root: Path, result: CompileResult) -> None:
    result.artifact_hashes = {}
    for path in sorted(uo_root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(uo_root).as_posix()
        if rel.startswith(("archive/runs/kb_compile_report", "archive/runs/kb_promotion_report", "archive/runs/canonical_hashes", "archive/runs/entity_index")):
            continue
        if rel.startswith(("cbm/", "archive/cbm/")):
            continue
        if path.suffix.lower() not in {".yaml", ".yml", ".md", ".json"}:
            continue
        result.artifact_hashes[rel] = hashlib.sha256(path.read_bytes()).hexdigest()


def _hash_docs(docs: dict[str, Any]) -> dict[str, str]:
    return {rel: hashlib.sha256(_canonical_json(data).encode("utf-8")).hexdigest() for rel, data in docs.items()}


def _hash_artifacts_from_docs(docs: dict[str, Any]) -> dict[str, str]:
    return _hash_docs({rel: data for rel, data in docs.items() if not rel.startswith(("archive/", "cbm/"))})


def _iter_entries(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        out = []
        for key, item in value.items():
            if isinstance(item, dict):
                merged = {"id": str(item.get("id") or key), **item}
                out.append(merged)
        return out
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value in (None, "", {}, []):
        return []
    return [value]


def _find_keys(value: Any, key: str, path: str = "") -> list[tuple[Any, str]]:
    found: list[tuple[Any, str]] = []
    if isinstance(value, dict):
        for k, v in value.items():
            child = f"{path}.{k}" if path else str(k)
            if k == key:
                found.append((v, child))
            found.extend(_find_keys(v, key, child))
    elif isinstance(value, list):
        for idx, item in enumerate(value):
            found.extend(_find_keys(item, key, f"{path}[{idx}]"))
    return found


def _collect_id_like_values(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for k, v in value.items():
            if str(k).endswith(("_id", "_ids", "_ref", "_refs")) or str(k) in {"var", "source", "target", "source_id", "target_id"}:
                for item in _as_list(v):
                    if isinstance(item, str):
                        found.add(item)
            found.update(_collect_id_like_values(v))
    elif isinstance(value, list):
        for item in value:
            found.update(_collect_id_like_values(item))
    elif isinstance(value, str):
        for token in re.findall(r"\b(?:SYM|VAR|REL|EV|SRC|KEY|FAM|KPATH|KBR|KTPL|CL|CON|VIEW|BUF|SYNC|RES)_[A-Z0-9_]+\b", value):
            found.add(token)
        for token in re.findall(r"\b(?:TF\d+|K\d+|C\d+|D\d+|P\d+)\b", value):
            found.add(token)
    return found


def _valid_lines(value: Any) -> bool:
    if isinstance(value, int):
        return value > 0
    if isinstance(value, list):
        return len(value) in {1, 2} and all(isinstance(item, int) and item > 0 for item in value)
    if isinstance(value, dict):
        start = value.get("start")
        end = value.get("end", start)
        return isinstance(start, int) and isinstance(end, int) and 0 < start <= end
    return False


def _has_nonplaceholder_paths(paths: dict[str, Any]) -> bool:
    entries = paths.get("kernel_paths")
    return bool(entries)


def _phase_rank(phase: str) -> int:
    return {"phase2": 2, "phase4": 4, "phase5": 5, "phase7": 7, "final": 8}.get(_normalize_phase(phase), 8)


def _required_phase_for(rel: str) -> int:
    if rel.startswith("kernel/"):
        return 4
    if rel.startswith("cross_layer/"):
        return 5
    if rel.startswith(("query/", "contracts/")):
        return 7
    return 2


def _normalize_phase(phase: str) -> str:
    phase = str(phase or "final").lower().replace("_", "")
    aliases = {"2": "phase2", "phase2": "phase2", "phase2host": "phase2", "4": "phase4", "phase4": "phase4", "5": "phase5", "phase5": "phase5", "7": "phase7", "phase7": "phase7", "8": "final", "phase8": "final", "final": "final"}
    if phase not in aliases:
        raise ValueError(f"unsupported phase: {phase}")
    return aliases[phase]


def _kind_from_prefix(item_id: str) -> str:
    if item_id.startswith("SYM_"):
        return "symbol"
    if item_id.startswith("VAR_"):
        return "variable"
    if item_id.startswith("REL_"):
        return "relation"
    if item_id.startswith(("EV_", "SRC_")):
        return "evidence"
    if item_id.startswith("KEY_"):
        return "key"
    if item_id.startswith("FAM_") or item_id.startswith("TF"):
        return "family"
    if item_id.startswith("KTPL_"):
        return "template_binding"
    if item_id.startswith("KPATH_") or re.match(r"K\d+", item_id):
        return "kernel_path"
    if item_id.startswith("KBR_"):
        return "kernel_branch"
    if item_id.startswith("C"):
        return "compute_step"
    if item_id.startswith(("BUF_", "SYNC_", "RES_")):
        return "resource" if not item_id.startswith("SYNC_") else "sync"
    return ""


def _proposal_op_name(docs: dict[str, Any]) -> str:
    for data in docs.values():
        if isinstance(data, dict) and data.get("op_name"):
            return str(data["op_name"])
    return "unknown"


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _to_yaml(data: Any) -> str:
    if yaml is not None:
        class _NoAliasDumper(yaml.SafeDumper):
            def ignore_aliases(self, data: Any) -> bool:  # type: ignore[override]
                return True

        return yaml.dump(data, Dumper=_NoAliasDumper, allow_unicode=True, sort_keys=False)
    return json.dumps(data, ensure_ascii=False, indent=2)


def _stable_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", str(value)).strip("_").upper()
    return slug or "UNKNOWN"


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Promote and validate understand-operator canonical KB artifacts")
    sub = parser.add_subparsers(dest="command")

    promote = sub.add_parser("promote", help="Promote proposal envelope files into canonical KB")
    promote.add_argument("repo_root", type=Path)
    promote.add_argument("--op-name", required=True)
    promote.add_argument("--phase", default="phase2")
    promote.add_argument("--proposal", action="append", type=Path, help="Specific proposal path; defaults to archive/proposals/*.yaml")

    validate = sub.add_parser("validate", help="Validate canonical KB without modifying canonical artifacts")
    validate.add_argument("repo_root", type=Path)
    validate.add_argument("--op-name", required=True)
    validate.add_argument("--phase", default="final")
    validate.add_argument("--check-only", action="store_true", help="Do not write reports")

    parser.add_argument("repo_root", nargs="?", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--op-name", dest="legacy_op_name", help=argparse.SUPPRESS)
    parser.add_argument("--phase", dest="legacy_phase", default="final", help=argparse.SUPPRESS)
    parser.add_argument("--check-only", dest="legacy_check_only", action="store_true", help=argparse.SUPPRESS)

    args = parser.parse_args(argv)
    if args.command is None:
        if args.repo_root is None or not args.legacy_op_name:
            parser.print_help()
            return 2
        repo_root = args.repo_root.resolve()
        op_name = safe_op_name(args.legacy_op_name, repo_root)
        uo_root = operator_root(repo_root, op_name)
        result = validate_kb(uo_root, op_name, phase=args.legacy_phase, write_outputs=not args.legacy_check_only)
    elif args.command == "promote":
        repo_root = args.repo_root.resolve()
        op_name = safe_op_name(args.op_name, repo_root)
        uo_root = operator_root(repo_root, op_name)
        result = promote_kb(uo_root, op_name, phase=args.phase, proposal_paths=args.proposal)
    else:
        repo_root = args.repo_root.resolve()
        op_name = safe_op_name(args.op_name, repo_root)
        uo_root = operator_root(repo_root, op_name)
        result = validate_kb(uo_root, op_name, phase=args.phase, write_outputs=not args.check_only)

    print(
        json.dumps(
            {
                "status": result.status,
                "phase": result.phase,
                "issues": len(result.issues),
                "entity_count": result.entity_count,
                "relation_count": result.relation_count,
                "compile_report": str(uo_root / "archive" / "runs" / "kb_compile_report.yaml"),
                "promotion_report": str(uo_root / "archive" / "runs" / "kb_promotion_report.yaml"),
            },
            ensure_ascii=False,
        )
    )
    return 0 if result.status != "fail" else 2


if __name__ == "__main__":
    raise SystemExit(main())
