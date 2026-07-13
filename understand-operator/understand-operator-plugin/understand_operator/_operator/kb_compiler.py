from __future__ import annotations

import argparse
import copy
import shutil
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
from understand_operator._operator.evidence import validate_evidence_closure
from understand_operator._operator.yaml_gate import (
    ORCHESTRATOR_AGENTS,
    artifact_owner,
    resource_semantic_errors,
    serialize_yaml_checked,
    validate_yaml_document,
    yaml_text,
)

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]


STABLE_ID_RE = re.compile(
    r"^(SYM|VAR|REL|EV|SRC|KEY|FAM|COMP|GOLD|KPATH|KBR|KTPL|CL|CON|VIEW|BUF|SYNC|RES|TDF|KVAR|KDEC|PIPE|COV|NUM)_[A-Z0-9_]+$"
)
PROPOSAL_HASH_RUNTIME_FIELDS = frozenset(
    {
        "proposal_hash",
        "consumed_at",
        "status",
        "promoted_at",
        "rejected_at",
        "failure_reason",
        "transaction_id",
        "recovery_status",
    }
)
TEST_CONSUMABLE_FILES = (
    "operator.yaml",
    "tiling/key_space.yaml",
    "tiling/exhaustive_key_space.yaml",
    "tiling/constraints.yaml",
    "tiling/families.yaml",
    "tiling/data_model.yaml",
    "tiling/coverage_model.yaml",
    "flow/golden_model.yaml",
    "flow/numerical_model.yaml",
    "kernel/compile_model.yaml",
    "kernel/variables.yaml",
    "kernel/paths.yaml",
    "kernel/branches.yaml",
    "contracts/testcase.yaml",
)
ENTITY_KINDS = {
    "symbol",
    "variable",
    "relation",
    "evidence",
    "key",
    "family",
    "compute_step",
    "golden_step",
    "template_binding",
    "kernel_path",
    "kernel_branch",
    "buffer",
    "sync",
    "resource",
    "view",
    "contract",
    "tilingdata_field",
    "kernel_runtime_variable",
    "tilingdata_read",
    "kernel_decision_point",
    "compile_variable",
    "compile_decision",
    "pipeline_stage",
    "coverage_obligation",
    "numerical_policy",
}
PREFIX_TO_KIND = {
    "SYM_": "symbol",
    "VAR_": "variable",
    "REL_": "relation",
    "EV_": "evidence",
    "SRC_": "evidence",
    "KEY_": "key",
    "FAM_": "family",
    "COMP_": "compute_step",
    "GOLD_": "golden_step",
    "KTPL_": "template_binding",
    "KPATH_": "kernel_path",
    "KBR_": "kernel_branch",
    "CON_": "contract",
    "VIEW_": "view",
    "BUF_": "buffer",
    "SYNC_": "sync",
    "RES_": "resource",
    "TDF_": "tilingdata_field",
    "KVAR_": "kernel_runtime_variable",
    "KDEC_": "kernel_decision_point",
    "PIPE_": "pipeline_stage",
    "COV_": "coverage_obligation",
    "NUM_": "numerical_policy",
}
PREFIX_KIND_ALIASES = {
    "VAR_": {"variable", "tilingdata_field", "kernel_runtime_variable", "compile_variable"},
    "TDF_": {"tilingdata_field", "tilingdata_read"},
    "KVAR_": {"kernel_runtime_variable", "variable"},
    "KDEC_": {"kernel_decision_point", "compile_decision"},
    # Compatibility for KBs generated before the dedicated COMP_ namespace.
    "COV_": {"coverage_obligation", "compute_step"},
}
LEGACY_ID_RE = re.compile(r"^(TF\d+|K\d+|C\d+|D\d+|P\d+)$")
STATUS_ENUM = {"confirmed", "proposed", "uncertain", "conflicting", "unresolved", "deprecated"}
EXECUTION_UNITS = {"VECTOR", "CUBE", "DATA_MOVE", "SYNC", "SCALAR_CONTROL", "UNKNOWN"}
EXECUTION_PREFIX = {
    "VECTOR": "[Vector]",
    "CUBE": "[Cube]",
    "DATA_MOVE": "[DataMove]",
    "SYNC": "[Sync]",
    "SCALAR_CONTROL": "[Scalar]",
    "UNKNOWN": "[Unknown]",
}
EXECUTION_OPERATION_DEFAULT = {
    "VECTOR": "vector_compute",
    "CUBE": "matmul",
    "DATA_MOVE": "data_move",
    "SYNC": "sync",
    "SCALAR_CONTROL": "scalar_control",
    "UNKNOWN": "unknown",
}
VECTOR_API_PATTERNS = (
    "ascendc::add",
    "ascendc::sub",
    "ascendc::mul",
    "ascendc::div",
    "ascendc::exp",
    "ascendc::log",
    "ascendc::sqrt",
    "ascendc::abs",
    "ascendc::max",
    "ascendc::min",
    "ascendc::reducemax",
    "ascendc::reducesum",
    "ascendc::cast",
    "ascendc::compare",
    "ascendc::select",
    "reduce_max",
    "reduce_sum",
)
CUBE_API_PATTERNS = (
    "matmul.iterate",
    "matmulimpl",
    "gettensorc",
    "ascendc::mmad",
    "mmadwithsparse",
    "mmad",
)
DATA_MOVE_PATTERNS = (
    "datacopy",
    "copyin",
    "copyout",
    "load",
    "store",
    "enqueue",
    "deque",
    "enque",
    "deque",
    "workspace",
    "gm to ub",
    "gm->ub",
    "gm to l1",
    "l1 to l0",
    "l0c to gm",
    "ub to gm",
)
SYNC_PATTERNS = (
    "pipebarrier",
    "syncall",
    "setflag",
    "waitflag",
    "event",
    "barrier",
    "wait",
)
SCALAR_PATTERNS = (
    "blockidx",
    "offset",
    "index",
    "loop bound",
    "tile size",
    "tail",
    "branch",
)
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
    "tiling/exhaustive_key_space.yaml",
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
    "manifest.yaml": ("artifact_version", "layers"),
    "index.yaml": ("canonical_files", "qa_routes"),
    "operator.yaml": ("scope", "entrypoints", "io"),
    "registry/variables.yaml": ("variables",),
    "registry/symbols.yaml": ("symbols",),
    "registry/aliases.yaml": ("aliases", "conflicts"),
    "registry/evidence.yaml": ("evidence",),
    "tiling/variables.yaml": ("variables", "tiling_mechanism"),
    "tiling/constraints.yaml": ("relations", "variable_constraints", "input_realization"),
    "tiling/key_space.yaml": ("fields", "derived_fields", "constants"),
    "tiling/exhaustive_key_space.yaml": ("enumeration_source", "summary", "template_blocks"),
    "tiling/families.yaml": ("families", "dispatch_tree"),
    "tiling/data_model.yaml": ("structs", "family_to_struct", "numeric_overlay"),
    "tiling/coverage_model.yaml": ("coverage_policy", "family_obligations", "key_field_obligations"),
    "tiling/evidence_index.yaml": ("symbols", "evidence_policy"),
    "flow/compute_graph.yaml": ("compute_steps", "outputs"),
    "flow/dataflow.yaml": ("dataflow_edges", "tensor_lifecycle"),
    "flow/golden_model.yaml": ("golden_inputs", "golden_outputs", "golden_generation_contract"),
    "flow/numerical_model.yaml": ("dtype_policy", "tolerance_policy", "randomness_policy"),
    "evidence/fact_index.yaml": ("facts", "evidence_refs"),
    "evidence/source_index.yaml": ("source_spans", "symbols"),
    "evidence/artifact_dependencies.yaml": ("dependencies", "artifact_to_source"),
    "evidence/issues.yaml": ("missing", "conflicts", "warnings", "unknowns"),
    "kernel/compile_model.yaml": ("template_bindings", "compile_time_configs", "compile_variables", "compile_decisions"),
    "kernel/variables.yaml": ("runtime_variables", "tilingdata_reads", "path_decision_points"),
    "kernel/branches.yaml": ("branches", "path_semantics", "dataflow_links", "resource_links"),
    "kernel/paths.yaml": ("kernel_paths",),
    "kernel/pipeline.yaml": ("pipelines", "stages", "resources"),
    "kernel/resources.yaml": ("buffers", "sync_events", "workspaces", "resources"),
    "cross_layer/input_to_tiling.yaml": ("nodes", "edges", "relations", "links"),
    "cross_layer/tiling_to_kernel.yaml": ("nodes", "edges", "relations", "links"),
    "cross_layer/variable_lineage.yaml": ("variables", "lineage", "relations", "edges"),
    "cross_layer/behavior_graph.yaml": ("nodes", "edges"),
    "cross_layer/impact_graph.yaml": ("nodes", "edges", "impacts"),
    "query/routes.yaml": ("routes",),
    "query/terminology.yaml": ("terms", "aliases"),
    "contracts/query.yaml": ("required_response_fields", "routes"),
    "contracts/code_change.yaml": ("target", "upstream", "downstream"),
    "contracts/pr_review.yaml": ("review_slices", "recommended_checks"),
    "contracts/testcase.yaml": ("version", "source", "interface", "typed_constraints", "coverage_obligations", "golden_contract"),
    "test/contract.yaml": ("input_domain", "typed_constraints", "kernel_branch_obligations"),
    "quality.yaml": ("status", "checks", "decision"),
}
ALLOWED_EMPTY_MATURITY_FILES = {
    "registry/aliases.yaml",
    # Phase-aware promotion tests and incremental runs may not have reached the
    # evidence audit yet.  Phase barriers/final quality enforce non-empty
    # evidence where it is required for handoff.
    "tiling/evidence_index.yaml",
    "flow/golden_model.yaml",
    "flow/numerical_model.yaml",
    "evidence/fact_index.yaml",
    "evidence/source_index.yaml",
    "evidence/issues.yaml",
}


def _default_entity_scope(kind: str, artifact: str) -> str:
    """Infer a stable domain scope when producers omit the optional field.

    Canonical names such as ``block_size`` legitimately occur in both the
    tiling key model and a kernel template binding.  Treating every omitted
    scope as the same empty scope creates false duplicate-name warnings and
    encourages destructive bulk renames.  Explicit scopes still win.
    """
    domain = artifact.split("/", 1)[0] if "/" in artifact else "root"
    if domain in {"tiling", "flow", "kernel", "cross_layer", "evidence", "registry"}:
        return domain
    if artifact.startswith("contracts/"):
        return "contract"
    if kind == "evidence":
        return "evidence"
    return domain


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
    consumability: dict[str, dict[str, Any]] = field(default_factory=dict)
    promotion_report: dict[str, Any] = field(default_factory=dict)
    normalization: dict[str, Any] = field(default_factory=dict)
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


@dataclass
class TransactionResult:
    transaction_id: str
    planned_artifacts: list[str]
    committed_artifacts: list[str] = field(default_factory=list)
    rolled_back_artifacts: list[str] = field(default_factory=list)
    metadata_artifacts: list[str] = field(default_factory=list)
    transaction_status: str = "pending"
    recovery_status: str = ""
    failure_reason: str = ""


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
    _validate_flow_step_graph(docs, result)
    _validate_kernel_two_step(docs, result)
    _validate_cross_layer(docs, result, phase)
    _validate_contracts(docs, result, phase)
    _validate_stale(uo_root, result, phase)
    if _phase_rank(phase) >= _phase_rank("final"):
        result.consumability = _validate_consumability(docs, result)
    if write_outputs:
        _write_compile_outputs(uo_root, result)
    return result


