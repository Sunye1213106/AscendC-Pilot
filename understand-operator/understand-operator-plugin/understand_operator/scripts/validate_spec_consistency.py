from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

if __package__ in (None, ""):
    _ROOT = Path(__file__).resolve().parents[2]
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))

from understand_operator._operator.catalog import match_catalog_entry
from understand_operator._operator.artifacts import operator_root
from understand_operator._operator.identity import IdentityError, resolve_identity
from understand_operator._operator.reference_paths import reference_declarations
from understand_operator._operator.run_context import active_run_id, phase0_snapshot, read_yaml_mapping
from understand_operator._operator.spec import load_spec
from understand_operator.scripts.finalize_phase0 import finalize_phase0
from understand_operator.scripts.macro_scope_scan import main as macro_scope_scan_main
from understand_operator.scripts.prepare_operator import main as prepare_operator_main
from understand_operator.scripts.review_checkpoint import main as review_checkpoint_main
from understand_operator.scripts.semantic_enrichment import main as semantic_enrichment_main
from understand_operator.scripts.validate_facts import validate_facts


MODEL_FORBIDDEN_FIELDS = {"id", "stable_id", "canonical_key", "source_text", "code_hash", "file_hash", "sources"}
COMMON_FORMAL_REQUIRED = {"id", "kind", "status", "identity", "sources"}


@dataclass(frozen=True)
class SpecError:
    code: str
    target: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "target": self.target, "message": self.message}


def validate_spec_consistency(plugin_root: Path | None = None) -> list[SpecError]:
    if yaml is None:
        return [SpecError("YAML_IMPORT_ERROR", ".", "PyYAML is required")]
    spec = load_spec()
    root = spec["root"]
    errors: list[SpecError] = []
    entity_spec = spec.get("entity_types") if isinstance(spec.get("entity_types"), dict) else {}
    entity_types = entity_spec.get("entity_types") if isinstance(entity_spec.get("entity_types"), dict) else {}
    kind_groups = entity_spec.get("kind_groups") if isinstance(entity_spec.get("kind_groups"), dict) else {}
    relation_types = (spec.get("relation_types") or {}).get("relation_types") or {}
    valid_targets = set(entity_types) | set(kind_groups) | {"any"}

    _validate_entity_types(entity_types, kind_groups, errors)
    _validate_relation_types(relation_types, valid_targets, errors)
    _validate_formal_schemas(root, entity_spec, entity_types, valid_targets, errors)
    _validate_candidate_schema(root, errors)
    _validate_agent_targets(plugin_root or root.parents[1], spec, errors)
    _validate_strategy_aliases(entity_spec, entity_types, errors)
    _validate_identity_strategy_probes(entity_types, root, errors)
    _validate_identity_reference_graph(entity_types, kind_groups, errors)
    _validate_phase3_agent_protocol(plugin_root or root.parents[1], errors)
    _validate_final_order(plugin_root or root.parents[1], errors)
    _validate_init_runtime_contracts(plugin_root or root.parents[1], errors)
    return errors


