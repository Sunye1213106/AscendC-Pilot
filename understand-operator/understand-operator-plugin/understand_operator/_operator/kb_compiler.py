from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
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
    r"^(SYM|VAR|REL|EV|SRC|KEY|FAM|KPATH|KBR|KTPL|CL|CON|VIEW)_[A-Z0-9_]+$"
)

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

KERNEL_TWO_STEP_FILES = (
    "kernel/compile_model.yaml",
    "kernel/variables.yaml",
    "kernel/branches.yaml",
)


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
    status: str = "pass"
    issues: list[Issue] = field(default_factory=list)
    artifact_hashes: dict[str, str] = field(default_factory=dict)
    entity_count: int = 0
    alias_count: int = 0
    evidence_count: int = 0
    relation_count: int = 0
    unresolved_count: int = 0
    conflict_count: int = 0

    def add(self, code: str, severity: str, message: str, artifact: str = "", target: str = "") -> None:
        self.issues.append(Issue(code, severity, message, artifact, target))
        if severity == "error":
            self.status = "fail"
        elif severity == "warning" and self.status == "pass":
            self.status = "warn"


def compile_kb(uo_root: Path, op_name: str, *, write_outputs: bool = True) -> CompileResult:
    result = CompileResult(op_name=op_name)
    docs = _load_yaml_files(uo_root, result)

    _hash_artifacts(uo_root, result)
    ids, aliases, evidence_ids = _collect_registry(docs, result)
    _validate_registry(ids, aliases, docs, result)
    _validate_evidence(docs, evidence_ids, result)
    _validate_typed_relations(docs, ids, evidence_ids, result)
    _validate_kernel_two_step(docs, ids, evidence_ids, result)
    _validate_cross_layer(docs, ids, evidence_ids, result)
    _validate_contracts(docs, ids, result)
    _derive_counts(docs, result)

    if write_outputs:
        _write_compile_outputs(uo_root, result)
    return result


def _load_yaml_files(uo_root: Path, result: CompileResult) -> dict[str, Any]:
    docs: dict[str, Any] = {}
    rels = (
        REGISTRY_FILES
        + CROSS_LAYER_FILES
        + CONTRACT_FILES
        + QUERY_FILES
        + KERNEL_TWO_STEP_FILES
        + (
            "manifest.yaml",
            "index.yaml",
            "operator.yaml",
            "tiling/variables.yaml",
            "tiling/constraints.yaml",
            "tiling/key_space.yaml",
            "tiling/families.yaml",
            "tiling/data_model.yaml",
            "kernel/paths.yaml",
            "kernel/pipeline.yaml",
            "kernel/resources.yaml",
            "evidence/fact_index.yaml",
            "evidence/source_index.yaml",
            "evidence/artifact_dependencies.yaml",
            "evidence/issues.yaml",
            "quality.yaml",
            "test/contract.yaml",
        )
    )
    if yaml is None:
        result.add("YAML_UNAVAILABLE", "error", "PyYAML is required for deterministic KB compilation")
        return docs
    for rel in rels:
        path = uo_root / rel
        if not path.exists():
            if rel in REGISTRY_FILES + CROSS_LAYER_FILES + CONTRACT_FILES + QUERY_FILES + KERNEL_TWO_STEP_FILES:
                result.add("MISSING_CANONICAL_V2", "error", f"missing KB v2 artifact: {rel}", rel)
            continue
        if rel.endswith((".yaml", ".yml")):
            try:
                data = yaml.safe_load(read_text(path)) or {}
            except Exception as exc:  # noqa: BLE001
                result.add("YAML_PARSE", "error", f"YAML parse failed: {exc}", rel)
                data = {}
            docs[rel] = data
    return docs