def promote_kb(
    uo_root: Path,
    op_name: str,
    *,
    phase: str = "phase2",
    run_id: str | None = None,
    proposal_paths: list[Path] | None = None,
    write_outputs: bool = True,
) -> CompileResult:
    phase = _normalize_phase(phase)
    result = CompileResult(op_name=op_name, phase=phase)
    if write_outputs:
        _recover_pending_transactions(uo_root, op_name)
    docs = _load_all_existing_docs(uo_root, result)
    before_hashes = _hash_docs(docs)
    proposals = _load_proposals(uo_root, result, run_id=run_id, proposal_paths=proposal_paths)
    candidate = copy.deepcopy(docs)

    applied: list[dict[str, Any]] = []
    proposal_ids: list[str] = []
    proposal_hashes: dict[str, str] = {}
    skipped: list[dict[str, Any]] = []
    for proposal_path, proposal in proposals:
        if not _validate_proposal_envelope(proposal_path, proposal, op_name, phase, result):
            continue
        proposal_id = str(proposal.get("proposal_id") or "")
        proposal_hash = _computed_proposal_hash(proposal)
        if not _validate_proposal_hash(proposal_path, proposal, proposal_hash, result):
            continue
        state = _proposal_consumption_state(uo_root, proposal_id, proposal_hash, result)
        if state == "already_promoted":
            skipped.append({"proposal_id": proposal_id, "proposal_hash": proposal_hash, "code": "ALREADY_PROMOTED"})
            continue
        if state == "conflict":
            continue
        proposal_ids.append(proposal_id)
        proposal_hashes[proposal_id] = proposal_hash
        producer_agent = str(_as_dict(proposal.get("producer")).get("agent") or "")
        for update in _as_list(proposal.get("canonical_updates")):
            if not isinstance(update, dict):
                result.add("BAD_PROPOSAL_UPDATE", "error", "canonical_updates entries must be mappings", proposal_path.as_posix())
                continue
            if not _validate_update_owner(producer_agent, update, proposal_path, result):
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
        result.promotion_report = _promotion_report(
            op_name,
            phase,
            "failed",
            applied,
            result,
            before_hashes,
            {},
            run_id=run_id,
            proposal_ids=proposal_ids,
            proposal_hashes=proposal_hashes,
            skipped_proposals=skipped,
        )
        if write_outputs:
            _write_promotion_report(uo_root, result)
            _write_rejected_proposals(uo_root, run_id, proposals, result)
        return result

    candidate_result = CompileResult(op_name=op_name, phase=phase)
    touched_artifacts = {
        str(item.get("target") or "").replace("\\", "/")
        for _path, proposal in proposals
        for item in _as_list(proposal.get("canonical_updates"))
        if isinstance(item, dict)
    }
    _normalize_candidate(candidate, touched_artifacts=touched_artifacts, result=candidate_result, op_name=op_name)
    _build_graphs(candidate, op_name, candidate_result)
    candidate_result.artifact_hashes = _hash_artifacts_from_docs(candidate)
    candidate_result.maturity = _check_maturity(candidate, phase, candidate_result)
    candidate_result.entity_index = build_entity_index(candidate, candidate_result)
    _validate_evidence(candidate, candidate_result)
    _validate_relations(candidate, candidate_result)
    _validate_flow_kernel_boundary(candidate, candidate_result)
    _validate_flow_step_graph(candidate, candidate_result)
    _validate_kernel_two_step(candidate, candidate_result)
    _validate_cross_layer(candidate, candidate_result, phase)
    _validate_contracts(candidate, candidate_result, phase)

    result.issues.extend(candidate_result.issues)
    if candidate_result.status == "fail":
        result.status = "fail"
        result.promotion_report = _promotion_report(
            op_name,
            phase,
            "failed",
            applied,
            result,
            before_hashes,
            {},
            run_id=run_id,
            proposal_ids=proposal_ids,
            proposal_hashes=proposal_hashes,
            skipped_proposals=skipped,
        )
        if write_outputs:
            _write_promotion_report(uo_root, result)
            _write_rejected_proposals(uo_root, run_id, proposals, result)
        return result
    if candidate_result.status == "warn":
        result.status = "warn"
    result.entity_index = candidate_result.entity_index
    result.maturity = candidate_result.maturity
    result.artifact_hashes = candidate_result.artifact_hashes
    result.relation_count = candidate_result.relation_count
    result.unresolved_count = candidate_result.unresolved_count
    result.conflict_count = candidate_result.conflict_count
    result.normalization = candidate_result.normalization

    after_hashes = _hash_artifacts_from_docs(candidate)
    transaction: TransactionResult | None = None
    result.promotion_report = _promotion_report(
        op_name,
        phase,
        "promoted",
        applied,
        result,
        before_hashes,
        after_hashes,
        run_id=run_id,
        proposal_ids=proposal_ids,
        proposal_hashes=proposal_hashes,
        skipped_proposals=skipped,
    )
    if write_outputs:
        stale_payload = _compute_stale_resolution(
            uo_root,
            phase=phase,
            run_id=run_id,
            changed_artifacts=sorted(path for path, digest in after_hashes.items() if before_hashes.get(path) != digest),
            artifact_hashes=after_hashes,
            validation_status="pass" if result.status != "fail" else "fail",
        )
        payloads = _build_promotion_payloads(
            uo_root,
            candidate,
            docs,
            result,
            run_id=run_id,
            proposal_ids=proposal_ids,
            proposal_hashes=proposal_hashes,
            before_hashes=before_hashes,
            after_hashes=after_hashes,
            stale_payload=stale_payload,
        )
        transaction = _execute_promotion_transaction(
            uo_root,
            op_name,
            payloads,
            phase=phase,
            run_id=run_id,
            proposal_hashes=proposal_hashes,
        )
        result.promotion_report["transaction_id"] = transaction.transaction_id
        result.promotion_report["metadata_artifacts"] = transaction.metadata_artifacts
        result.promotion_report["transaction_status"] = transaction.transaction_status
        result.promotion_report["recovery_status"] = transaction.recovery_status
        result.promotion_report["failure_reason"] = transaction.failure_reason
        result.promotion_report["committed_artifacts"] = transaction.committed_artifacts
        result.promotion_report["rolled_back_artifacts"] = transaction.rolled_back_artifacts
        if transaction.transaction_status == "commit_complete":
            pass
        elif transaction.transaction_status in {"canonical_committed", "metadata_pending"}:
            result.add(
                "PROMOTION_METADATA_PENDING",
                "warning",
                "canonical committed but metadata pending recovery",
                "archive/runs/transactions",
            )
            result.promotion_report["status"] = "promoted"
            result.promotion_report["transaction_status"] = "metadata_pending"
        else:
            result.add("PROMOTION_TRANSACTION_ROLLED_BACK", "error", transaction.failure_reason, "canonical_kb")
            result.promotion_report["status"] = "rolled_back"
            _write_promotion_report(uo_root, result)
            _write_rejected_proposals(uo_root, run_id, proposals, result)
            return result
    return result


def collect_entity_definitions(docs: dict[str, Any], result: CompileResult | None = None) -> dict[str, dict[str, Any]]:
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
            prefix = next((p for p in PREFIX_KIND_ALIASES if item_id.startswith(p)), "")
            allowed = PREFIX_KIND_ALIASES.get(prefix, {expected_kind})
            if kind not in allowed:
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
            "scope": meta.get("scope") or _default_entity_scope(kind, artifact),
            "data_type": meta.get("data_type") or meta.get("dtype") or "",
            "evidence_refs": _as_list(meta.get("evidence_refs")),
            "status": meta.get("status") if meta.get("status") in STATUS_ENUM else "",
            "artifacts": [{"artifact": artifact, "section": section}],
        }

    for rel in sorted(docs):
        data = docs[rel]
        doc = _as_dict(data)
        if rel == "registry/symbols.yaml":
            for item in _iter_entries(doc.get("symbols")):
                add(str(item.get("id")), "symbol", rel, "symbols", item)
        if rel == "registry/variables.yaml":
            for item in _iter_entries(doc.get("variables")):
                kind = str(item.get("kind") or "variable")
                add(str(item.get("id")), kind if kind in ENTITY_KINDS else "variable", rel, "variables", item)
        if rel == "registry/evidence.yaml":
            for item in _iter_entries(doc.get("evidence")):
                add(str(item.get("id")), "evidence", rel, "evidence", item)
        if rel == "tiling/data_model.yaml":
            for struct_name, struct in _iter_mapping_entries(doc.get("structs")):
                for field_name, field in _iter_mapping_entries(struct.get("fields") if isinstance(struct, dict) else None):
                    item_id = str(field.get("id") or field.get("stable_id") or f"TDF_{_stable_slug(struct_name)}_{_stable_slug(field_name)}")
                    add(item_id, "tilingdata_field", rel, f"structs.{struct_name}.fields", {**field, "canonical_name": field_name, "struct": struct_name})
            for family, struct_name in _iter_mapping_entries(doc.get("family_to_struct")):
                if isinstance(struct_name, str) and struct_name:
                    add(f"TDF_FAM_{_stable_slug(family)}", "tilingdata_field", rel, "family_to_struct", {"canonical_name": family, "struct": struct_name})
            for overlay_key, overlay in _iter_mapping_entries(doc.get("numeric_overlay")):
                item_id = str(overlay.get("id") or f"TDF_NUM_{_stable_slug(overlay_key)}")
                add(item_id, "tilingdata_field", rel, "numeric_overlay", {**overlay, "canonical_name": overlay_key})
        if rel == "tiling/coverage_model.yaml":
            for item in _iter_entries(doc.get("family_obligations")):
                item_id = str(item.get("id") or f"COV_FAM_{_stable_slug(item.get('name') or item.get('family_id') or '')}")
                add(item_id, "coverage_obligation", rel, "family_obligations", item)
            for key, item in _iter_mapping_entries(doc.get("key_field_obligations")):
                payload = item if isinstance(item, dict) else {"name": key}
                item_id = str(payload.get("id") or f"COV_KEY_{_stable_slug(key)}")
                add(item_id, "coverage_obligation", rel, "key_field_obligations", payload)
            for item in _iter_entries(doc.get("key_relation_obligations")):
                add(str(item.get("id") or f"COV_REL_{_stable_slug(item.get('name') or '')}"), "coverage_obligation", rel, "key_relation_obligations", item)
            for item in _iter_entries(doc.get("tilingdata_obligations")):
                add(str(item.get("id") or f"COV_TDF_{_stable_slug(item.get('name') or '')}"), "coverage_obligation", rel, "tilingdata_obligations", item)
        if rel == "tiling/key_space.yaml":
            for item in _iter_entries(doc.get("fields")):
                item_id = str(item.get("id") or item.get("stable_id") or f"KEY_{str(item.get('canonical_name') or item.get('name') or '').upper()}")
                add(item_id, "key", rel, "fields", item)
        if rel == "tiling/exhaustive_key_space.yaml":
            for item in _iter_entries(doc.get("template_blocks")):
                item_id = str(item.get("id") or f"KTPL_TILING_KEY_BLOCK_{_stable_slug(item.get('name') or item.get('dtype_section') or '')}")
                add(item_id, "template_binding", rel, "template_blocks", item)
        if rel == "tiling/families.yaml":
            for item in _iter_entries(doc.get("families")):
                item_id = str(item.get("id") or item.get("family_id") or "")
                if item_id.startswith("TF"):
                    item_id = "FAM_" + item_id
                add(item_id, "family", rel, "families", item)
        if rel == "flow/compute_graph.yaml":
            for item in _iter_entries(doc.get("compute_steps")):
                add(str(item.get("id")), "compute_step", rel, "compute_steps", item)
        if rel == "flow/golden_model.yaml":
            for item in _iter_entries(doc.get("golden_steps")):
                if item.get("id"):
                    add(str(item.get("id")), "golden_step", rel, "golden_steps", item)
        if rel == "kernel/compile_model.yaml":
            for item in _iter_entries(doc.get("template_bindings")):
                add(str(item.get("id")), "template_binding", rel, "template_bindings", item)
            for item in _iter_entries(doc.get("compile_variables")):
                kind = str(item.get("kind") or "compile_variable")
                add(str(item.get("id")), kind if kind in ENTITY_KINDS else "compile_variable", rel, "compile_variables", item)
            for item in _iter_entries(doc.get("compile_decisions")):
                add(str(item.get("id") or f"KDEC_{_stable_slug(item.get('name') or '')}"), "compile_decision", rel, "compile_decisions", item)
        if rel == "kernel/variables.yaml":
            for item in _iter_entries(doc.get("runtime_variables")):
                kind = str(item.get("kind") or "kernel_runtime_variable")
                add(str(item.get("id")), kind if kind in ENTITY_KINDS else "kernel_runtime_variable", rel, "runtime_variables", item)
            for item in _iter_entries(doc.get("tilingdata_reads")):
                add(str(item.get("id") or f"TDF_READ_{_stable_slug(item.get('field') or item.get('name') or '')}"), "tilingdata_read", rel, "tilingdata_reads", item)
            for item in _iter_entries(doc.get("path_decision_points")):
                add(str(item.get("id") or f"KDEC_{_stable_slug(item.get('name') or '')}"), "kernel_decision_point", rel, "path_decision_points", item)
        if rel == "kernel/pipeline.yaml":
            for item in _iter_entries(doc.get("stages")):
                add(str(item.get("id") or f"PIPE_{_stable_slug(item.get('name') or '')}"), "pipeline_stage", rel, "stages", item)
            for pipeline_name, pipeline in _iter_mapping_entries(doc.get("pipelines")):
                for item in _iter_entries(pipeline.get("stages") if isinstance(pipeline, dict) else None):
                    add(str(item.get("id") or f"PIPE_{_stable_slug(pipeline_name)}_{_stable_slug(item.get('name') or '')}"), "pipeline_stage", rel, f"pipelines.{pipeline_name}.stages", item)
        if rel == "flow/numerical_model.yaml":
            for item in _iter_entries(doc.get("dtype_policy")):
                add(str(item.get("id") or f"NUM_DTYPE_{_stable_slug(item.get('name') or '')}"), "numerical_policy", rel, "dtype_policy", item)
            tolerance = _as_dict(doc.get("tolerance_policy"))
            for key in ("default",):
                if tolerance.get(key):
                    add(f"NUM_TOL_{_stable_slug(key)}", "numerical_policy", rel, "tolerance_policy", {"canonical_name": key, **(_as_dict(tolerance.get(key)))})
            for key, value in tolerance.items():
                if key == "default":
                    continue
                add(f"NUM_TOL_{_stable_slug(key)}", "numerical_policy", rel, f"tolerance_policy.{key}", value if isinstance(value, dict) else {"value": value})
            randomness = _as_dict(doc.get("randomness_policy"))
            for key, value in randomness.items():
                add(f"NUM_RND_{_stable_slug(key)}", "numerical_policy", rel, f"randomness_policy.{key}", value if isinstance(value, dict) else {"value": value})
        if rel == "kernel/paths.yaml":
            for item in _iter_entries(doc.get("kernel_paths")):
                add(str(item.get("id") or item.get("stable_key")), "kernel_path", rel, "kernel_paths", item)
        if rel == "kernel/branches.yaml":
            for item in _iter_entries(doc.get("branches")):
                add(str(item.get("id")), "kernel_branch", rel, "branches", item)
        if rel == "kernel/resources.yaml":
            for section in ("buffers", "sync_events", "workspaces", "resources"):
                for item in _iter_entries(doc.get(section)):
                    raw_id = str(item.get("id") or "")
                    kind = "sync" if section == "sync_events" or raw_id.startswith("SYNC_") else "buffer" if raw_id.startswith("BUF_") else "resource"
                    add(str(item.get("id")), kind, rel, section, item)
        for section in ("relations", "links", "edges", "impacts"):
            for item in _iter_entries(doc.get(section)):
                item_id = str(item.get("id") or "")
                if item_id:
                    add(item_id, "relation", rel, section, item)
        if rel.startswith("contracts/"):
            for item in _iter_entries(doc.get("views")):
                add(str(item.get("id")), "view", rel, "views", item)
            if rel == "contracts/testcase.yaml":
                for section in ("coverage_obligations",):
                    obligations = _as_dict(doc.get(section))
                    for bucket, items in obligations.items():
                        for item in _iter_entries(items):
                            item_id = str(item.get("id") or f"COV_{_stable_slug(bucket)}_{_stable_slug(item.get('name') or '')}")
                            add(item_id, "coverage_obligation", rel, f"{section}.{bucket}", item)

    return dict(sorted(index.items()))