def _validate_entity_types(entity_types: dict[str, Any], kind_groups: dict[str, Any], errors: list[SpecError]) -> None:
    valid_targets = set(entity_types) | set(kind_groups) | {"any"}
    for kind, config in sorted(entity_types.items()):
        if not isinstance(config, dict):
            continue
        for field in ("prefix", "identity_strategy", "required_identity_fields", "reference_fields"):
            if field not in config:
                errors.append(SpecError("SPEC_IDENTITY_FIELD_MISMATCH", "entity_types.yaml", f"{kind} missing {field}"))
        required = config.get("required_identity_fields")
        if not isinstance(required, list) or not required:
            errors.append(SpecError("SPEC_IDENTITY_FIELD_MISMATCH", "entity_types.yaml", f"{kind} required_identity_fields must be non-empty"))
        refs = config.get("reference_fields") if isinstance(config.get("reference_fields"), dict) else {}
        for cardinality in ("single", "multiple"):
            declared = refs.get(cardinality) if isinstance(refs.get(cardinality), dict) else {}
            for path, allowed in declared.items():
                suffix = "_ref" if cardinality == "single" else "_refs"
                if not str(path).split(".")[-1].endswith(suffix):
                    errors.append(SpecError("SPEC_REFERENCE_CARDINALITY_MISMATCH", "entity_types.yaml", f"{kind}.{path} must end with {suffix}"))
                _check_allowed_targets(allowed, valid_targets, errors, "SPEC_REFERENCE_KIND_UNKNOWN", f"{kind}.{path}")
        identity_refs = config.get("identity_reference_fields") if isinstance(config.get("identity_reference_fields"), dict) else {}
        identity_fields = set(str(item) for item in (required if isinstance(required, list) else []))
        for path, allowed in identity_refs.items():
            if path not in identity_fields:
                errors.append(SpecError("SPEC_IDENTITY_FIELD_MISMATCH", "entity_types.yaml", f"{kind}.{path} identity reference is not a required identity field"))
            _check_allowed_targets(allowed, valid_targets, errors, "SPEC_REFERENCE_KIND_UNKNOWN", f"{kind}.{path}")


def _validate_relation_types(relation_types: dict[str, Any], valid_targets: set[str], errors: list[SpecError]) -> None:
    for name, config in sorted(relation_types.items()):
        if not isinstance(config, dict):
            continue
        for key in ("source", "target"):
            target = str(config.get(key) or "")
            if target and target not in valid_targets:
                errors.append(SpecError("SPEC_RELATION_KIND_GROUP_UNKNOWN", "relation_types.yaml", f"{name}.{key} uses unknown kind/group {target}"))
        for index, signature in enumerate(config.get("endpoint_signatures") or []):
            if not isinstance(signature, dict):
                continue
            for key in ("source", "target"):
                target = str(signature.get(key) or "")
                if target not in valid_targets:
                    errors.append(SpecError("SPEC_RELATION_KIND_GROUP_UNKNOWN", "relation_types.yaml", f"{name}.endpoint_signatures[{index}].{key} uses unknown kind/group {target}"))


def _validate_formal_schemas(root: Path, entity_spec: dict[str, Any], entity_types: dict[str, Any], valid_targets: set[str], errors: list[SpecError]) -> None:
    for schema_path in sorted((root / "schemas").rglob("*.schema.yaml")):
        rel = schema_path.relative_to(root).as_posix()
        schema = _read_yaml(schema_path)
        kinds = [str(item) for item in schema.get("item_kind_enum") or []]
        required_common = set(str(item) for item in schema.get("required_item_fields") or [])
        if kinds and not COMMON_FORMAL_REQUIRED <= required_common:
            errors.append(SpecError("SPEC_FORMAL_IDENTITY_NOT_REQUIRED", rel, f"required_item_fields must include {sorted(COMMON_FORMAL_REQUIRED)}"))
        forbidden_required = required_common & MODEL_FORBIDDEN_FIELDS - {"id", "sources"}
        if forbidden_required:
            errors.append(SpecError("SPEC_MODEL_FORBIDDEN_FIELD_REQUIRED", rel, f"required_item_fields contains Python-owned fields {sorted(forbidden_required)}"))
        kind_required = schema.get("kind_required_fields") if isinstance(schema.get("kind_required_fields"), dict) else {}
        for kind in kinds:
            if kind not in entity_types:
                errors.append(SpecError("SPEC_REFERENCE_KIND_UNKNOWN", rel, f"schema kind {kind} missing from entity_types.yaml"))
                continue
            declarations = reference_declarations(entity_spec, kind)
            required_fields = [str(item) for item in kind_required.get(kind, []) if isinstance(item, str)]
            for field in required_fields:
                if field in MODEL_FORBIDDEN_FIELDS:
                    errors.append(SpecError("SPEC_MODEL_FORBIDDEN_FIELD_REQUIRED", rel, f"{kind}.{field} is Python-owned and must not be schema-required"))
                if field.endswith("_ref") or field.endswith("_refs"):
                    declaration = declarations.get(field)
                    if declaration is None:
                        errors.append(SpecError("SPEC_REQUIRED_REFERENCE_UNDECLARED", rel, f"{kind}.{field} is required but not declared in entity_types.reference_fields"))
                    elif field.endswith("_ref") and declaration.cardinality != "single":
                        errors.append(SpecError("SPEC_REFERENCE_CARDINALITY_MISMATCH", rel, f"{kind}.{field} must be single"))
                    elif field.endswith("_refs") and declaration.cardinality != "multiple":
                        errors.append(SpecError("SPEC_REFERENCE_CARDINALITY_MISMATCH", rel, f"{kind}.{field} must be multiple"))
            for path, declaration in declarations.items():
                _check_allowed_targets(declaration.allowed, valid_targets, errors, "SPEC_REFERENCE_KIND_UNKNOWN", f"{kind}.{path}")