def _hash_artifacts(uo_root: Path, result: CompileResult) -> None:
    for path in sorted(uo_root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(uo_root).as_posix()
        if rel.startswith(("archive/runs/kb_compile_report", "archive/runs/canonical_hashes")):
            continue
        if rel.startswith(("cbm/", "archive/cbm/")):
            continue
        if path.suffix.lower() not in {".yaml", ".yml", ".md", ".json"}:
            continue
        result.artifact_hashes[rel] = hashlib.sha256(path.read_bytes()).hexdigest()


def _collect_registry(
    docs: dict[str, Any],
    result: CompileResult,
) -> tuple[dict[str, dict[str, Any]], dict[str, str], set[str]]:
    ids: dict[str, dict[str, Any]] = {}
    aliases: dict[str, str] = {}
    evidence_ids: set[str] = set()

    for rel in ("registry/symbols.yaml", "registry/variables.yaml"):
        data = _as_dict(docs.get(rel))
        for section in ("symbols", "variables", "entities"):
            for item in _iter_entries(data.get(section)):
                item_id = str(item.get("id") or "").strip()
                if not item_id:
                    result.add("MISSING_ID", "error", "registry entry missing id", rel)
                    continue
                if item_id in ids:
                    result.add("DUPLICATE_ID", "error", f"duplicate stable id {item_id}", rel, item_id)
                    continue
                ids[item_id] = item
                for alias in _as_list(item.get("aliases")):
                    alias_key = str(alias).strip()
                    if not alias_key:
                        continue
                    prev = aliases.get(alias_key)
                    if prev and prev != item_id:
                        result.add(
                            "ALIAS_CONFLICT",
                            "error",
                            f"alias {alias_key} maps to both {prev} and {item_id}",
                            rel,
                            alias_key,
                        )
                    aliases[alias_key] = item_id

    alias_doc = _as_dict(docs.get("registry/aliases.yaml"))
    for item in _iter_entries(alias_doc.get("aliases")):
        alias_key = str(item.get("alias") or item.get("name") or "").strip()
        target = str(item.get("target_id") or item.get("canonical_id") or "").strip()
        if not alias_key or not target:
            result.add("BAD_ALIAS", "warning", "alias entry missing alias or target_id", "registry/aliases.yaml")
            continue
        prev = aliases.get(alias_key)
        if prev and prev != target:
            result.add("ALIAS_CONFLICT", "error", f"alias {alias_key} maps to both {prev} and {target}", "registry/aliases.yaml")
        aliases[alias_key] = target
        if target and target not in ids:
            result.add("DANGLING_ALIAS", "error", f"alias {alias_key} targets unknown id {target}", "registry/aliases.yaml")

    ev_doc = _as_dict(docs.get("registry/evidence.yaml"))
    for item in _iter_entries(ev_doc.get("evidence")):
        ev_id = str(item.get("id") or "").strip()
        if ev_id:
            evidence_ids.add(ev_id)
            ids.setdefault(ev_id, item)

    fact_index = _as_dict(docs.get("evidence/fact_index.yaml"))
    refs = _as_dict(fact_index.get("evidence_refs"))
    evidence_ids.update(str(k) for k in refs.keys())

    result.entity_count = len(ids)
    result.alias_count = len(aliases)
    result.evidence_count = len(evidence_ids)
    return ids, aliases, evidence_ids


def _validate_registry(ids: dict[str, dict[str, Any]], aliases: dict[str, str], docs: dict[str, Any], result: CompileResult) -> None:
    for item_id, item in ids.items():
        if not STABLE_ID_RE.match(item_id):
            if not re.match(r"^(TF\d+|K\d+|C\d+|D\d+|P\d+)$", item_id):
                result.add("BAD_STABLE_ID", "error", f"stable id does not match convention: {item_id}", target=item_id)
        kind = str(item.get("kind") or "").strip()
        canonical_name = str(item.get("canonical_name") or item.get("name") or "").strip()
        if item_id.startswith(("VAR_", "SYM_")) and not (kind and canonical_name):
            result.add("MISSING_ENTITY_FIELDS", "error", f"{item_id} requires kind and canonical_name/name", target=item_id)
    for alias, target in aliases.items():
        if target not in ids:
            result.add("DANGLING_ALIAS", "error", f"alias {alias} targets unknown id {target}", "registry/aliases.yaml")

    variables_doc = _as_dict(docs.get("registry/variables.yaml"))
    seen_by_scope_name: dict[tuple[str, str], str] = {}
    for item in _iter_entries(variables_doc.get("variables")):
        name = str(item.get("canonical_name") or "").strip()
        scope = str(item.get("scope") or "").strip()
        item_id = str(item.get("id") or "").strip()
        key = (scope, name)
        if name and scope and key in seen_by_scope_name and seen_by_scope_name[key] != item_id:
            result.add("DUPLICATE_VARIABLE_NAME", "warning", f"{scope}.{name} has multiple ids", "registry/variables.yaml", name)
        if name and scope:
            seen_by_scope_name[key] = item_id


def _validate_evidence(docs: dict[str, Any], evidence_ids: set[str], result: CompileResult) -> None:
    ev_doc = _as_dict(docs.get("registry/evidence.yaml"))
    for item in _iter_entries(ev_doc.get("evidence")):
        ev_id = str(item.get("id") or "").strip()
        file_name = str(item.get("file") or item.get("path") or "").strip()
        lines = item.get("lines")
        if not ev_id:
            result.add("MISSING_EVIDENCE_ID", "error", "evidence entry missing id", "registry/evidence.yaml")
        if not file_name:
            result.add("MISSING_EVIDENCE_FILE", "error", f"evidence {ev_id} missing file", "registry/evidence.yaml", ev_id)
        if not _valid_lines(lines):
            result.add("BAD_EVIDENCE_LINES", "error", f"evidence {ev_id} has invalid lines", "registry/evidence.yaml", ev_id)

    for rel, doc in docs.items():
        for refs, path in _find_keys(doc, "evidence_refs"):
            ref_values = refs.keys() if isinstance(refs, dict) else _as_list(refs)
            for ref in ref_values:
                ref_s = str(ref).strip()
                if ref_s and ref_s not in evidence_ids:
                    result.add("DANGLING_EVIDENCE_REF", "error", f"unknown evidence ref {ref_s}", rel, path)


def _validate_typed_relations(
    docs: dict[str, Any],
    ids: dict[str, dict[str, Any]],
    evidence_ids: set[str],
    result: CompileResult,
) -> None:
    allowed = {
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
    relation_sources = [
        ("tiling/constraints.yaml", ("relations",)),
        ("cross_layer/input_to_tiling.yaml", ("relations", "links")),
        ("cross_layer/tiling_to_kernel.yaml", ("relations", "links")),
        ("cross_layer/variable_lineage.yaml", ("relations", "lineage")),
        ("cross_layer/behavior_graph.yaml", ("edges",)),
        ("cross_layer/impact_graph.yaml", ("edges", "impacts")),
    ]
    for rel, sections in relation_sources:
        data = _as_dict(docs.get(rel))
        for section in sections:
            for item in _iter_entries(data.get(section)):
                rel_id = str(item.get("id") or "").strip()
                rel_type = str(item.get("type") or item.get("relation") or "").strip()
                if rel_id and rel_id.startswith("REL_") and not STABLE_ID_RE.match(rel_id):
                    result.add("BAD_RELATION_ID", "error", f"bad relation id {rel_id}", rel, rel_id)
                if rel_type and rel_type not in allowed:
                    result.add("BAD_RELATION_TYPE", "error", f"unsupported relation type {rel_type}", rel, rel_id)
                expr = item.get("expression")
                if expr is not None and not isinstance(expr, dict):
                    result.add("BAD_EXPRESSION_AST", "error", "relation expression must be a mapping AST", rel, rel_id)
                refs = _as_list(item.get("evidence_refs"))
                if rel_type in {"derives", "controls", "determines", "implies", "binds", "dispatches_to", "maps_to", "affects"} and not refs:
                    result.add("MISSING_RELATION_EVIDENCE", "warning", "key relation missing evidence_refs", rel, rel_id)
                for ref in refs:
                    if str(ref) not in evidence_ids:
                        result.add("DANGLING_EVIDENCE_REF", "error", f"unknown evidence ref {ref}", rel, rel_id)
                for var_ref in _collect_id_like_values(item):
                    if var_ref == rel_id:
                        continue
                    if var_ref.startswith(("VAR_", "SYM_", "KEY_", "KPATH_", "KTPL_", "REL_")) and var_ref not in ids:
                        result.add("DANGLING_REFERENCE", "error", f"unknown stable id {var_ref}", rel, rel_id)


def _validate_kernel_two_step(
    docs: dict[str, Any],
    ids: dict[str, dict[str, Any]],
    evidence_ids: set[str],
    result: CompileResult,
) -> None:
    compile_model = _as_dict(docs.get("kernel/compile_model.yaml"))
    variables = _as_dict(docs.get("kernel/variables.yaml"))
    branches = _as_dict(docs.get("kernel/branches.yaml"))
    paths = _as_dict(docs.get("kernel/paths.yaml"))

    template_ids = {
        str(item.get("id")).strip()
        for item in _iter_entries(compile_model.get("template_bindings"))
        if item.get("id")
    }
    if not compile_model:
        result.add("KERNEL_STEP1_MISSING", "error", "kernel/compile_model.yaml missing or empty", "kernel/compile_model.yaml")
    if not variables:
        result.add("KERNEL_VARIABLES_MISSING", "error", "kernel/variables.yaml missing or empty", "kernel/variables.yaml")
    if not branches:
        result.add("KERNEL_BRANCHES_MISSING", "error", "kernel/branches.yaml missing or empty", "kernel/branches.yaml")

    if not _iter_entries(compile_model.get("template_bindings")) and _has_nonplaceholder_paths(paths):
        result.add("MISSING_TEMPLATE_BINDING", "warning", "kernel paths exist but compile_model.template_bindings is empty", "kernel/compile_model.yaml")

    for item in _iter_entries(paths.get("kernel_paths")):
        path_id = str(item.get("id") or item.get("stable_key") or "").strip()
        for binding in _as_list(item.get("template_binding_ids")):
            binding_id = str(binding).strip()
            if binding_id and binding_id not in template_ids and binding_id not in ids:
                result.add("DANGLING_TEMPLATE_BINDING", "error", f"unknown template binding {binding_id}", "kernel/paths.yaml", path_id)
        for ref in _as_list(item.get("evidence_refs")):
            if str(ref) not in evidence_ids:
                result.add("DANGLING_EVIDENCE_REF", "error", f"unknown evidence ref {ref}", "kernel/paths.yaml", path_id)


def _validate_cross_layer(
    docs: dict[str, Any],
    ids: dict[str, dict[str, Any]],
    evidence_ids: set[str],
    result: CompileResult,
) -> None:
    for rel in CROSS_LAYER_FILES:
        data = _as_dict(docs.get(rel))
        if not data:
            result.add("CROSS_LAYER_EMPTY", "warning", f"{rel} is empty", rel)
            continue
        unresolved = _as_list(data.get("unresolved")) + _as_list(data.get("unknowns"))
        conflicts = _as_list(data.get("conflicts"))
        result.unresolved_count += len(unresolved)
        result.conflict_count += len(conflicts)

    lineage = _as_dict(docs.get("cross_layer/variable_lineage.yaml"))
    variables = _iter_entries(lineage.get("variables") or lineage.get("lineage"))
    for item in variables:
        var_id = str(item.get("variable_id") or item.get("id") or "").strip()
        if var_id.startswith("VAR_") and var_id not in ids:
            result.add("DANGLING_LINEAGE_VARIABLE", "error", f"lineage references unknown variable {var_id}", "cross_layer/variable_lineage.yaml")
        if not (_as_list(item.get("produced_by")) or _as_list(item.get("written_by")) or item.get("source")):
            result.add("LINEAGE_NO_SOURCE", "warning", f"lineage {var_id or '<unknown>'} has no source/write site", "cross_layer/variable_lineage.yaml", var_id)
        if not (_as_list(item.get("consumed_by")) or _as_list(item.get("read_by")) or _as_list(item.get("controls"))):
            result.add("LINEAGE_NO_DOWNSTREAM", "warning", f"lineage {var_id or '<unknown>'} has no downstream read/control site", "cross_layer/variable_lineage.yaml", var_id)

    tiling_to_kernel = _as_dict(docs.get("cross_layer/tiling_to_kernel.yaml"))
    for item in _iter_entries(tiling_to_kernel.get("links") or tiling_to_kernel.get("relations")):
        refs = _collect_id_like_values(item)
        if not any(ref.startswith(("KEY_", "VAR_", "FAM")) for ref in refs):
            result.add("TILING_TO_KERNEL_NO_UPSTREAM", "warning", "tiling_to_kernel link lacks key/family/variable source", "cross_layer/tiling_to_kernel.yaml")
        if not any(ref.startswith(("KPATH_", "KTPL_", "KBR")) or re.match(r"K\d+", ref) for ref in refs):
            result.add("TILING_TO_KERNEL_NO_KERNEL", "warning", "tiling_to_kernel link lacks kernel target", "cross_layer/tiling_to_kernel.yaml")


def _validate_contracts(docs: dict[str, Any], ids: dict[str, dict[str, Any]], result: CompileResult) -> None:
    for rel in CONTRACT_FILES:
        data = _as_dict(docs.get(rel))
        if not data:
            result.add("CONTRACT_EMPTY", "error", f"{rel} missing or empty", rel)
            continue
        if not data.get("purpose") and not data.get("contract"):
            result.add("CONTRACT_NO_PURPOSE", "warning", f"{rel} should describe purpose/contract", rel)
    code_change = _as_dict(docs.get("contracts/code_change.yaml"))
    required = ("target", "upstream", "downstream", "recommended_checks")
    for key in required:
        if key not in code_change:
            result.add("CODE_CHANGE_CONTRACT_INCOMPLETE", "error", f"contracts/code_change.yaml missing {key}", "contracts/code_change.yaml")
    testcase = _as_dict(docs.get("contracts/testcase.yaml"))
    for key in ("input_domain", "derived_variables", "typed_constraints", "kernel_branch_obligations"):
        if key not in testcase:
            result.add("TESTCASE_CONTRACT_INCOMPLETE", "warning", f"contracts/testcase.yaml missing {key}", "contracts/testcase.yaml")


def _derive_counts(docs: dict[str, Any], result: CompileResult) -> None:
    for rel in (
        "tiling/constraints.yaml",
        "cross_layer/input_to_tiling.yaml",
        "cross_layer/tiling_to_kernel.yaml",
        "cross_layer/behavior_graph.yaml",
        "cross_layer/impact_graph.yaml",
    ):
        data = _as_dict(docs.get(rel))
        for key in ("relations", "links", "edges", "impacts"):
            result.relation_count += len(_iter_entries(data.get(key)))


def _write_compile_outputs(uo_root: Path, result: CompileResult) -> None:
    out = {
        "version": 1,
        "op_name": result.op_name,
        "compiled_at": datetime.now(tz=timezone.utc).isoformat(),
        "status": result.status,
        "summary": {
            "entity_count": result.entity_count,
            "alias_count": result.alias_count,
            "evidence_count": result.evidence_count,
            "relation_count": result.relation_count,
            "unresolved_count": result.unresolved_count,
            "conflict_count": result.conflict_count,
        },
        "issues": [issue.to_dict() for issue in result.issues],
    }
    write_text(uo_root / "archive" / "runs" / "kb_compile_report.yaml", _to_yaml(out))
    hashes = {
        "version": 1,
        "op_name": result.op_name,
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "artifact_hashes": result.artifact_hashes,
    }
    write_text(uo_root / "archive" / "runs" / "canonical_hashes.yaml", _to_yaml(hashes))


def _iter_entries(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        out: list[dict[str, Any]] = []
        for key, item in value.items():
            if isinstance(item, dict):
                merged = {"id": key, **item} if "id" not in item else dict(item)
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
    if value in (None, ""):
        return []
    return [value]


def _valid_lines(value: Any) -> bool:
    if isinstance(value, int):
        return value > 0
    if isinstance(value, list):
        return all(isinstance(item, int) and item > 0 for item in value)
    if isinstance(value, dict):
        start = value.get("start")
        end = value.get("end", start)
        return isinstance(start, int) and isinstance(end, int) and 0 < start <= end
    return False


def _find_keys(value: Any, key: str, path: str = "") -> list[tuple[Any, str]]:
    found: list[tuple[Any, str]] = []
    if isinstance(value, dict):
        for k, v in value.items():
            child_path = f"{path}.{k}" if path else str(k)
            if k == key:
                found.append((v, child_path))
            found.extend(_find_keys(v, key, child_path))
    elif isinstance(value, list):
        for idx, item in enumerate(value):
            found.extend(_find_keys(item, key, f"{path}[{idx}]"))
    return found


def _collect_id_like_values(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for k, v in value.items():
            if str(k).endswith(("_id", "_ids", "_ref", "_refs")) or str(k) in {"var", "source", "target"}:
                for item in _as_list(v):
                    if isinstance(item, str):
                        found.add(item)
            found.update(_collect_id_like_values(v))
    elif isinstance(value, list):
        for item in value:
            found.update(_collect_id_like_values(item))
    elif isinstance(value, str):
        for token in re.findall(r"\b(?:SYM|VAR|REL|EV|SRC|KEY|KPATH|KBR|KTPL|CL|CON)_[A-Z0-9_]+\b", value):
            found.add(token)
    return found


def _has_nonplaceholder_paths(paths: dict[str, Any]) -> bool:
    entries = paths.get("kernel_paths")
    if isinstance(entries, dict) and entries:
        return True
    if isinstance(entries, list) and entries:
        return True
    return False


def _to_yaml(data: Any, indent: int = 0) -> str:
    sp = "  " * indent
    if isinstance(data, dict):
        if not data:
            return sp + "{}\n"
        lines: list[str] = []
        for key, val in data.items():
            if isinstance(val, (dict, list)):
                lines.append(f"{sp}{key}:")
                lines.append(_to_yaml(val, indent + 1).rstrip("\n"))
            else:
                lines.append(f"{sp}{key}: {_yaml_scalar(val)}")
        return "\n".join(lines) + "\n"
    if isinstance(data, list):
        if not data:
            return sp + "[]\n"
        lines = []
        for item in data:
            if isinstance(item, (dict, list)):
                lines.append(f"{sp}-")
                lines.append(_to_yaml(item, indent + 1).rstrip("\n"))
            else:
                lines.append(f"{sp}- {_yaml_scalar(item)}")
        return "\n".join(lines) + "\n"
    return sp + _yaml_scalar(data) + "\n"


def _yaml_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if text == "" or any(ch in text for ch in ":#{}[]&*!|>'\"%@`\n"):
        return json.dumps(text, ensure_ascii=False)
    return text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate and compile understand-operator canonical KB artifacts")
    parser.add_argument("repo_root", type=Path, help="AscendC operator repository root")
    parser.add_argument("--op-name", required=True, help="Operator name")
    parser.add_argument("--check-only", action="store_true", help="Do not write compile report files")
    args = parser.parse_args(argv)

    repo_root = args.repo_root.resolve()
    op_name = safe_op_name(args.op_name, repo_root)
    uo_root = operator_root(repo_root, op_name)
    result = compile_kb(uo_root, op_name, write_outputs=not args.check_only)
    print(
        json.dumps(
            {
                "status": result.status,
                "issues": len(result.issues),
                "entity_count": result.entity_count,
                "relation_count": result.relation_count,
                "report": str(uo_root / "archive" / "runs" / "kb_compile_report.yaml"),
            },
            ensure_ascii=False,
        )
    )
    return 0 if result.status != "fail" else 2


if __name__ == "__main__":
    raise SystemExit(main())