def _iter_mapping_entries(value: Any) -> list[tuple[str, dict[str, Any]]]:
    if isinstance(value, dict):
        out: list[tuple[str, dict[str, Any]]] = []
        for key, item in value.items():
            if isinstance(item, dict):
                out.append((str(key), item))
            else:
                out.append((str(key), {"value": item}))
        return out
    return []


def validate_entity_references(
    docs: dict[str, Any],
    index: dict[str, dict[str, Any]],
    result: CompileResult,
) -> None:
    aliases_by_scope: dict[tuple[str, str], str] = {}
    alias_targets: dict[tuple[str, str], str] = {}
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
            alias_key = (scope, str(alias))
            prev_alias = alias_targets.get(alias_key)
            if result and prev_alias and prev_alias != item_id:
                result.add("ALIAS_CONFLICT", "error", f"alias {alias} maps to both {prev_alias} and {item_id} in scope {scope}", meta.get("artifact", ""), str(alias))
            if (scope, str(alias)) in aliases_by_scope and aliases_by_scope[(scope, str(alias))] != item_id:
                result.add("ALIAS_CANONICAL_NAME_CONFLICT", "error", f"alias {alias} conflicts with canonical name", meta.get("artifact", ""), str(alias))
            alias_targets[alias_key] = item_id

    alias_doc = _as_dict(docs.get("registry/aliases.yaml"))
    seen_alias_entries: dict[tuple[str, str], str] = {}
    for item in _iter_entries(alias_doc.get("aliases")):
        alias = str(item.get("alias") or item.get("name") or "").strip()
        scope = str(item.get("scope") or "").strip()
        target = str(item.get("target_id") or item.get("canonical_id") or "").strip()
        if not alias:
            result.add("BAD_ALIAS_ENTRY", "error", "alias entry missing alias", "registry/aliases.yaml")
            continue
        if not target or target not in index:
            result.add("DANGLING_ALIAS", "error", f"alias targets unknown id {target}", "registry/aliases.yaml", target)
            continue
        key = (scope, alias)
        prev = seen_alias_entries.get(key)
        if prev and prev != target:
            result.add("ALIAS_SCOPE_CONFLICT", "error", f"alias {alias} in scope {scope} maps to both {prev} and {target}", "registry/aliases.yaml", alias)
        seen_alias_entries[key] = target
        canonical_conflict = aliases_by_scope.get(key)
        if canonical_conflict and canonical_conflict != target:
            result.add("ALIAS_CANONICAL_NAME_CONFLICT", "error", f"alias {alias} conflicts with canonical name {canonical_conflict}", "registry/aliases.yaml", alias)
        existing = alias_targets.get(key)
        if existing and existing != target:
            result.add("ALIAS_CONFLICT", "error", f"alias {alias} maps to both {existing} and {target} in scope {scope}", "registry/aliases.yaml", alias)
        alias_targets[key] = target
        aliases = index[target].setdefault("aliases", [])
        if alias not in aliases:
            aliases.append(alias)

    for meta in index.values():
        meta["aliases"] = sorted(str(alias) for alias in meta.get("aliases") or [])


def build_entity_index(docs: dict[str, Any], result: CompileResult | None = None) -> dict[str, dict[str, Any]]:
    index = collect_entity_definitions(docs, result)
    if result:
        validate_entity_references(docs, index, result)
    return dict(sorted(index.items()))


def migrate_stable_ids(docs: dict[str, Any], migrations: list[dict[str, Any]], result: CompileResult | None = None) -> dict[str, Any]:
    """Apply structured stable-id migrations to canonical documents.

    This intentionally updates only structured id/ref fields. It does not
    rewrite prose, source excerpts, formulas, or arbitrary scalar text.
    """
    migrated = copy.deepcopy(docs)
    mapping: dict[str, str] = {}
    kinds: dict[str, str] = {}
    index = collect_entity_definitions(migrated, result)
    for item in migrations:
        old_id = str(item.get("old_id") or "").strip()
        new_id = str(item.get("new_id") or "").strip()
        kind = str(item.get("kind") or "").strip()
        if not old_id or not new_id:
            if result:
                result.add("BAD_ID_MIGRATION", "error", "migration requires old_id and new_id", "id_migration")
            continue
        if old_id not in index and not _structured_id_exists(migrated, old_id):
            if result:
                result.add("BAD_ID_MIGRATION", "error", f"old id not found: {old_id}", "id_migration", old_id)
            continue
        expected = _canonicalize_id_for_kind(old_id, kind)
        if new_id != expected and not STABLE_ID_RE.match(new_id):
            if result:
                result.add("BAD_ID_MIGRATION", "error", f"new id {new_id} is invalid for kind {kind}", "id_migration", old_id)
            continue
        mapping[old_id] = new_id
        kinds[old_id] = kind

    if not mapping:
        return migrated
    _rewrite_structured_refs(migrated, mapping)
    for rel, data in migrated.items():
        _attach_legacy_ids(data, mapping)
    rebuilt = build_entity_index(migrated, result)
    for old_id in mapping:
        if old_id in rebuilt:
            if result:
                result.add("ID_MIGRATION_INCOMPLETE", "error", f"old id still defines entity: {old_id}", "id_migration", old_id)
    return migrated


def _structured_id_exists(value: Any, item_id: str) -> bool:
    if isinstance(value, dict):
        if value.get("id") == item_id or value.get("stable_id") == item_id:
            return True
        return any(_structured_id_exists(child, item_id) for child in value.values())
    if isinstance(value, list):
        return any(_structured_id_exists(item, item_id) for item in value)
    return False


def _rewrite_structured_refs(value: Any, mapping: dict[str, str], key: str = "") -> None:
    if isinstance(value, dict):
        for child_key, child in list(value.items()):
            if child_key in {"id", "stable_id"} and isinstance(child, str) and child in mapping:
                value[child_key] = mapping[child]
            elif _is_ref_key(child_key):
                value[child_key] = _rewrite_ref_value(child, mapping)
            else:
                _rewrite_structured_refs(child, mapping, child_key)
    elif isinstance(value, list):
        for item in value:
            _rewrite_structured_refs(item, mapping, key)


def _rewrite_ref_value(value: Any, mapping: dict[str, str]) -> Any:
    if isinstance(value, str):
        return mapping.get(value, value)
    if isinstance(value, list):
        return [_rewrite_ref_value(item, mapping) for item in value]
    if isinstance(value, dict):
        rewritten: dict[Any, Any] = {}
        for key, child in value.items():
            new_key = mapping.get(key, key) if isinstance(key, str) else key
            rewritten[new_key] = _rewrite_ref_value(child, mapping)
        return rewritten
    return value


def _is_ref_key(key: str) -> bool:
    return key.endswith(("_id", "_ids", "_ref", "_refs")) or key in {
        "family_id",
        "family_ids",
        "source_family",
        "target_family",
        "kernel_path_refs",
        "source_ids",
        "target_ids",
        "depends_on",
        "evidence_refs",
    }


def _attach_legacy_ids(value: Any, mapping: dict[str, str]) -> None:
    if isinstance(value, dict):
        current_id = value.get("id") or value.get("stable_id")
        if isinstance(current_id, str):
            legacy = [old for old, new in mapping.items() if new == current_id]
            if legacy:
                existing = [str(item) for item in _as_list(value.get("legacy_ids"))]
                value["legacy_ids"] = sorted(set(existing + legacy))
        for child in value.values():
            _attach_legacy_ids(child, mapping)
    elif isinstance(value, list):
        for item in value:
            _attach_legacy_ids(item, mapping)


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
    rel = path.as_posix()
    text = read_text(path)
    data, errors = validate_yaml_document(text, rel)
    if result:
        for error in errors:
            result.add(error.code, "error", error.message, rel)
    return data if isinstance(data, dict) else {}


def _load_proposals(
    uo_root: Path,
    result: CompileResult,
    *,
    run_id: str | None = None,
    proposal_paths: list[Path] | None = None,
) -> list[tuple[Path, dict[str, Any]]]:
    if proposal_paths is None:
        if not run_id:
            result.add("RUN_ID_REQUIRED", "error", "promote requires --run-id when --proposal is not provided", "archive/proposals")
            return []
        proposal_paths = sorted((uo_root / "archive" / "proposals" / run_id).glob("*.yaml"))
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
        result.add("NO_PROPOSALS", "warning", "no proposal files found", f"archive/proposals/{run_id or ''}".rstrip("/"))
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
    if prop_phase:
        try:
            normalized_prop_phase = _normalize_owner_phase(prop_phase)
        except ValueError:
            normalized_prop_phase = prop_phase
        if normalized_prop_phase != phase:
            result.add("PROPOSAL_PHASE_MISMATCH", "error", f"proposal phase {prop_phase} cannot promote in {phase}", path.as_posix())
            ok = False
    if not _as_list(proposal.get("canonical_updates")):
        result.add("PROPOSAL_NO_UPDATES", "error", "proposal has no canonical_updates", path.as_posix())
        ok = False
    return ok


def _computed_proposal_hash(proposal: dict[str, Any]) -> str:
    payload = {k: v for k, v in proposal.items() if k not in PROPOSAL_HASH_RUNTIME_FIELDS}
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _proposal_hash(proposal: dict[str, Any]) -> str:
    return _computed_proposal_hash(proposal)


def _validate_proposal_hash(path: Path, proposal: dict[str, Any], computed_hash: str, result: CompileResult) -> bool:
    explicit = str(proposal.get("proposal_hash") or "").strip()
    if not explicit:
        return True
    if explicit == computed_hash:
        return True
    result.add(
        "PROPOSAL_HASH_MISMATCH",
        "error",
        f"proposal_hash mismatch for {proposal.get('proposal_id')}: declared {explicit}, computed {computed_hash}",
        path.as_posix(),
        str(proposal.get("proposal_id") or ""),
    )
    return False


def _validate_update_owner(producer_agent: str, update: dict[str, Any], proposal_path: Path, result: CompileResult) -> bool:
    target = str(update.get("target") or "").replace("\\", "/")
    owner = artifact_owner(target)
    if producer_agent in ORCHESTRATOR_AGENTS and not target.startswith("archive/"):
        result.add(
            "CANONICAL_DIRECT_WRITE",
            "error",
            f"{producer_agent} must not write canonical artifact {target}; route retry to {owner}",
            proposal_path.as_posix(),
            target,
        )
        return False
    if owner.startswith("uo-") and producer_agent and producer_agent != owner:
        result.add(
            "ARTIFACT_OWNER_MISMATCH",
            "error",
            f"{target} is owned by {owner}, not {producer_agent}",
            proposal_path.as_posix(),
            target,
        )
        return False
    return True


def _proposal_consumption_state(uo_root: Path, proposal_id: str, proposal_hash: str, result: CompileResult) -> str:
    if not proposal_id:
        return "new"
    sources: list[tuple[str, dict[str, Any]]] = []
    for receipt in sorted((uo_root / "archive" / "promoted").glob("*/promotion_receipt.yaml")):
        data = _read_yaml(receipt, result)
        if isinstance(data, dict):
            sources.append((receipt.as_posix(), data))
    # Canonical may already be committed while receipt is missing; treat pending tx as consumed.
    for state_path in sorted((uo_root / "archive" / "runs" / "transactions").glob("*/state.yaml")):
        data = _read_yaml(state_path, result)
        if not isinstance(data, dict):
            continue
        status = str(data.get("transaction_status") or "")
        if status in {"canonical_committed", "metadata_pending", "commit_complete"}:
            sources.append((state_path.as_posix(), data))
    for source, data in sources:
        hashes = _as_dict(data.get("proposal_hashes"))
        if proposal_id not in hashes:
            continue
        previous_hash = str(hashes.get(proposal_id) or "")
        if previous_hash == proposal_hash:
            result.add("ALREADY_PROMOTED", "warning", f"proposal {proposal_id} already promoted", source, proposal_id)
            return "already_promoted"
        result.add(
            "PROPOSAL_ID_REUSED_WITH_DIFFERENT_CONTENT",
            "error",
            f"proposal_id {proposal_id} was already promoted with different content",
            source,
            proposal_id,
        )
        return "conflict"
    return "new"