def _validate_candidate_schema(root: Path, errors: list[SpecError]) -> None:
    path = root / "schemas" / "candidate" / "candidate_batch.schema.json"
    try:
        json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        errors.append(SpecError("SPEC_CANDIDATE_SCHEMA_INVALID", path.as_posix(), str(exc)))


def _validate_agent_targets(plugin_root: Path, spec: dict[str, Any], errors: list[SpecError]) -> None:
    ownership = (spec.get("ownership") or {}).get("owners") or {}
    paths = [
        *sorted((plugin_root / "agents").glob("*.md")),
        *sorted((plugin_root / "prompts").rglob("*.md")),
        *sorted((plugin_root / "skills" / "uo-init").glob("*.md")),
    ]
    for path in paths:
        text = path.read_text(encoding="utf-8")
        owner = path.stem
        for target_path, section, has_section in _target_objects(text):
            if has_section and section == "":
                errors.append(SpecError("SPEC_AGENT_TARGET_EMPTY_SECTION", path.relative_to(plugin_root).as_posix(), f"{target_path} uses empty target section"))
            match = match_catalog_entry(spec, target_path, writable_only=True)
            if not match:
                errors.append(SpecError("SPEC_AGENT_TARGET_UNKNOWN", path.name, f"{target_path} is not in catalog"))
                continue
            if path.parts[-2:] != ("agents", path.name):
                continue
            if match.entry.get("owner") != owner:
                errors.append(SpecError("SPEC_AGENT_OWNER_MISMATCH", path.name, f"{owner} cannot write {target_path}"))
            sections = match.entry.get("section_schemas") if isinstance(match.entry.get("section_schemas"), dict) else {}
            if section and section not in sections:
                errors.append(SpecError("SPEC_AGENT_TARGET_UNKNOWN", path.name, f"{target_path} section {section} is not in catalog"))
            allowed = ownership.get(owner, {}).get("may_write") if isinstance(ownership.get(owner), dict) else []
            if allowed and not any(_path_matches(target_path, str(pattern)) for pattern in allowed):
                errors.append(SpecError("SPEC_AGENT_OWNER_MISMATCH", path.name, f"ownership.yaml does not allow {owner} to write {target_path}"))


def _target_objects(text: str) -> list[tuple[str, str, bool]]:
    found: list[tuple[str, str, bool]] = []
    pattern = re.compile(r'"target"\s*:\s*\{(?P<body>[^{}]*)\}', re.DOTALL)
    for match in pattern.finditer(text):
        body = match.group("body")
        path_match = re.search(r'"path"\s*:\s*"([^"]+)"', body)
        if not path_match:
            continue
        section_match = re.search(r'"section"\s*:\s*"([^"]*)"', body)
        found.append((path_match.group(1), section_match.group(1) if section_match else "", section_match is not None))
    return found