def _write_rejected_proposals(
    uo_root: Path,
    run_id: str | None,
    proposals: list[tuple[Path, dict[str, Any]]],
    result: CompileResult,
) -> None:
    if not proposals:
        return
    target_dir = uo_root / "archive" / "rejected" / (run_id or "unknown_run")
    issues = [issue.to_dict() for issue in result.issues]
    for path, proposal in proposals:
        out = target_dir / f"{path.stem}.rejected.yaml"
        write_text(
            out,
            _to_yaml(
                {
                    "version": 1,
                    "rejected_at": _now(),
                    "source_path": path.as_posix(),
                    "proposal_id": proposal.get("proposal_id"),
                    "proposal_hash": _proposal_hash(proposal),
                    "failure_reason": "; ".join(issue["code"] for issue in issues if issue.get("severity") == "error") or "promotion failed",
                    "issues": issues,
                }
            ),
        )


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
    if not _validate_update_evidence_refs(target, entries, proposal_path, result):
        return False
    if not _validate_canonical_update_ids(target, section, entries, proposal_path, result):
        return False

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


def _validate_update_evidence_refs(target: str, entries: list[Any], proposal_path: Path, result: CompileResult) -> bool:
    if target.startswith(("archive/", "cbm/")):
        return True
    ok = True
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        for ref in _as_list(entry.get("evidence_refs")):
            ref_s = str(ref)
            if not re.fullmatch(r"(?:EV|SRC)_[A-Z0-9_]+", ref_s):
                result.add(
                    "BAD_EVIDENCE_REF_FORMAT",
                    "error",
                    f"evidence ref must be a canonical EV_/SRC_ id: {ref_s!r}",
                    proposal_path.as_posix(),
                    ref_s,
                )
                ok = False
    return ok


def _validate_canonical_update_ids(
    target: str,
    section: str,
    entries: list[Any],
    proposal_path: Path,
    result: CompileResult,
) -> bool:
    if target.startswith(("archive/", "cbm/")):
        return True
    ok = True
    for entry in entries:
        for entry_id in _iter_entry_ids(entry):
            kind = _inferred_kind_for_target(target, section)
            if _is_intermediate_id(entry_id):
                result.add(
                    "INTERMEDIATE_ID_IN_CANONICAL",
                    "error",
                    (
                        f"intermediate id {entry_id} cannot be promoted into {target}:{section}; "
                        f"inferred entity kind={kind}, suggested prefix={_suggested_prefix(kind)}"
                    ),
                    proposal_path.as_posix(),
                    entry_id,
                )
                ok = False
                continue
            canonical_id = _canonicalize_id_for_kind(entry_id, kind)
            if canonical_id != entry_id:
                result.add(
                    "BAD_STABLE_ID",
                    "error",
                    f"canonical update id {entry_id} must be {canonical_id}",
                    proposal_path.as_posix(),
                    entry_id,
                )
                ok = False
            elif not (STABLE_ID_RE.match(entry_id) or LEGACY_ID_RE.match(entry_id)):
                result.add("BAD_STABLE_ID", "error", f"bad canonical update id {entry_id}", proposal_path.as_posix(), entry_id)
                ok = False
    return ok


def _iter_entry_ids(value: Any) -> list[str]:
    ids: list[str] = []
    if isinstance(value, dict):
        for key in ("id", "stable_id", "target_id", "source_id"):
            raw = value.get(key)
            if isinstance(raw, str) and raw:
                ids.append(raw)
        for key in ("source_ids", "target_ids", "family_ids", "kernel_path_refs", "evidence_refs"):
            for raw in _as_list(value.get(key)):
                if isinstance(raw, str) and raw:
                    ids.append(raw)
    return ids


def _is_intermediate_id(value: str) -> bool:
    return bool(re.fullmatch(r"(?:FRO_[A-Za-z0-9_]+|FR\d+|P\d+|PR\d+|TI\d+|IC\d+)", value))


def _inferred_kind_for_target(target: str, section: str) -> str:
    if target == "registry/evidence.yaml" or section == "evidence":
        return "evidence"
    if "families" in target or section == "families":
        return "family"
    if target == "registry/variables.yaml" or section in {"variables", "runtime_variables"}:
        return "variable"
    if section in {"relations", "links", "edges", "impacts"}:
        return "relation"
    if "constraints" in target:
        return "constraint"
    if "coverage" in target or section == "coverage_obligations":
        return "coverage_obligation"
    if "paths" in target:
        return "kernel_path"
    return "entity"


def _suggested_prefix(kind: str) -> str:
    return {
        "evidence": "EV_ or SRC_",
        "family": "FAM_",
        "variable": "VAR_",
        "relation": "REL_",
        "constraint": "CON_",
        "coverage_obligation": "COV_",
        "kernel_path": "KPATH_",
    }.get(kind, "canonical namespace prefix")


def _canonicalize_id_for_kind(value: str, kind: str) -> str:
    if kind == "family":
        if re.fullmatch(r"TF\d+", value):
            return f"FAM_{value}"
        if value.startswith("TF_"):
            return "FAM_" + _stable_slug(value[3:])
    if kind == "evidence" and value.startswith(("EV_", "SRC_")):
        prefix, suffix = value.split("_", 1)
        return f"{prefix}_{_stable_slug(suffix)}"
    return value


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
        if target == "registry/evidence.yaml" and section == "evidence":
            entry = _normalize_evidence_entry(entry)
        else:
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


def _normalize_evidence_entry(entry: dict[str, Any]) -> dict[str, Any]:
    out = dict(entry)
    if not out.get("status") and out.get("file") and out.get("lines") and out.get("symbol") and out.get("kind"):
        out["status"] = "confirmed"
    return out


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


def _normalize_candidate(
    docs: dict[str, Any],
    *,
    touched_artifacts: set[str] | None = None,
    migration_mode: bool = False,
    result: CompileResult | None = None,
    op_name: str = "",
) -> None:
    normalize_structural_compatibility(docs)
    flow_artifacts = normalize_flow_execution_model(
        docs,
        touched_artifacts=touched_artifacts if touched_artifacts is not None else {"flow/compute_graph.yaml", "kernel/paths.yaml"},
        migration_mode=migration_mode or touched_artifacts is None,
        result=result,
        op_name=op_name or _proposal_op_name(docs),
    )
    if result is not None:
        result.normalization = {
            "structural_artifacts": sorted(docs),
            "flow_artifacts": sorted(flow_artifacts),
            "migration_mode": bool(migration_mode or touched_artifacts is None),
        }


def normalize_structural_compatibility(docs: dict[str, Any]) -> None:
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


def normalize_flow_execution_model(
    docs: dict[str, Any],
    *,
    touched_artifacts: set[str],
    migration_mode: bool = False,
    result: CompileResult | None = None,
    op_name: str = "",
) -> set[str]:
    flow_artifacts: set[str] = set()
    function_index = _collect_function_execution_units(docs)
    if migration_mode or "flow/compute_graph.yaml" in touched_artifacts:
        doc = _as_dict(docs.get("flow/compute_graph.yaml"))
        if doc:
            docs["flow/compute_graph.yaml"] = _normalize_compute_graph_doc(doc, function_index, result, op_name=op_name)
            flow_artifacts.add("flow/compute_graph.yaml")
    if migration_mode or "kernel/paths.yaml" in touched_artifacts:
        doc = _as_dict(docs.get("kernel/paths.yaml"))
        if doc:
            docs["kernel/paths.yaml"] = _normalize_kernel_paths_doc(doc, function_index, result, op_name=op_name)
            flow_artifacts.add("kernel/paths.yaml")
    return flow_artifacts


def _normalize_compute_graph_doc(doc: dict[str, Any], function_index: dict[str, Any], result: CompileResult | None, *, op_name: str = "") -> dict[str, Any]:
    out = dict(doc)
    raw_steps = _canonical_step_entries(out, "flow/compute_graph.yaml", result)
    id_map: dict[str, str] = {}
    steps = [
        _normalize_computation_step(item, idx, function_index, id_map=id_map, op_name=op_name, id_prefix="CL", artifact="flow/compute_graph.yaml")
        for idx, item in enumerate(raw_steps, start=1)
    ]
    _rewrite_depends_on_aliases(steps, id_map)
    steps = _link_computation_steps(steps, out, result, artifact="flow/compute_graph.yaml")
    out["compute_steps"] = steps
    out.pop("computation_steps", None)
    _add_step_indexes(out, steps)
    return out


def _normalize_kernel_paths_doc(doc: dict[str, Any], function_index: dict[str, Any], result: CompileResult | None, *, op_name: str = "") -> dict[str, Any]:
    out = dict(doc)
    paths = []
    for path in _iter_entries(out.get("kernel_paths")):
        item = dict(path)
        raw_steps = item.get("computation_steps") or item.get("compute_steps") or item.get("data_flow_steps") or []
        if raw_steps:
            id_map: dict[str, str] = {}
            path_id = str(item.get("id") or item.get("stable_key") or "")
            steps = [
                _normalize_computation_step(step, idx, function_index, path_id=path_id, id_map=id_map, op_name=op_name, id_prefix="KSTEP", artifact="kernel/paths.yaml")
                for idx, step in enumerate(_iter_entries(raw_steps), start=1)
            ]
            _rewrite_depends_on_aliases(steps, id_map)
            steps = _link_computation_steps(steps, item, result, artifact="kernel/paths.yaml", path_id=path_id)
            item["computation_steps"] = steps
            _add_step_indexes(item, steps)
        paths.append(item)
    out["kernel_paths"] = sorted(paths, key=lambda item: str(item.get("id") or item.get("stable_key") or ""))
    return out


def _add_step_indexes(container: dict[str, Any], steps: list[dict[str, Any]]) -> None:
    buckets = {
        "vector_steps": "VECTOR",
        "cube_steps": "CUBE",
        "data_move_steps": "DATA_MOVE",
        "sync_steps": "SYNC",
        "scalar_control_steps": "SCALAR_CONTROL",
        "unknown_steps": "UNKNOWN",
    }
    for key, unit in buckets.items():
        container[key] = [str(step.get("id") or step.get("step_id")) for step in steps if step.get("execution_unit") == unit]


def _link_computation_steps(
    steps: list[dict[str, Any]],
    container: dict[str, Any],
    result: CompileResult | None,
    *,
    artifact: str,
    path_id: str = "",
) -> list[dict[str, Any]]:
    step_ids = [str(step.get("id") or step.get("step_id")) for step in steps]
    if len(step_ids) != len(set(step_ids)) and result is not None:
        for step_id in sorted({item for item in step_ids if step_ids.count(item) > 1}):
            result.add("FLOW_STEP_ID_COLLISION", "error", f"duplicate flow step id {step_id}", artifact, step_id)
    linked: list[dict[str, Any]] = []
    ordered = str(container.get("sequence_semantics") or container.get("dependency_policy") or "") in {"linear", "ordered_sequence"}
    for idx, step in enumerate(steps):
        item = dict(step)
        step_id = str(item.get("id") or item.get("step_id"))
        item["id"] = step_id
        item["step_id"] = step_id
        has_explicit_depends_on = "depends_on" in item
        bad_dependency_format = False
        if not has_explicit_depends_on:
            item["depends_on"] = [str(linked[-1].get("id"))] if ordered and linked else []
        else:
            item["depends_on"], bad_dependency_format = _normalize_dependency_list(item.get("depends_on"))
        item["dependency_status"], item["is_root"] = _dependency_status(
            has_explicit_depends_on=has_explicit_depends_on,
            depends_on=item["depends_on"],
            ordered=ordered,
            is_first=idx == 0,
        )
        if bad_dependency_format:
            item["dependency_status"] = "invalid"
            item["is_root"] = False
            if result is not None:
                result.add(
                    "FLOW_BAD_DEPENDENCY_FORMAT",
                    "error",
                    f"{step_id} has invalid depends_on format",
                    artifact,
                    path_id or step_id,
                )
        linked.append(item)
    step_by_id = {str(step["id"]): step for step in linked}
    downstream_by_id = {step_id: [] for step_id in step_by_id}
    for step in linked:
        missing_dependencies = []
        for dep in step.get("depends_on") or []:
            if dep not in step_by_id:
                missing_dependencies.append(dep)
                if result is not None:
                    result.add("FLOW_UNKNOWN_DEPENDENCY", "error", f"{step['id']} depends on unknown step {dep}", artifact, path_id or str(step["id"]))
                continue
            downstream_by_id[dep].append(str(step["id"]))
        if missing_dependencies:
            step["dependency_status"] = "unresolved"
            step["missing_dependencies"] = sorted(set(missing_dependencies))
            step["is_root"] = False
        else:
            step.pop("missing_dependencies", None)
    for step in linked:
        step["downstream_steps"] = sorted(downstream_by_id.get(str(step["id"]), []))
        transitions = []
        for dep in step.get("depends_on") or []:
            upstream = step_by_id.get(dep)
            if not upstream:
                continue
            transitions.append(_execution_transition(upstream, step))
        step["execution_transitions"] = transitions
        if len(transitions) == 1:
            step["execution_transition"] = transitions[0]
        else:
            step.pop("execution_transition", None)
    cycle_nodes = _detect_step_cycles(linked, result, artifact=artifact, path_id=path_id)
    for step in linked:
        if str(step.get("id")) in cycle_nodes:
            step["dependency_status"] = "invalid"
            step["is_root"] = False
    return linked