def _validate_identity_strategy_probes(entity_types: dict[str, Any], root: Path, errors: list[SpecError]) -> None:
    repo_root = root
    for kind, config in sorted(entity_types.items()):
        if not isinstance(config, dict):
            continue
        sample = _identity_probe_for(kind, str(config.get("identity_strategy") or ""))
        if sample is None:
            errors.append(SpecError("SPEC_IDENTITY_PROBE_MISSING", "entity_types.yaml", f"{kind} has no identity probe"))
            continue
        try:
            resolved = resolve_identity(kind, sample, repo_root=repo_root)
        except IdentityError as exc:
            errors.append(SpecError("SPEC_IDENTITY_RESOLVER_FIELD_MISMATCH", "entity_types.yaml", f"{kind} probe failed: {exc.code}: {exc.message}"))
            continue
        required = {str(item) for item in config.get("required_identity_fields") or []}
        actual = set(resolved.normalized_identity)
        if actual != required:
            errors.append(SpecError("SPEC_IDENTITY_RESOLVER_FIELD_MISMATCH", "entity_types.yaml", f"{kind} normalized fields {sorted(actual)} != required {sorted(required)}"))
        extended = _extended_identity_probe_for(str(config.get("identity_strategy") or ""), sample)
        if extended != sample:
            try:
                extended_resolved = resolve_identity(kind, extended, repo_root=repo_root)
            except IdentityError as exc:
                errors.append(SpecError("SPEC_IDENTITY_OPTIONAL_FIELD_LEAK", "entity_types.yaml", f"{kind} extended probe failed: {exc.code}: {exc.message}"))
                continue
            extended_actual = set(extended_resolved.normalized_identity)
            if extended_actual != required:
                errors.append(SpecError("SPEC_IDENTITY_OPTIONAL_FIELD_LEAK", "entity_types.yaml", f"{kind} extended normalized fields {sorted(extended_actual)} != required {sorted(required)}"))


def _validate_strategy_aliases(entity_spec: dict[str, Any], entity_types: dict[str, Any], errors: list[SpecError]) -> None:
    aliases = entity_spec.get("strategy_aliases") if isinstance(entity_spec.get("strategy_aliases"), dict) else {}
    for kind, config in sorted(entity_types.items()):
        if not isinstance(config, dict):
            continue
        strategy = str(config.get("identity_strategy") or "")
        alias = aliases.get(strategy)
        if not isinstance(alias, dict) or "required_identity_fields" not in alias:
            continue
        alias_fields = [str(item) for item in alias.get("required_identity_fields") or []]
        kind_fields = [str(item) for item in config.get("required_identity_fields") or []]
        if alias_fields != kind_fields:
            errors.append(SpecError("SPEC_STRATEGY_ALIAS_FIELD_MISMATCH", "entity_types.yaml", f"{kind} uses {strategy} fields {kind_fields}, alias declares {alias_fields}"))


def _validate_identity_reference_graph(entity_types: dict[str, Any], kind_groups: dict[str, Any], errors: list[SpecError]) -> None:
    graph: dict[str, set[str]] = {}
    for kind, config in sorted(entity_types.items()):
        refs = config.get("identity_reference_fields") if isinstance(config, dict) and isinstance(config.get("identity_reference_fields"), dict) else {}
        targets: set[str] = set()
        for field, allowed in refs.items():
            if not isinstance(allowed, list):
                continue
            for target in allowed:
                name = str(target)
                if name == "any":
                    continue
                if name in entity_types:
                    targets.add(name)
                elif name in kind_groups:
                    for expanded in kind_groups.get(name) or []:
                        if str(expanded) in entity_types:
                            targets.add(str(expanded))
                else:
                    errors.append(SpecError("SPEC_REFERENCE_KIND_UNKNOWN", "entity_types.yaml", f"{kind}.{field} uses unknown identity reference target {name}"))
        graph[kind] = targets
    for kind in sorted(graph):
        if _has_identity_ref_cycle(kind, graph, set(), set()):
            errors.append(SpecError("SPEC_IDENTITY_REFERENCE_CYCLE", "entity_types.yaml", f"identity_reference_fields for {kind} can form a cycle"))


def _has_identity_ref_cycle(kind: str, graph: dict[str, set[str]], visiting: set[str], seen: set[str]) -> bool:
    if kind in visiting:
        return True
    if kind in seen:
        return False
    visiting.add(kind)
    for target in graph.get(kind, set()):
        if _has_identity_ref_cycle(target, graph, visiting, seen):
            return True
    visiting.remove(kind)
    seen.add(kind)
    return False