def _normalize_dependency_list(value: Any) -> tuple[list[str], bool]:
    if isinstance(value, list):
        return [str(dep) for dep in value if str(dep)], False
    return [], True


def _dependency_status(
    *,
    has_explicit_depends_on: bool,
    depends_on: list[str],
    ordered: bool,
    is_first: bool,
) -> tuple[str, bool]:
    """Return normalized DAG dependency metadata.

    Phase 3 consumers may directly consume only `root` and `resolved`.
    `unspecified`, `unresolved`, and `invalid` require blocking or human review:
    - root: explicit empty dependency list, or first ordered-sequence step.
    - resolved: all declared predecessors are present.
    - unspecified: no dependency field and no ordered sequence policy.
    - unresolved: declared predecessor cannot be resolved.
    - invalid: cycle or illegal dependency structure.
    """
    if has_explicit_depends_on:
        if not depends_on:
            return "root", True
        return "resolved", False
    if ordered:
        if is_first:
            return "root", True
        return "resolved", False
    return "unspecified", False


def _normalize_computation_step(
    raw: dict[str, Any],
    index: int,
    function_index: dict[str, Any],
    *,
    path_id: str = "",
    id_map: dict[str, str],
    op_name: str,
    id_prefix: str,
    artifact: str,
) -> dict[str, Any]:
    step = dict(raw)
    original_id = str(step.get("step_id") or step.get("id") or "")
    step_id = _canonical_step_id(step, index, op_name=op_name, path_id=path_id, id_prefix=id_prefix)
    if original_id and original_id != step_id:
        id_map[original_id] = step_id
        aliases = sorted(set(_as_list(step.get("aliases")) + _as_list(step.get("legacy_ids")) + [original_id]))
        step["legacy_ids"] = aliases
        step["aliases"] = sorted(set(_as_list(step.get("aliases")) + [original_id]))
    unit, confidence, unit_evidence = _classify_execution_unit(step, function_index)
    operation = str(step.get("operation") or _infer_operation(step, unit))
    name = _normalize_step_name(str(step.get("name") or step.get("label") or ""), unit, operation, step)
    evidence = [str(item) for item in _as_list(step.get("evidence")) if str(item)]
    for item in unit_evidence:
        if item not in evidence:
            evidence.append(item)
    out = {
        **step,
        "id": step_id,
        "step_id": step_id,
        "name": name,
        "execution_unit": unit,
        "operation": operation,
        "inputs": [str(item) for item in _as_list(step.get("inputs"))],
        "outputs": [str(item) for item in _as_list(step.get("outputs"))],
        "source_location": _as_dict(step.get("source_location")),
        "evidence": evidence,
        "confidence": str(step.get("confidence") or confidence),
    }
    if artifact == "flow/compute_graph.yaml":
        for implementation_key in (
            "api",
            "apis",
            "calls",
            "callees",
            "memory_locations",
            "buffer",
            "buffers",
            "pipeline",
            "pipe",
            "queue",
            "queues",
            "local_tensor",
            "global_tensor",
        ):
            out.pop(implementation_key, None)
    else:
        out.setdefault("memory_locations", [str(item) for item in _as_list(step.get("memory_locations"))])
    return out


def _canonical_step_entries(doc: dict[str, Any], artifact: str, result: CompileResult | None) -> list[dict[str, Any]]:
    has_compute = "compute_steps" in doc
    has_computation = "computation_steps" in doc
    if has_compute and has_computation and _canonical_json(doc.get("compute_steps")) != _canonical_json(doc.get("computation_steps")):
        if result is not None:
            result.add("FLOW_STEP_ALIAS_MISMATCH", "error", "compute_steps and computation_steps differ", artifact)
    source = doc.get("compute_steps") if has_compute else doc.get("computation_steps")
    return _iter_entries(source)


def _rewrite_depends_on_aliases(steps: list[dict[str, Any]], id_map: dict[str, str]) -> None:
    for step in steps:
        if "depends_on" in step and isinstance(step.get("depends_on"), list):
            step["depends_on"] = [id_map.get(str(dep), str(dep)) for dep in _as_list(step.get("depends_on"))]


def _execution_transition(upstream: dict[str, Any], step: dict[str, Any]) -> dict[str, Any]:
    from_unit = str(upstream.get("execution_unit") or "UNKNOWN")
    to_unit = str(step.get("execution_unit") or "UNKNOWN")
    return {
        "from_step": str(upstream.get("id")),
        "from_unit": from_unit,
        "to_step": str(step.get("id")),
        "to_unit": to_unit,
        "sync_semantics": _transition_semantics(upstream, step, "SYNC"),
        "data_move_semantics": _transition_semantics(upstream, step, "DATA_MOVE"),
    }


def _transition_semantics(upstream: dict[str, Any], step: dict[str, Any], unit: str) -> dict[str, Any]:
    evidence = []
    if upstream.get("execution_unit") == unit:
        evidence.append(f"upstream step {upstream.get('id')} is {unit}")
    if step.get("execution_unit") == unit:
        evidence.append(f"current step {step.get('id')} is {unit}")
    status = "observed" if evidence else "unknown"
    return {"status": status, "evidence": evidence}


def _detect_step_cycles(steps: list[dict[str, Any]], result: CompileResult | None, *, artifact: str, path_id: str = "") -> set[str]:
    graph = {str(step.get("id")): [str(dep) for dep in _as_list(step.get("depends_on"))] for step in steps}
    visiting: set[str] = set()
    visited: set[str] = set()
    cycle_nodes: set[str] = set()

    def visit(node: str, path: list[str]) -> None:
        if node in visiting:
            cycle = path[path.index(node):] if node in path else path + [node]
            cycle_nodes.update(cycle)
            if result is not None:
                result.add("FLOW_DEPENDENCY_CYCLE", "error", f"cycle in flow dependencies: {', '.join(cycle)}", artifact, path_id or node)
            return
        if node in visited:
            return
        visiting.add(node)
        for dep in graph.get(node, []):
            if dep in graph:
                visit(dep, path + [dep])
        visiting.discard(node)
        visited.add(node)

    for node in sorted(graph):
        visit(node, [node])
    return cycle_nodes


def _canonical_step_id(step: dict[str, Any], index: int, *, op_name: str, path_id: str = "", id_prefix: str) -> str:
    existing = str(step.get("id") or step.get("step_id") or "")
    if id_prefix == "CL" and existing.startswith("CL_"):
        return existing
    if id_prefix == "KSTEP" and existing.startswith("KSTEP_"):
        return existing
    parts = [op_name or "OP"]
    if path_id and id_prefix == "KSTEP":
        parts.append(path_id)
    for key in ("operation", "name", "function"):
        value = str(step.get(key) or "")
        if value:
            parts.append(value)
            break
    outputs = _as_list(step.get("outputs"))
    if outputs:
        parts.append(str(outputs[0]))
    slug = "_".join(_stable_slug(part) for part in parts if str(part))
    return f"{id_prefix}_{slug or f'STEP_{index}'}"


def _normalize_step_name(name: str, unit: str, operation: str, step: dict[str, Any]) -> str:
    prefix = EXECUTION_PREFIX[unit]
    for known in EXECUTION_PREFIX.values():
        if name.startswith(known):
            name = name[len(known):].strip()
            break
    if not name or name.lower() in {"process data", "compute result", "execute kernel", "run calculation", "handle tensor"}:
        objects = _as_list(step.get("outputs")) or _as_list(step.get("inputs"))
        data_object = " and ".join(str(item) for item in objects[:2]) if objects else "kernel data"
        verb = {
            "VECTOR": "Compute",
            "CUBE": "Compute",
            "DATA_MOVE": "Move",
            "SYNC": "Synchronize",
            "SCALAR_CONTROL": "Control",
            "UNKNOWN": "Analyze",
        }[unit]
        name = f"{verb} {operation.replace('_', ' ')} {data_object}".strip()
    return f"{prefix} {name}"


def _classify_execution_unit(step: dict[str, Any], function_index: dict[str, Any]) -> tuple[str, str, list[str]]:
    explicit = str(step.get("execution_unit") or step.get("unit") or "").upper()
    if explicit in EXECUTION_UNITS:
        return explicit, str(step.get("confidence") or "high"), [f"Explicit execution_unit={explicit}"]
    calls = [str(item) for item in _as_list(step.get("calls") or step.get("callees") or step.get("apis"))]
    for call in calls:
        api_unit = _unit_for_exact_api(call)
        if api_unit:
            return api_unit, "high", [f"Matched exact {api_unit} API evidence: {call}"]
        lookup = _lookup_function_unit(call, step, function_index)
        if lookup.get("status") == "matched":
            return str(lookup["unit"]), "medium", [f"Called function {call} is classified as {lookup['unit']}"]
        if lookup.get("status") == "ambiguous":
            return "UNKNOWN", "low", [f"AMBIGUOUS_CALLEE_CLASSIFICATION: {call}"]
    operation_unit = _unit_for_exact_api(str(step.get("operation") or ""))
    if operation_unit:
        return operation_unit, "medium", [f"Matched structured operation evidence: {step.get('operation')}"]
    if _has_matrix_semantics(step):
        return "CUBE", "medium", ["Matched matrix input/output semantics"]
    if _has_vector_semantics(step):
        return "VECTOR", "medium", ["Matched LocalTensor/vector elementwise semantics"]
    fuzzy = _fuzzy_classification_hint(step)
    if fuzzy:
        return "UNKNOWN", "low", [f"classification_hint={fuzzy}; fuzzy text evidence is not sufficient"]
    return "UNKNOWN", "low", ["Insufficient API or data-shape evidence for execution unit"]


def _infer_operation(step: dict[str, Any], unit: str) -> str:
    for call in _as_list(step.get("calls") or step.get("callees") or step.get("apis")):
        normalized = _normalize_api_name(str(call))
        if normalized:
            return EXACT_API_OPERATIONS.get(normalized) or normalized.split("::")[-1].split(".")[-1]
    return EXECUTION_OPERATION_DEFAULT[unit]


def _step_text(step: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("name", "label", "operation", "api", "function", "body", "description", "code"):
        if step.get(key) is not None:
            parts.append(str(step.get(key)))
    parts.extend(str(item) for item in _as_list(step.get("calls") or step.get("callees") or step.get("apis")))
    parts.extend(str(item) for item in _as_list(step.get("evidence")))
    parts.extend(str(item) for item in _as_list(step.get("inputs")))
    parts.extend(str(item) for item in _as_list(step.get("outputs")))
    return "\n".join(parts).lower()


def _first_pattern_hit(text: str, patterns: tuple[str, ...]) -> str:
    compact = text.lower()
    for pattern in patterns:
        normalized = pattern.lower()
        if normalized in compact:
            return pattern
    return ""


def _normalize_api_name(name: str) -> str:
    text = name.strip().replace("AscendC::", "ascendc::").replace("::", "::").replace(" ", "")
    return text.lower()


EXACT_API_UNITS = {
    "ascendc::datacopy": "DATA_MOVE",
    "datacopy": "DATA_MOVE",
    "copyin": "DATA_MOVE",
    "copyout": "DATA_MOVE",
    "pipebarrier": "SYNC",
    "syncall": "SYNC",
    "setflag": "SYNC",
    "waitflag": "SYNC",
    "matmul.iterate": "CUBE",
    "matmul::iterate": "CUBE",
    "matmulimpl": "CUBE",
    "gettensorc": "CUBE",
    "ascendc::mmad": "CUBE",
    "mmad": "CUBE",
    "mmadwithsparse": "CUBE",
    "ascendc::add": "VECTOR",
    "ascendc::sub": "VECTOR",
    "ascendc::mul": "VECTOR",
    "ascendc::div": "VECTOR",
    "ascendc::exp": "VECTOR",
    "ascendc::log": "VECTOR",
    "ascendc::sqrt": "VECTOR",
    "ascendc::abs": "VECTOR",
    "ascendc::cast": "VECTOR",
    "ascendc::reducemax": "VECTOR",
    "ascendc::reducesum": "VECTOR",
}
EXACT_API_OPERATIONS = {
    "ascendc::datacopy": "copy",
    "datacopy": "copy",
    "copyin": "copy",
    "copyout": "copy",
    "pipebarrier": "sync",
    "syncall": "sync",
    "setflag": "sync",
    "waitflag": "sync",
    "matmul.iterate": "matmul",
    "matmul::iterate": "matmul",
    "matmulimpl": "matmul",
    "gettensorc": "matmul",
    "ascendc::mmad": "matmul",
    "mmad": "matmul",
    "mmadwithsparse": "matmul",
}


def _unit_for_exact_api(name: str) -> str:
    return EXACT_API_UNITS.get(_normalize_api_name(name), "")


def _fuzzy_classification_hint(step: dict[str, Any]) -> str:
    text = _step_text(step)
    for unit, patterns in (("DATA_MOVE", DATA_MOVE_PATTERNS), ("SYNC", SYNC_PATTERNS), ("CUBE", CUBE_API_PATTERNS), ("VECTOR", VECTOR_API_PATTERNS), ("SCALAR_CONTROL", SCALAR_PATTERNS)):
        if _first_pattern_hit(text, patterns):
            return unit
    return ""


def _has_matrix_semantics(step: dict[str, Any]) -> bool:
    text = _step_text(step)
    matrix_words = ("matrix", "tile a", "tile b", "l0a", "l0b", "l0c", "tensor a", "tensor b", "tensor c")
    return sum(1 for word in matrix_words if word in text) >= 2


def _has_vector_semantics(step: dict[str, Any]) -> bool:
    text = _step_text(step)
    return ("localtensor" in text or "ub" in text) and any(word in text for word in ("elementwise", "softmax", "normalize", "scale", "mask"))


def _collect_function_execution_units(docs: dict[str, Any]) -> dict[str, Any]:
    functions: dict[str, list[dict[str, Any]]] = {}
    for doc in docs.values():
        data = _as_dict(doc)
        for section in ("functions", "kernel_functions", "function_summaries", "symbols"):
            for item in _iter_entries(data.get(section)):
                name = str(item.get("name") or item.get("canonical_name") or item.get("id") or "")
                if name:
                    keys = {name, _qualified_function_key(item), str(item.get("id") or "")}
                    for key in keys:
                        if key:
                            functions.setdefault(key, []).append(item)
    resolved: dict[str, Any] = {}
    for _ in range(4):
        changed = False
        for name, items in functions.items():
            if name in resolved or len(items) != 1:
                continue
            item = items[0]
            unit, _confidence, _evidence = _classify_execution_unit({**item, "name": ""}, resolved)
            if unit != "UNKNOWN":
                resolved[name] = unit
                changed = True
        if not changed:
            break
    resolved["_functions"] = functions
    return resolved


def _qualified_function_key(item: dict[str, Any]) -> str:
    file_name = str(item.get("file") or item.get("path") or "")
    scope = str(item.get("scope") or item.get("namespace") or item.get("class") or "")
    name = str(item.get("name") or item.get("canonical_name") or item.get("function") or "")
    return "::".join(part for part in (file_name, scope, name) if part)


def _lookup_function_unit(call: str, step: dict[str, Any], function_index: dict[str, Any]) -> dict[str, Any]:
    functions = function_index.get("_functions") or {}
    source = _as_dict(step.get("source_location"))
    file_name = str(step.get("file") or source.get("file") or step.get("path") or "")
    scope = str(step.get("scope") or step.get("namespace") or step.get("class") or source.get("class") or source.get("scope") or "")
    simple = str(call).split("::")[-1].split(".")[-1]
    keys = [
        "::".join(part for part in (file_name, scope, call) if part),
        "::".join(part for part in (file_name, scope, simple) if part),
        str(call),
        simple,
    ]
    for key in keys:
        if key in function_index:
            return {"status": "matched", "unit": function_index[key]}
        matches = functions.get(key)
        if matches and len(matches) > 1:
            return {"status": "ambiguous"}
    return {"status": "missing"}


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
        present_keys = 0
        for key in rules:
            value = data.get(key)
            if key in data:
                present_keys += 1
            if isinstance(value, dict) and value:
                has_real = True
            elif isinstance(value, list) and value:
                has_real = True
            elif value not in (None, "", {}, []):
                has_real = True
        if has_real:
            maturity[rel] = "valid"
        elif rel in ALLOWED_EMPTY_MATURITY_FILES and present_keys == len(rules):
            maturity[rel] = "valid"
        else:
            maturity[rel] = "placeholder"
            if _phase_rank(phase) >= _required_phase_for(rel):
                result.add("PLACEHOLDER_ARTIFACT", "error", f"{rel} has only skeleton content", rel)
    return maturity


def _validate_evidence(docs: dict[str, Any], result: CompileResult) -> None:
    for issue in validate_evidence_closure(docs):
        result.add(issue.code, issue.severity, issue.message, issue.artifact, issue.target)


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
    hardware_patterns = [
        re.compile(pattern)
        for pattern in (
            r"\bLocalTensor\b",
            r"\bGlobalTensor\b",
            r"\bTQue\b",
            r"\bTBuf\b",
            r"\bDataCopy\b",
            r"\bSetFlag\b",
            r"\bWaitFlag\b",
            r"\bPIPE_[A-Z0-9_]+\b",
            r"\bL0[A-C]?\b",
            r"\bL1\b",
            r"\bUB\b",
        )
    ]
    for rel in ("flow/compute_graph.yaml", "flow/dataflow.yaml", "flow/golden_model.yaml"):
        values = _structured_boundary_values(docs.get(rel, {}))
        if any(pattern.search(value) for value in values for pattern in hardware_patterns):
            result.add("FLOW_HARDWARE_DETAIL", "warning", f"{rel} appears to contain kernel hardware/resource detail", rel)
    for rel in ("kernel/paths.yaml", "kernel/pipeline.yaml", "kernel/branches.yaml"):
        data = _as_dict(docs.get(rel))
        for refs, path in _find_keys(data, "implements_compute_steps"):
            for ref in _as_list(refs):
                if ref and ref not in compute_ids:
                    result.add("KERNEL_UNKNOWN_COMPUTE_STEP", "error", f"kernel references unknown compute step {ref}", rel, path)


def _validate_flow_step_graph(docs: dict[str, Any], result: CompileResult) -> None:
    flow = _as_dict(docs.get("flow/compute_graph.yaml"))
    if "compute_steps" in flow and "computation_steps" in flow and _canonical_json(flow.get("compute_steps")) != _canonical_json(flow.get("computation_steps")):
        result.add("FLOW_STEP_ALIAS_MISMATCH", "error", "compute_steps and computation_steps differ", "flow/compute_graph.yaml")
    _validate_step_container(_iter_entries(flow.get("compute_steps") or flow.get("computation_steps")), result, artifact="flow/compute_graph.yaml")
    for path in _iter_entries(_as_dict(docs.get("kernel/paths.yaml")).get("kernel_paths")):
        _validate_step_container(
            _iter_entries(path.get("computation_steps") or path.get("compute_steps") or path.get("data_flow_steps")),
            result,
            artifact="kernel/paths.yaml",
            path_id=str(path.get("id") or path.get("stable_key") or ""),
        )


def _validate_step_container(steps: list[dict[str, Any]], result: CompileResult, *, artifact: str, path_id: str = "") -> None:
    step_ids = [str(step.get("id") or step.get("step_id") or "") for step in steps if step.get("id") or step.get("step_id")]
    step_set = set(step_ids)
    for step_id in sorted({item for item in step_ids if step_ids.count(item) > 1}):
        result.add("FLOW_STEP_ID_COLLISION", "error", f"duplicate flow step id {step_id}", artifact, path_id or step_id)
    for step in steps:
        step_id = str(step.get("id") or step.get("step_id") or "")
        if "depends_on" in step:
            deps, bad_format = _normalize_dependency_list(step.get("depends_on"))
        else:
            deps, bad_format = [], False
        if bad_format:
            result.add("FLOW_BAD_DEPENDENCY_FORMAT", "error", f"{step_id} has invalid depends_on format", artifact, path_id or step_id)
        for dep in deps:
            dep_id = str(dep)
            if dep_id and dep_id not in step_set:
                result.add("FLOW_UNKNOWN_DEPENDENCY", "error", f"{step_id} depends on unknown step {dep_id}", artifact, path_id or step_id)
    _detect_step_cycles([dict(step, id=str(step.get("id") or step.get("step_id") or "")) for step in steps], result, artifact=artifact, path_id=path_id)


def _structured_boundary_values(value: Any) -> list[str]:
    fields = {"api", "operation", "resource", "buffer", "pipeline", "sync", "implementation", "hardware_detail", "description"}
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key) in fields:
                if isinstance(child, str):
                    found.append(child)
                elif isinstance(child, (list, dict)):
                    found.append(_canonical_json(child))
            found.extend(_structured_boundary_values(child))
    elif isinstance(value, list):
        for item in value:
            found.extend(_structured_boundary_values(item))
    return found


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


def _resolve_stale_after_success(
    uo_root: Path,
    *,
    phase: str,
    run_id: str | None,
    changed_artifacts: list[str],
    artifact_hashes: dict[str, str] | None = None,
    validation_status: str = "pass",
    dependency_hash: str | None = None,
) -> list[str]:
    payload = _compute_stale_resolution(
        uo_root,
        phase=phase,
        run_id=run_id,
        changed_artifacts=changed_artifacts,
        artifact_hashes=artifact_hashes or {},
        validation_status=validation_status,
        dependency_hash=dependency_hash,
    )
    if payload is None:
        return []
    write_text(uo_root / "archive" / "runs" / "stale_artifacts.yaml", _to_yaml(payload))
    return sorted(
        str(item.get("path"))
        for item in _as_list(payload.get("stale_artifacts"))
        if isinstance(item, dict) and item.get("resolution_reason")
    )


def _compute_stale_resolution(
    uo_root: Path,
    *,
    phase: str,
    run_id: str | None,
    changed_artifacts: list[str],
    artifact_hashes: dict[str, str],
    validation_status: str,
    dependency_hash: str | None = None,
) -> dict[str, Any] | None:
    stale_path = uo_root / "archive" / "runs" / "stale_artifacts.yaml"
    if not stale_path.exists():
        return None
    data = _read_yaml(stale_path)
    if not isinstance(data, dict):
        return None
    changed = set(changed_artifacts)
    resolved: list[str] = []
    entries: list[dict[str, Any]] = []
    for raw in _as_list(data.get("stale_artifacts")):
        item = dict(raw) if isinstance(raw, dict) else {}
        path = str(item.get("path") or "")
        expected_run = str(item.get("expected_refresh_run_id") or "")
        owner_phase = _normalize_owner_phase(str(item.get("owner_phase") or _owner_phase_for(path)))
        current_hash = artifact_hashes.get(path, "")
        old_hash = str(item.get("old_artifact_hash") or item.get("canonical_hash_before") or "")
        dep_hash = str(item.get("dependency_hash") or "")
        if item.get("stale") is not True:
            entries.append(item)
            continue
        if owner_phase != phase:
            entries.append(item)
            continue
        if expected_run and (not run_id or expected_run != run_id):
            entries.append(item)
            continue
        if validation_status != "pass":
            entries.append(item)
            continue
        if dep_hash and dependency_hash and dep_hash != dependency_hash:
            entries.append(item)
            continue
        hash_changed = bool(path and path in changed and current_hash and old_hash and current_hash != old_hash)
        hash_unchanged = bool(path and current_hash and old_hash and current_hash == old_hash)
        can_resolve = bool(path) and (hash_changed or hash_unchanged or path in changed)
        if not can_resolve:
            entries.append(item)
            continue
        item["stale"] = False
        item["validated_at"] = _now()
        item["validated_by_run_id"] = run_id
        item["validation_status"] = validation_status
        item["resolved_at"] = _now()
        item["resolved_by_run_id"] = run_id
        item["resolution_reason"] = "changed_and_validated" if hash_changed else "unchanged_but_validated"
        resolved.append(path)
        entries.append(item)
    history = _as_list(data.get("resolution_history"))
    if resolved:
        history.append(
            {
                "resolved_at": _now(),
                "run_id": run_id,
                "phase": phase,
                "artifacts": sorted(resolved),
                "validation_status": validation_status,
            }
        )
    data["stale_artifacts"] = entries
    data["resolution_history"] = history
    return data


def _owner_phase_for(path: str) -> str:
    if path.startswith(("operator.yaml", "manifest.yaml", "index.yaml", "registry/")):
        return "phase2"
    if path.startswith("flow/"):
        return "phase2"
    if path.startswith(("tiling/", "cross_layer/input_to_tiling", "cross_layer/variable_lineage")):
        return "phase2"
    if path.startswith("kernel/"):
        return "phase4"
    if path.startswith("cross_layer/"):
        return "phase5"
    if path.startswith(("query/", "contracts/", "test/")):
        return "phase7"
    return "final"


def _normalize_owner_phase(phase: str) -> str:
    phase = phase.replace("_host", "").replace("_flow", "")
    try:
        return _normalize_phase(phase)
    except ValueError:
        return _owner_phase_for(phase)