def _identity_probe_for(kind: str, strategy: str) -> dict[str, Any] | None:
    span = {"start_line": 1, "end_line": 1}
    by_strategy: dict[str, dict[str, Any]] = {
        "scoped_declaration": {"source_file": "sample.cpp", "scope_symbol": "DemoScope", "source_name": "value", "declaration_span": span},
        "qualified_symbol_signature": {"qualified_symbol": "Demo::Function", "signature": "void()"},
        "scoped_callsite": {"source_file": "sample.cpp", "scope_symbol": "DemoScope", "callee_symbol": "Call", "call_span": span},
        "scoped_predicate": {"source_file": "sample.cpp", "scope_symbol": "DemoScope", "predicate_span": span},
        "branch_outcome": {"parent_branch_ref": "BRANCH_PARENT", "outcome": "true"},
        "scoped_loop": {"source_file": "sample.cpp", "scope_symbol": "DemoScope", "loop_header_span": span},
        "repo_path": {"path": "sample.cpp"},
        "qualified_struct": {"qualified_struct_name": "DemoStruct"},
        "struct_field": {"qualified_struct_name": "DemoStruct", "field_name": "field"},
        "scoped_field_write": {"source_file": "sample.cpp", "scope_symbol": "DemoScope", "struct_name": "DemoStruct", "field_name": "field", "write_span": span},
        "scoped_field_read": {"source_file": "sample.cpp", "scope_symbol": "DemoScope", "struct_name": "DemoStruct", "field_name": "field", "read_span": span},
        "operator_io": {"operator_name": "DemoOp", "direction": "input", "index": 0},
        "operator_named_value": {"operator_name": "DemoOp", "name": "seed"},
        "kernel_entry": {"qualified_entry_symbol": "DemoKernel", "signature": "void()", "discriminator": "generic"},
        "kernel_slice_signature": {"kernel_entry_ref": "KERNEL_ENTRY", "template_binding_signature": "generic", "structural_flow_signature": "read-compute-write", "tilingdata_read_signature": "none", "output_signature": "out0"},
        "slice_interface": {"source_slice_ref": "KERNEL_SLICE_A", "target_slice_ref": "KERNEL_SLICE_B", "interface_kind": "data", "position": "0"},
        "compute_operation": {"compute_scope": "DemoCompute", "operation_type": "add", "output_identity": "out0", "source_span": span},
        "endpoint_relation_entity": {"source_ref": "SRC", "target_ref": "DST"},
        "scoped_policy": {"source_file": "sample.cpp", "scope_symbol": "DemoScope", "policy_kind": "tolerance", "source_span": span},
        "scoped_resource": {"source_file": "sample.cpp", "scope_symbol": "DemoScope", "source_name": "buf", "declaration_span": span, "resource_kind": "buffer"},
        "scoped_event": {"source_file": "sample.cpp", "scope_symbol": "DemoScope", "event_kind": "setflag", "event_identifier": "flag0", "source_span": span},
        "scoped_site": {"source_file": "sample.cpp", "scope_symbol": "DemoScope", "site_kind": "frontier", "site_span": span},
        "architecture_variant": {"variant_name": "generic", "file_set_signature": ["sample.cpp"], "architecture_discriminator": "generic"},
        "source_rule": {"source_file": "sample.cpp", "rule_kind": "include", "pattern": "*.cpp"},
        "source_span": {"source_file": "sample.cpp", "scope_symbol": "DemoScope", "source_span": span},
        "qualified_symbol": {"qualified_symbol": "DemoSymbol"},
        "external_dependency": {"logical_path": "external.hpp", "dependency_type": "third_party", "discovered_from": "include"},
    }
    return dict(by_strategy[strategy]) if strategy in by_strategy else None


def _extended_identity_probe_for(strategy: str, sample: dict[str, Any]) -> dict[str, Any]:
    extended = dict(sample)
    if strategy == "qualified_symbol_signature":
        extended["source_file"] = "sample.cpp"
        extended["definition_span"] = {"start_line": 1, "end_line": 1}
    if strategy == "architecture_variant":
        extended["architecture_discriminator"] = extended.get("architecture_discriminator") or "generic"
    return extended


def _validate_phase3_agent_protocol(plugin_root: Path, errors: list[SpecError]) -> None:
    forbidden = ("directly write YAML", "source_text", "code_hash", "file_hash", "--write-report", "nine files")
    for rel in ("agents/uo-kernel-slice-planner.md", "agents/uo-kernel-slice-agent.md"):
        path = plugin_root / rel
        if not path.exists():
            continue
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            lowered = line.lower()
            if any(term.lower() in lowered for term in forbidden) and not _is_forbidding_context(lowered):
                errors.append(SpecError("SPEC_PHASE3_AGENT_PROTOCOL_LEGACY", rel, f"legacy instruction at line {line_no}: {line.strip()}"))


def _is_forbidding_context(line: str) -> bool:
    return any(marker in line for marker in ("must not", "never", "do not", "forbidden", "not provide", "orchestrator runs", "--scope all"))


def _validate_final_order(plugin_root: Path, errors: list[SpecError]) -> None:
    checks = {
        "skills/uo-init/SKILL.md": ("prepare_abstraction_rules.py", "uo-behavior-abstraction-agent", "materialize_derived_graph.py", "build_query_index.py", "uo_query_readonly.py", "--smoke", "quality_gate.py"),
        "prompts/01_workflow_orchestrator.md": ("prepare_abstraction_rules.py", "uo-behavior-abstraction-agent", "materialize_derived_graph.py", "build_query_index", "uo_query_readonly.py --smoke", "quality_gate.py"),
    }
    for rel, ordered_terms in checks.items():
        text = (plugin_root / rel).read_text(encoding="utf-8") if (plugin_root / rel).exists() else ""
        cursor = -1
        for term in ordered_terms:
            index = text.find(term, cursor + 1)
            if index == -1:
                errors.append(SpecError("SPEC_FINAL_ORDER_INVALID", rel, f"missing or out-of-order term {term}"))
                break
            cursor = index


def _validate_init_runtime_contracts(plugin_root: Path, errors: list[SpecError]) -> None:
    with tempfile.TemporaryDirectory(prefix="uo-init-spec-") as tmp:
        repo = Path(tmp) / "repo"
        repo.mkdir()
        (repo / "op_host").mkdir()
        (repo / "op_kernel").mkdir()
        (repo / "op_host" / "demo.cpp").write_text(
            "void DemoOpHost() { int x = 1; TilingData tile; tile.v = x; }\n",
            encoding="utf-8",
        )
        (repo / "op_kernel" / "demo.cpp").write_text(
            "__global__ void DemoKernel() { TilingData tile; }\n",
            encoding="utf-8",
        )
        _check_phase0_prepare_outputs(plugin_root, repo, errors)
        _check_runtime_schema_probes(plugin_root, repo, errors)
        _check_phase0_roundtrip(plugin_root, repo, errors)


def _check_phase0_prepare_outputs(plugin_root: Path, repo: Path, errors: list[SpecError]) -> None:
    code = prepare_operator_main([str(repo), "--op-name", "DemoOp", "--force-new-run"])
    if code != 0:
        errors.append(SpecError("SPEC_INIT_PREPARE_FAILED", "prepare_operator.py", f"prepare_operator.py returned {code}"))
        return
    uo_root = operator_root(repo, "DemoOp")
    run_id = active_run_id(uo_root)
    phase0 = uo_root / "runs" / run_id / "phase0"
    snapshot = phase0_snapshot(uo_root, run_id)
    for rel, schema_rel in (
        ("scope_scan.yaml", "schemas/runs/scope_scan.schema.yaml"),
        ("semantic_enrichment.yaml", "schemas/runs/semantic_enrichment.schema.yaml"),
    ):
        doc = read_yaml_mapping(phase0 / rel)
        if doc.get("snapshot") != snapshot:
            errors.append(SpecError("SPEC_INIT_SNAPSHOT_MISMATCH", rel, "pending artifact snapshot does not match phase0_snapshot()"))
        rendered = json.dumps(doc, ensure_ascii=False)
        if "SOURCE_PHASE0" in rendered:
            errors.append(SpecError("SPEC_INIT_LEGACY_SNAPSHOT", rel, "pending artifact still contains SOURCE_PHASE0"))
        _assert_required_top_level(plugin_root, rel, schema_rel, doc, errors)