def _build_graphs(docs: dict[str, Any], op_name: str, result: CompileResult | None = None) -> None:
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
        if eid.startswith(("EV_", "SRC_")):
            continue
        nodes[eid] = {
            "id": eid,
            "kind": meta.get("kind"),
            "label": meta.get("canonical_name") or eid,
            "artifact": meta.get("artifact"),
            "status": meta.get("status") or "proposed",
            "evidence_refs": meta.get("evidence_refs") or [],
        }

    unresolved: list[dict[str, Any]] = []
    for rel, doc in source_docs.items():
        data = _as_dict(doc)
        for section in ("relations", "links", "edges"):
            for item in _iter_entries(data.get(section)):
                item = _normalize_relation_entry(item)
                sources = _as_list(item.get("source_ids"))
                targets = _as_list(item.get("target_ids"))
                if not sources or not targets:
                    unresolved_item = {
                        "id": item.get("id") or "",
                        "type": item.get("type") or "affects",
                        "artifact": rel,
                        "section": section,
                        "status": "unresolved",
                        "reason": "relation_direction_missing",
                        "source_ids": sources,
                        "target_ids": targets,
                        "relation_id": item.get("id") or "",
                        "evidence_refs": _as_list(item.get("evidence_refs")),
                    }
                    unresolved_key = _unresolved_key(unresolved_item)
                    if unresolved_key not in { _unresolved_key(x) for x in unresolved }:
                        unresolved.append(unresolved_item)
                    if result:
                        result.add("RELATION_DIRECTION_MISSING", "error", "relation missing explicit source_ids/target_ids", rel, str(item.get("id") or ""))
                    continue
                for src in sources:
                    for dst in targets:
                        if not src or not dst or src == dst:
                            continue
                        if str(src).startswith(("EV_", "SRC_")) or str(dst).startswith(("EV_", "SRC_")):
                            if result:
                                result.add("GRAPH_EVIDENCE_NODE_SKIPPED", "warning", "evidence/source ids are not behavior graph business nodes", rel, str(item.get("id") or ""))
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
    deduped_unresolved = _dedupe_unresolved(unresolved)
    behavior.update(
        {
            "version": 1,
            "op_name": op_name,
            "purpose": "deterministically built behavior graph",
            "nodes": [nodes[key] for key in sorted(nodes)],
            "edges": [edges[key] for key in sorted(edges)],
            "unresolved": deduped_unresolved,
            "conflicts": _dedupe_conflicts(_as_list(behavior.get("conflicts"))),
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
            "traversal_policy": {"max_depth": 8, "cycle_protection": "path_ancestors", "edge_types": sorted(RELATION_TYPES)},
            "unresolved": [],
            "conflicts": [],
        }
    )
    docs["cross_layer/impact_graph.yaml"] = impact