def _check_runtime_schema_probes(plugin_root: Path, repo: Path, errors: list[SpecError]) -> None:
    uo_root = operator_root(repo, "DemoOp")
    run_id = active_run_id(uo_root)
    phase0 = uo_root / "runs" / run_id / "phase0"
    semantic_path = phase0 / "semantic_enrichment.yaml"
    original = _read_yaml(semantic_path)

    missing_path = dict(original)
    missing_path["architecture_filter"] = {"excluded": []}
    _write_yaml(semantic_path, missing_path)
    path_errors = validate_facts(repo, "DemoOp", stage="init", run_id=run_id)
    if not any(error.code == "SCHEMA_REQUIRED_FIELD_MISSING" and "architecture_filter/included" in error.message for error in path_errors):
        errors.append(SpecError("SPEC_INIT_REQUIRED_PATH_INERT", semantic_path.relative_to(uo_root).as_posix(), "required_paths did not flag missing architecture_filter/included"))

    required_one_of = dict(original)
    required_one_of["cbm_queries"] = [{"tool": "search_graph"}]
    _write_yaml(semantic_path, required_one_of)
    one_of_errors = validate_facts(repo, "DemoOp", stage="init", run_id=run_id)
    if not any(error.code == "SCHEMA_REQUIRED_ONE_OF_MISSING" and "/cbm_queries/0/" in error.message for error in one_of_errors):
        errors.append(SpecError("SPEC_INIT_REQUIRED_ONE_OF_INERT", semantic_path.relative_to(uo_root).as_posix(), "list_item_rules.required_one_of did not flag incomplete cbm_queries[0]"))

    _write_yaml(semantic_path, original)