def _derive_impact_edges(edges: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    adjacency: dict[str, list[dict[str, Any]]] = {}
    for edge in edges.values():
        adjacency.setdefault(str(edge.get("source_id")), []).append(edge)
    for node in adjacency:
        adjacency[node] = sorted(adjacency[node], key=lambda e: (str(e.get("target_id")), str(e.get("id"))))
    impacts: dict[str, dict[str, Any]] = {}
    for start in sorted(adjacency):
        queue: list[tuple[str, int, list[str], list[str]]] = [(start, 0, [], [start])]
        best_depth: dict[str, int] = {start: 0}
        while queue:
            node, depth, path, path_nodes = queue.pop(0)
            if depth >= 8:
                continue
            for edge in adjacency.get(node, []):
                dst = str(edge.get("target_id"))
                edge_path = path + [str(edge.get("id"))]
                if dst in path_nodes:
                    impact_id = f"REL_IMPACT_{_stable_slug(start)}_TO_{_stable_slug(dst)}"
                    impacts[f"{impact_id}:cycle:{':'.join(edge_path)}"] = {
                        "id": impact_id + "_CYCLE",
                        "type": "affects",
                        "source_id": start,
                        "target_id": dst,
                        "impact_kind": "cycle",
                        "depth": depth + 1,
                        "confidence": "possible",
                        "path": edge_path,
                        "alternative_paths": [],
                        "status": "unresolved",
                        "evidence_refs": [],
                    }
                    continue
                impact_id = f"REL_IMPACT_{_stable_slug(start)}_TO_{_stable_slug(dst)}"
                relation = "direct" if depth == 0 else "transitive"
                impact_key = f"{impact_id}:{relation}"
                candidate = {
                    "id": impact_id,
                    "type": "affects",
                    "source_id": start,
                    "target_id": dst,
                    "impact_kind": relation,
                    "depth": depth + 1,
                    "confidence": "confirmed" if edge.get("status") == "confirmed" else "possible",
                    "path": edge_path,
                    "alternative_paths": [],
                    "status": edge.get("status") or "proposed",
                    "evidence_refs": edge.get("evidence_refs") or [],
                }
                existing = impacts.get(impact_key)
                if existing is None or (candidate["depth"], candidate["path"]) < (existing.get("depth", 999), existing.get("path", [])):
                    if existing is not None:
                        candidate["alternative_paths"] = sorted(_as_list(existing.get("alternative_paths")) + [existing.get("path")])
                    impacts[impact_key] = candidate
                elif existing is not None and edge_path != existing.get("path"):
                    existing["alternative_paths"] = sorted(_as_list(existing.get("alternative_paths")) + [edge_path])
                if best_depth.get(dst, 999) <= depth + 1:
                    continue
                best_depth[dst] = depth + 1
                queue.append((dst, depth + 1, edge_path, path_nodes + [dst]))
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
        "consumability": result.consumability,
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


def _write_promotion_receipt(
    uo_root: Path,
    result: CompileResult,
    run_id: str | None,
    proposal_ids: list[str],
    proposal_hashes: dict[str, str],
    before_hashes: dict[str, str],
    after_hashes: dict[str, str],
    transaction: TransactionResult | None,
) -> None:
    if result.promotion_report.get("status") != "promoted":
        return
    changed = sorted(path for path, digest in after_hashes.items() if before_hashes.get(path) != digest)
    receipt = {
        "version": 1,
        "run_id": run_id,
        "phase": result.phase,
        "proposal_ids": proposal_ids,
        "proposal_hashes": proposal_hashes,
        "promoted_at": _now(),
        "changed_artifacts": changed,
        "before_hashes": {path: before_hashes.get(path) for path in changed},
        "after_hashes": {path: after_hashes.get(path) for path in changed},
        "transaction_id": transaction.transaction_id if transaction else None,
        "status": "promoted",
    }
    write_text(uo_root / "archive" / "promoted" / (run_id or "manual") / "promotion_receipt.yaml", _to_yaml(receipt))


def _promotion_report(
    op_name: str,
    phase: str,
    status: str,
    applied: list[dict[str, Any]],
    result: CompileResult,
    before_hashes: dict[str, str],
    after_hashes: dict[str, str],
    *,
    transaction: TransactionResult | None = None,
    run_id: str | None = None,
    proposal_ids: list[str] | None = None,
    proposal_hashes: dict[str, str] | None = None,
    skipped_proposals: list[dict[str, Any]] | None = None,
    normalization: dict[str, Any] | None = None,
) -> dict[str, Any]:
    planned = transaction.planned_artifacts if transaction else sorted(path for path, digest in after_hashes.items() if before_hashes.get(path) != digest)
    return {
        "version": 1,
        "op_name": op_name,
        "phase": phase,
        "run_id": run_id,
        "status": status,
        "promoted_at": _now(),
        "applied_updates": applied,
        "proposal_ids": proposal_ids or [],
        "proposal_hashes": proposal_hashes or {},
        "skipped_proposals": skipped_proposals or [],
        "normalization": normalization or getattr(result, "normalization", {}),
        "changed_artifacts": sorted(path for path, digest in after_hashes.items() if before_hashes.get(path) != digest),
        "transaction_id": transaction.transaction_id if transaction else None,
        "planned_artifacts": planned,
        "committed_artifacts": transaction.committed_artifacts if transaction else planned,
        "rolled_back_artifacts": transaction.rolled_back_artifacts if transaction else [],
        "metadata_artifacts": transaction.metadata_artifacts if transaction else [],
        "transaction_status": transaction.transaction_status if transaction else ("commit_complete" if status == "promoted" else "not_started"),
        "recovery_status": transaction.recovery_status if transaction else "",
        "failure_reason": transaction.failure_reason if transaction else "",
        "issues": [issue.to_dict() for issue in result.issues],
    }


def _unresolved_key(item: dict[str, Any]) -> str:
    return _canonical_json(
        {
            "artifact": item.get("artifact"),
            "section": item.get("section"),
            "relation_id": item.get("relation_id") or item.get("id"),
            "reason": item.get("reason"),
            "source_ids": sorted(_as_list(item.get("source_ids"))),
            "target_ids": sorted(_as_list(item.get("target_ids"))),
        }
    )


def _dedupe_unresolved(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for item in sorted(items, key=lambda x: _unresolved_key(x)):
        key = _unresolved_key(item)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _dedupe_conflicts(items: list[Any]) -> list[Any]:
    seen: set[str] = set()
    out: list[Any] = []
    for item in items:
        key = _canonical_json(item)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _artifact_not_applicable(data: dict[str, Any]) -> bool:
    return str(data.get("status") or "") == "not_applicable" and bool(data.get("reason")) and bool(_as_list(data.get("evidence_refs")))


def _validate_consumability(docs: dict[str, Any], result: CompileResult) -> dict[str, dict[str, Any]]:
    consumability: dict[str, dict[str, Any]] = {}
    for rel in TEST_CONSUMABLE_FILES:
        data = _as_dict(docs.get(rel))
        blockers: list[str] = []
        schema_valid = bool(data)
        semantically_complete = schema_valid and result.maturity.get(rel) in {"valid", "not_applicable"}
        test_consumable = semantically_complete
        if not schema_valid:
            blockers.append("missing_or_empty")
        if rel == "flow/golden_model.yaml" and schema_valid and not _artifact_not_applicable(data):
            if not _as_list(data.get("golden_inputs")):
                blockers.append("golden_inputs_empty")
            if not _as_list(data.get("golden_outputs")):
                blockers.append("golden_outputs_empty")
            contract = data.get("golden_generation_contract")
            if contract in (None, "", {}, []):
                blockers.append("golden_generation_contract_empty")
        if rel == "contracts/testcase.yaml" and schema_valid:
            if int(data.get("version") or 0) < 2:
                blockers.append("testcase_contract_version_lt_2")
            for key in ("source", "interface", "coverage_obligations", "golden_contract"):
                if key not in data:
                    blockers.append(f"missing_{key}")
        if blockers:
            test_consumable = False
            for blocker in blockers:
                result.add("NOT_TEST_CONSUMABLE", "error", f"{rel}: {blocker}", rel, blocker)
        consumability[rel] = {
            "schema_valid": schema_valid,
            "semantically_complete": semantically_complete,
            "test_consumable": test_consumable and not blockers,
            "blockers": blockers,
        }
    return consumability


def _build_promotion_payloads(
    uo_root: Path,
    candidate: dict[str, Any],
    previous: dict[str, Any],
    result: CompileResult,
    *,
    run_id: str | None,
    proposal_ids: list[str],
    proposal_hashes: dict[str, str],
    before_hashes: dict[str, str],
    after_hashes: dict[str, str],
    stale_payload: dict[str, Any] | None,
) -> dict[str, str]:
    payloads: dict[str, str] = {}
    for rel, data in candidate.items():
        if rel.startswith(("archive/", "cbm/")):
            continue
        if _canonical_json(previous.get(rel)) != _canonical_json(data):
            payloads[rel] = _to_yaml(data)
    summary = {
        "entity_count": result.entity_count,
        "alias_count": result.alias_count,
        "evidence_count": result.evidence_count,
        "relation_count": result.relation_count,
        "unresolved_count": result.unresolved_count,
        "conflict_count": result.conflict_count,
    }
    compile_report = {
        "version": 1,
        "op_name": result.op_name,
        "phase": result.phase,
        "compiled_at": _now(),
        "status": result.status,
        "summary": summary,
        "maturity": result.maturity,
        "consumability": result.consumability,
        "issues": [issue.to_dict() for issue in result.issues],
    }
    payloads["archive/runs/kb_compile_report.yaml"] = _to_yaml(compile_report)
    payloads["archive/runs/canonical_hashes.yaml"] = _to_yaml(
        {"version": 1, "op_name": result.op_name, "generated_at": _now(), "artifact_hashes": result.artifact_hashes}
    )
    payloads["archive/runs/entity_index.yaml"] = _to_yaml(
        {"version": 1, "op_name": result.op_name, "generated_at": _now(), "entities": result.entity_index}
    )
    payloads["archive/runs/kb_promotion_report.yaml"] = _to_yaml(result.promotion_report)
    changed = sorted(path for path, digest in after_hashes.items() if before_hashes.get(path) != digest)
    receipt = {
        "version": 1,
        "run_id": run_id,
        "phase": result.phase,
        "proposal_ids": proposal_ids,
        "proposal_hashes": proposal_hashes,
        "promoted_at": _now(),
        "changed_artifacts": changed,
        "before_hashes": {path: before_hashes.get(path) for path in changed},
        "after_hashes": {path: after_hashes.get(path) for path in changed},
        "transaction_id": result.promotion_report.get("transaction_id"),
        "status": "promoted",
    }
    payloads[f"archive/promoted/{run_id or 'manual'}/promotion_receipt.yaml"] = _to_yaml(receipt)
    if stale_payload is not None:
        payloads["archive/runs/stale_artifacts.yaml"] = _to_yaml(stale_payload)
    return payloads


def _transaction_dir(uo_root: Path, transaction_id: str) -> Path:
    return uo_root / "archive" / "runs" / "transactions" / transaction_id


def _write_transaction_state(uo_root: Path, tx: TransactionResult, *, op_name: str, phase: str, run_id: str | None, proposal_hashes: dict[str, str]) -> None:
    tx_dir = _transaction_dir(uo_root, tx.transaction_id)
    tx_dir.mkdir(parents=True, exist_ok=True)
    write_text(
        tx_dir / "state.yaml",
        _to_yaml(
            {
                "version": 1,
                "transaction_id": tx.transaction_id,
                "op_name": op_name,
                "phase": phase,
                "run_id": run_id,
                "proposal_hashes": proposal_hashes,
                "planned_artifacts": tx.planned_artifacts,
                "committed_artifacts": tx.committed_artifacts,
                "rolled_back_artifacts": tx.rolled_back_artifacts,
                "metadata_artifacts": tx.metadata_artifacts,
                "transaction_status": tx.transaction_status,
                "recovery_status": tx.recovery_status,
                "failure_reason": tx.failure_reason,
                "updated_at": _now(),
            }
        ),
    )


def _execute_promotion_transaction(
    uo_root: Path,
    op_name: str,
    payloads: dict[str, str],
    *,
    phase: str,
    run_id: str | None,
    proposal_hashes: dict[str, str],
) -> TransactionResult:
    canonical = [rel for rel in sorted(payloads) if not rel.startswith("archive/")]
    metadata = [rel for rel in sorted(payloads) if rel.startswith("archive/")]
    tx = TransactionResult(
        transaction_id=f"TX_{datetime.now(tz=timezone.utc).strftime('%Y%m%d%H%M%S%f')}",
        planned_artifacts=sorted(payloads),
        transaction_status="prepared",
    )
    _write_transaction_state(uo_root, tx, op_name=op_name, phase=phase, run_id=run_id, proposal_hashes=proposal_hashes)
    canonical_payload = {rel: payloads[rel] for rel in canonical}
    validation_errors: list[str] = []
    for rel, text in canonical_payload.items():
        data, errors = validate_yaml_document(text, rel, phase=phase, run_id=run_id or "")
        if rel == "kernel/resources.yaml" and not errors:
            errors.extend(resource_semantic_errors(data, rel, phase=phase, run_id=run_id or ""))
        validation_errors.extend(f"{rel}: {error.code}: {error.message}" for error in errors)
    if validation_errors:
        tx.transaction_status = "rolled_back"
        tx.failure_reason = "; ".join(validation_errors)
        _write_transaction_state(uo_root, tx, op_name=op_name, phase=phase, run_id=run_id, proposal_hashes=proposal_hashes)
        return tx
    canonical_previous = {rel: read_text(uo_root / rel) for rel in canonical if (uo_root / rel).exists()}
    canonical_docs = {rel: _read_yaml_from_text(canonical_payload[rel], rel) for rel in canonical}
    previous_docs = {rel: _read_yaml_from_text(canonical_previous.get(rel, ""), rel) for rel in canonical if rel in canonical_previous}
    canonical_tx = _transactional_write_texts(uo_root, canonical_payload)
    tx.committed_artifacts = canonical_tx.committed_artifacts
    tx.rolled_back_artifacts = canonical_tx.rolled_back_artifacts
    if canonical_tx.transaction_status != "committed":
        tx.transaction_status = "rolled_back"
        tx.failure_reason = canonical_tx.failure_reason
        _write_transaction_state(uo_root, tx, op_name=op_name, phase=phase, run_id=run_id, proposal_hashes=proposal_hashes)
        return tx
    tx.transaction_status = "canonical_committed"
    _write_transaction_state(uo_root, tx, op_name=op_name, phase=phase, run_id=run_id, proposal_hashes=proposal_hashes)
    metadata_payload = {rel: payloads[rel] for rel in metadata}
    metadata_tx = _transactional_write_texts(uo_root, metadata_payload)
    tx.metadata_artifacts = metadata_tx.committed_artifacts
    if metadata_tx.transaction_status != "committed":
        tx.transaction_status = "metadata_pending"
        tx.failure_reason = metadata_tx.failure_reason
        tx.recovery_status = "metadata_pending"
        _write_transaction_state(uo_root, tx, op_name=op_name, phase=phase, run_id=run_id, proposal_hashes=proposal_hashes)
        return tx
    tx.transaction_status = "commit_complete"
    write_text(_transaction_dir(uo_root, tx.transaction_id) / "commit.yaml", _to_yaml({"transaction_id": tx.transaction_id, "committed_at": _now()}))
    _write_transaction_state(uo_root, tx, op_name=op_name, phase=phase, run_id=run_id, proposal_hashes=proposal_hashes)
    return tx


def _transactional_write_texts(uo_root: Path, payloads: dict[str, str]) -> TransactionResult:
    changed = sorted(payloads)
    tx = TransactionResult(
        transaction_id=f"TX_{datetime.now(tz=timezone.utc).strftime('%Y%m%d%H%M%S%f')}",
        planned_artifacts=changed,
        transaction_status="prepared" if changed else "committed",
    )
    if not changed:
        return tx
    temp_paths: dict[str, Path] = {}
    backup_paths: dict[str, Path] = {}
    existed: dict[str, bool] = {}
    try:
        for rel in changed:
            path = uo_root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
            temp_path = Path(tmp_name)
            with os.fdopen(fd, "w", encoding="utf-8") as tmp:
                tmp.write(payloads[rel])
                tmp.flush()
                os.fsync(tmp.fileno())
            temp_paths[rel] = temp_path
        for rel in changed:
            path = uo_root / rel
            existed[rel] = path.exists()
            if not existed[rel]:
                continue
            fd, backup_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".bak", dir=str(path.parent))
            os.close(fd)
            backup = Path(backup_name)
            shutil.copy2(path, backup)
            backup_paths[rel] = backup
        for rel in changed:
            path = uo_root / rel
            os.replace(temp_paths[rel], path)
            tx.committed_artifacts.append(rel)
        tx.transaction_status = "committed"
        for backup in backup_paths.values():
            backup.unlink(missing_ok=True)
        return tx
    except Exception as exc:  # noqa: BLE001
        tx.transaction_status = "rolled_back"
        tx.failure_reason = str(exc)
        for rel in reversed(tx.committed_artifacts):
            path = uo_root / rel
            backup = backup_paths.get(rel)
            try:
                if existed.get(rel) and backup and backup.exists():
                    os.replace(backup, path)
                elif path.exists():
                    path.unlink()
                tx.rolled_back_artifacts.append(rel)
            except Exception as rollback_exc:  # noqa: BLE001
                tx.failure_reason += f"; rollback failed for {rel}: {rollback_exc}"
        for rel, tmp in temp_paths.items():
            if rel not in tx.committed_artifacts:
                tmp.unlink(missing_ok=True)
        for backup in backup_paths.values():
            backup.unlink(missing_ok=True)
        return tx


def _read_yaml_from_text(text: str, rel: str) -> Any:
    if not text.strip() or yaml is None:
        return {}
    try:
        return yaml.safe_load(text) or {}
    except Exception:  # noqa: BLE001
        return {}


def _recover_pending_transactions(uo_root: Path, op_name: str) -> None:
    tx_root = uo_root / "archive" / "runs" / "transactions"
    if not tx_root.exists():
        return
    for state_path in sorted(tx_root.glob("*/state.yaml")):
        state = _read_yaml(state_path)
        if not isinstance(state, dict):
            continue
        if str(state.get("op_name") or "") not in {"", op_name}:
            continue
        if (state_path.parent / "commit.yaml").exists():
            continue
        status = str(state.get("transaction_status") or "")
        if status not in {"canonical_committed", "metadata_pending"}:
            continue
        tx = TransactionResult(
            transaction_id=str(state.get("transaction_id") or state_path.parent.name),
            planned_artifacts=_as_list(state.get("planned_artifacts")),
            committed_artifacts=[str(x) for x in _as_list(state.get("committed_artifacts"))],
            rolled_back_artifacts=[str(x) for x in _as_list(state.get("rolled_back_artifacts"))],
            metadata_artifacts=[str(x) for x in _as_list(state.get("metadata_artifacts"))],
            transaction_status=status,
            recovery_status="recovering",
        )
        pending = [rel for rel in tx.planned_artifacts if rel.startswith("archive/") and rel not in tx.metadata_artifacts]
        if not pending:
            tx.transaction_status = "commit_complete"
            tx.recovery_status = "already_complete"
            write_text(state_path.parent / "commit.yaml", _to_yaml({"transaction_id": tx.transaction_id, "committed_at": _now(), "recovered": True}))
            _write_transaction_state(uo_root, tx, op_name=op_name, phase=str(state.get("phase") or "final"), run_id=str(state.get("run_id") or "") or None, proposal_hashes=_as_dict(state.get("proposal_hashes")))
            continue
        # Metadata recovery requires caller-provided payloads on next promotion; mark for manual recovery.
        tx.recovery_status = "metadata_pending"
        _write_transaction_state(uo_root, tx, op_name=op_name, phase=str(state.get("phase") or "final"), run_id=str(state.get("run_id") or "") or None, proposal_hashes=_as_dict(state.get("proposal_hashes")))


def _atomic_write_docs(uo_root: Path, candidate: dict[str, Any], *, only_changed_against: dict[str, Any]) -> None:
    result = _transactional_write_docs(uo_root, candidate, only_changed_against)
    if result.transaction_status != "committed":
        raise RuntimeError(result.failure_reason)


def _transactional_write_docs(
    uo_root: Path,
    candidate: dict[str, Any],
    previous: dict[str, Any],
) -> TransactionResult:
    changed = [
        rel
        for rel, data in sorted(candidate.items())
        if not rel.startswith(("archive/", "cbm/")) and _canonical_json(previous.get(rel)) != _canonical_json(data)
    ]
    tx = TransactionResult(
        transaction_id=f"TX_{datetime.now(tz=timezone.utc).strftime('%Y%m%d%H%M%S%f')}",
        planned_artifacts=changed,
        transaction_status="prepared" if changed else "committed",
    )
    if not changed:
        return tx

    temp_paths: dict[str, Path] = {}
    backup_paths: dict[str, Path] = {}
    existed: dict[str, bool] = {}
    try:
        for rel in changed:
            path = uo_root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            text, errors = serialize_yaml_checked(rel, candidate[rel])
            if errors:
                raise ValueError("; ".join(f"{error.code}: {error.message}" for error in errors))
            fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
            temp_path = Path(tmp_name)
            with os.fdopen(fd, "w", encoding="utf-8") as tmp:
                tmp.write(text)
                tmp.flush()
                os.fsync(tmp.fileno())
            temp_paths[rel] = temp_path

        for rel in changed:
            path = uo_root / rel
            existed[rel] = path.exists()
            if not existed[rel]:
                continue
            fd, backup_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".bak", dir=str(path.parent))
            os.close(fd)
            backup = Path(backup_name)
            shutil.copy2(path, backup)
            backup_paths[rel] = backup

        for rel in changed:
            path = uo_root / rel
            os.replace(temp_paths[rel], path)
            tx.committed_artifacts.append(rel)

        tx.transaction_status = "committed"
        for backup in backup_paths.values():
            backup.unlink(missing_ok=True)
        return tx
    except Exception as exc:  # noqa: BLE001
        tx.transaction_status = "rolled_back"
        tx.failure_reason = str(exc)
        for rel in reversed(tx.committed_artifacts):
            path = uo_root / rel
            backup = backup_paths.get(rel)
            try:
                if existed.get(rel) and backup and backup.exists():
                    os.replace(backup, path)
                elif path.exists():
                    path.unlink()
                tx.rolled_back_artifacts.append(rel)
            except Exception as rollback_exc:  # noqa: BLE001
                tx.failure_reason += f"; rollback failed for {rel}: {rollback_exc}"
        for rel, tmp in temp_paths.items():
            if rel not in tx.committed_artifacts:
                tmp.unlink(missing_ok=True)
        for backup in backup_paths.values():
            backup.unlink(missing_ok=True)
        return tx


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
        for token in re.findall(
            r"\b(?:SYM|VAR|REL|EV|SRC|KEY|FAM|COMP|GOLD|KPATH|KBR|KTPL|CL|CON|VIEW|BUF|SYNC|RES|TDF|KVAR|KDEC|PIPE|COV|NUM)_[A-Z0-9_]+\b",
            value,
        ):
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
    for prefix, kind in PREFIX_TO_KIND.items():
        if item_id.startswith(prefix):
            return kind
    if item_id.startswith("TF"):
        return "family"
    if re.match(r"K\d+", item_id):
        return "kernel_path"
    if item_id.startswith("C"):
        return "compute_step"
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
        return yaml_text(data)
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
    promote.add_argument("--run-id", help="Only consume proposals under archive/proposals/<run_id>/")
    promote.add_argument("--proposal", action="append", type=Path, help="Specific proposal path; otherwise --run-id is required")

    validate = sub.add_parser("validate", help="Validate canonical KB without modifying canonical artifacts")
    validate.add_argument("repo_root", type=Path)
    validate.add_argument("--op-name", required=True)
    validate.add_argument("--phase", default="final")
    validate.add_argument("--check-only", action="store_true", help="Do not write reports")

    resolve = sub.add_parser("resolve-stale", help="Resolve stale artifacts after a successful phase refresh")
    resolve.add_argument("repo_root", type=Path)
    resolve.add_argument("--op-name", required=True)
    resolve.add_argument("--phase", required=True)
    resolve.add_argument("--run-id", required=True)
    resolve.add_argument("--artifact", action="append", default=[], help="Refreshed canonical artifact path")

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
        result = promote_kb(uo_root, op_name, phase=args.phase, run_id=args.run_id, proposal_paths=args.proposal)
    elif args.command == "resolve-stale":
        repo_root = args.repo_root.resolve()
        op_name = safe_op_name(args.op_name, repo_root)
        uo_root = operator_root(repo_root, op_name)
        phase = _normalize_phase(args.phase)
        resolved = _resolve_stale_after_success(uo_root, phase=phase, run_id=args.run_id, changed_artifacts=args.artifact)
        result = CompileResult(op_name=op_name, phase=phase)
        result.promotion_report = {"status": "resolved", "resolved_artifacts": resolved}
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