def _check_phase0_roundtrip(plugin_root: Path, repo: Path, errors: list[SpecError]) -> None:
    uo_root = operator_root(repo, "DemoOp")
    run_id = active_run_id(uo_root)
    phase0 = uo_root / "runs" / run_id / "phase0"

    scan_code = macro_scope_scan_main([str(repo), "--op-name", "DemoOp"])
    if scan_code != 0:
        errors.append(SpecError("SPEC_INIT_SCOPE_SCAN_FAILED", "macro_scope_scan.py", f"macro_scope_scan.py returned {scan_code}"))
        return

    semantic_code = semantic_enrichment_main([str(repo), "--op-name", "DemoOp"])
    if semantic_code != 0:
        errors.append(SpecError("SPEC_INIT_SEMANTIC_ENRICHMENT_FAILED", "semantic_enrichment.py", f"semantic_enrichment.py returned {semantic_code}"))
        return

    review_code = review_checkpoint_main([str(repo), "--op-name", "DemoOp", "--gate", "macro_scope", "--decision", "continue"])
    if review_code != 0:
        errors.append(SpecError("SPEC_INIT_SCOPE_REVIEW_FAILED", "review_checkpoint.py", f"review_checkpoint.py returned {review_code}"))
        return

    confirmed = _read_yaml(phase0 / "scope_confirmed.yaml")
    confirmed_files = confirmed.get("confirmed_file_list") if isinstance(confirmed.get("confirmed_file_list"), list) else []
    (uo_root / "cbm").mkdir(exist_ok=True)
    (uo_root / "cbm" / "index_meta.json").write_text(
        json.dumps(
            {
                "repo_root": str(repo.resolve()),
                "op_name": "DemoOp",
                "cbm_project": "demo",
                "indexed_via": "mcp",
                "cbm_mode": "fast",
                "indexed_at": "2026-01-01T00:00:00+00:00",
                "project_confirmed": True,
                "index_input": "confirmed_file_list",
                "indexed_files": confirmed_files,
                "indexed_scope_roots": [],
                "cbm_status": {"available": True, "retry_count": 0, "fallback": "", "last_error": ""},
            },
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )

    finalize_code, finalize_messages = finalize_phase0(repo, "DemoOp")
    if finalize_code != 0:
        errors.append(SpecError("SPEC_INIT_FINALIZE_FAILED", "finalize_phase0.py", "; ".join(finalize_messages)))
        return

    receipt = _read_yaml(phase0 / "receipt.yaml")
    receipt_snapshot = receipt.get("snapshot") if isinstance(receipt.get("snapshot"), dict) else {}
    if receipt_snapshot != phase0_snapshot(uo_root, run_id):
        errors.append(SpecError("SPEC_INIT_RECEIPT_SNAPSHOT_MISMATCH", "runs/phase0/receipt.yaml", "receipt snapshot does not match phase0 context snapshot"))
    input_hashes = receipt.get("input_hashes")
    if not isinstance(input_hashes, dict) or not {
        f"runs/{run_id}/phase0/context.yaml",
        f"runs/{run_id}/phase0/installed_skill_check.yaml",
        f"runs/{run_id}/phase0/ignore_rules.yaml",
        f"runs/{run_id}/phase0/scope_scan.yaml",
        f"runs/{run_id}/phase0/semantic_enrichment.yaml",
        f"runs/{run_id}/phase0/scope_review.yaml",
    } <= set(input_hashes):
        errors.append(SpecError("SPEC_INIT_RECEIPT_INPUT_HASHES_INCOMPLETE", "runs/phase0/receipt.yaml", "receipt.input_hashes does not freeze the full Phase 0 input set"))

    validation_errors = validate_facts(repo, "DemoOp", stage="step1", run_id=run_id)
    blocked = {
        "SCHEMA_REQUIRED_FIELD_MISSING",
        "SCHEMA_TOP_LEVEL_FIELD_FORBIDDEN",
        "ARTIFACT_RUN_MISMATCH",
        "ARTIFACT_SOURCE_SNAPSHOT_MISMATCH",
        "ARTIFACT_SOURCE_REVISION_MISMATCH",
        "SPEC_BUNDLE_MISMATCH",
        "PHASE0_RECEIPT_INVALID",
        "PHASE0_RECEIPT_STALE",
    }
    hits = [f"{error.code}:{error.artifact}" for error in validation_errors if error.code in blocked]
    if hits:
        errors.append(SpecError("SPEC_INIT_ROUNDTRIP_VALIDATION_FAILED", "validate_facts.py", "; ".join(hits)))


def _assert_required_top_level(plugin_root: Path, rel: str, schema_rel: str, doc: dict[str, Any], errors: list[SpecError]) -> None:
    schema = _read_yaml(plugin_root / "skills" / "understand-operator" / "spec" / schema_rel)
    required = schema.get("required_top_level") if isinstance(schema.get("required_top_level"), list) else []
    missing = [name for name in required if name not in doc]
    if missing:
        errors.append(SpecError("SPEC_INIT_PENDING_FIELDS_MISSING", rel, f"missing required pending fields: {missing}"))


def _check_allowed_targets(allowed: Any, valid_targets: set[str], errors: list[SpecError], code: str, label: str) -> None:
    if not isinstance(allowed, (list, tuple)) or not allowed:
        errors.append(SpecError("SPEC_REFERENCE_KIND_UNKNOWN", "entity_types.yaml", f"{label} has no allowed targets"))
        return
    for item in allowed:
        if str(item) not in valid_targets:
            errors.append(SpecError(code, "entity_types.yaml", f"{label} uses unknown kind/group {item}"))


def _read_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _path_matches(path: str, pattern: str) -> bool:
    import fnmatch

    return fnmatch.fnmatch(path, pattern.split("#", 1)[0])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate schema/entity/relation/agent consistency.")
    parser.add_argument("--plugin-root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args(argv)
    errors = validate_spec_consistency(args.plugin_root.resolve())
    payload = {"status": "fail" if errors else "pass", "errors": [error.to_dict() for error in errors]}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 2 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
