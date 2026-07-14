from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
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

from understand_operator._operator.artifacts import resolve_existing_operator_root, safe_op_name, write_text
from understand_operator.scripts.build_compile_gate import compile_gate_errors, facts_hashes_for
from understand_operator.scripts.materialize_derived_graph import materialize_derived_graph
from understand_operator.scripts.source_graph_compiler import compile_source_graph
from understand_operator.scripts.uo_query_readonly import query_readonly

MOJIBAKE_MARKERS = ("閳?", "閿?", "鈫?", "ā†?", "\ufffd")


def run_quality_gate(repo_root: Path, op_name: str) -> tuple[int, dict[str, Any]]:
    if yaml is None:
        return 2, {"status": "red", "blockers": ["PyYAML is required"], "checks": {}}
    repo_root = repo_root.resolve()
    resolved = resolve_existing_operator_root(repo_root, safe_op_name(op_name, repo_root))
    if resolved is None:
        return 2, {"status": "red", "blockers": [f"KB not found via manifest/aliases for {op_name}"], "checks": {}}
    resolved_name, base = resolved
    checks: dict[str, str] = {}
    blockers: list[str] = []
    warnings: list[str] = []

    _check_exists(base, checks, blockers, "phase0_receipt", _phase0_receipts(base))
    _check_report(base, checks, blockers, "phase1_validation", "checks/step1/validation.yaml")
    _check_report(base, checks, blockers, "step2_receipt", "checks/step2/receipt.yaml")
    _check_report(base, checks, blockers, "step3_receipt", "checks/step3/receipt.yaml")

    _check_receipt_freshness(base, "checks/step2/receipt.yaml", checks, blockers, "step2_receipt_fresh")
    _check_receipt_freshness(base, "checks/step3/receipt.yaml", checks, blockers, "step3_receipt_fresh")

    compile_errors = compile_gate_errors(base)
    if compile_errors:
        checks["compile_gate_fresh"] = "fail"
        blockers.extend(compile_errors)
    else:
        checks["compile_gate_fresh"] = "pass"

    raw_code, raw_messages = compile_source_graph(repo_root, resolved_name)
    checks["raw_graph_consistency"] = "pass" if raw_code == 0 else "fail"
    if raw_code:
        blockers.extend(raw_messages)

    derived_code, derived_messages = materialize_derived_graph(repo_root, resolved_name)
    checks["derived_graph_reversibility"] = "pass" if derived_code == 0 else "fail"
    if derived_code:
        blockers.extend(derived_messages)

    query_ok = _query_smoke(repo_root, resolved_name, base, blockers)
    checks["query_smoke"] = "pass" if query_ok else "fail"
    checks["no_test_generation_results"] = "pass" if _no_test_generation_results(base, blockers) else "fail"

    status = "red" if blockers else "yellow" if warnings else "green"
    decision = "not_usable" if blockers else "usable_for_query"
    payload = {
        "version": 1,
        "op_name": resolved_name,
        "status": status,
        "decision": decision,
        "checked_at": datetime.now(tz=timezone.utc).isoformat(),
        "checks": checks,
        "blockers": blockers,
        "warnings": warnings,
        "facts_hashes": facts_hashes_for(base),
    }
    write_text(base / "quality.yaml", yaml.safe_dump(payload, sort_keys=False, allow_unicode=True))
    return (2 if blockers else 0), payload


def _phase0_receipts(base: Path) -> list[Path]:
    return sorted((base / "runs").glob("*/phase0/receipt.yaml")) if (base / "runs").exists() else []


def _check_exists(base: Path, checks: dict[str, str], blockers: list[str], name: str, paths: list[Path]) -> None:
    if paths:
        checks[name] = "pass"
    else:
        checks[name] = "fail"
        blockers.append(f"{name} is missing under {base}")


def _check_report(base: Path, checks: dict[str, str], blockers: list[str], name: str, rel: str) -> None:
    path = base / rel
    if not path.exists():
        checks[name] = "fail"
        blockers.append(f"{rel} is missing")
        return
    data = _read_yaml(path)
    if data.get("status") != "pass":
        checks[name] = "fail"
        blockers.append(f"{rel} status is not pass")
        return
    checks[name] = "pass"


def _check_receipt_freshness(base: Path, rel: str, checks: dict[str, str], blockers: list[str], name: str) -> None:
    path = base / rel
    data = _read_yaml(path)
    expected = data.get("input_hashes") if isinstance(data.get("input_hashes"), dict) else {}
    stale: list[str] = []
    for item_rel, digest in expected.items():
        item_path = base / str(item_rel)
        if not item_path.exists():
            stale.append(f"{item_rel} missing")
            continue
        actual = "sha256:" + hashlib.sha256(item_path.read_bytes()).hexdigest()
        if actual != digest:
            stale.append(f"{item_rel} changed")
    if stale:
        checks[name] = "fail"
        blockers.extend(f"{rel} stale: {item}" for item in stale)
    else:
        checks[name] = "pass"


def _query_smoke(repo_root: Path, op_name: str, base: Path, blockers: list[str]) -> bool:
    derived_nodes = _load_list(base / "graphs" / "derived" / "nodes.yaml", "nodes")
    if not derived_nodes:
        blockers.append("query smoke has no derived graph node to query")
        return False
    entity = str(derived_nodes[0].get("id") or "")
    if not entity:
        blockers.append("query smoke derived node lacks id")
        return False
    try:
        result = query_readonly(repo_root, op_name, entity)
    except Exception as exc:  # noqa: BLE001
        blockers.append(f"query smoke failed: {exc}")
        return False
    if result.get("writes") or result.get("cbm_writes"):
        blockers.append("query smoke attempted writes")
        return False
    if result.get("query", {}).get("order") != ["derived", "raw", "yaml", "source"]:
        blockers.append("query smoke did not use Derived -> Raw -> YAML -> Source order")
        return False
    return True


def _no_test_generation_results(base: Path, blockers: list[str]) -> bool:
    forbidden_names = {"generated_cases", "actual_test_result", "observed_coverage", "case_csv"}
    hits: list[str] = []
    for path in base.rglob("*.yaml"):
        rel = path.relative_to(base).as_posix()
        if rel.startswith("."):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for name in forbidden_names:
            if f"{name}:" in text:
                hits.append(f"{rel}:{name}")
    if hits:
        blockers.append("UO contains test generation result fields: " + ", ".join(hits[:8]))
        return False
    return True


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists() or yaml is None:
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _load_list(path: Path, key: str) -> list[dict[str, Any]]:
    data = _read_yaml(path)
    values = data.get(key)
    return [item for item in values if isinstance(item, dict)] if isinstance(values, list) else []


def _has_compute_golden_mapping(compute_graph: object, golden_model: object) -> bool:
    graph = compute_graph if isinstance(compute_graph, dict) else {}
    steps = graph.get("compute_steps")
    values = steps.values() if isinstance(steps, dict) else steps if isinstance(steps, list) else []
    return any(isinstance(item, dict) and item.get("golden_step_ref") for item in values)


def _has_resource_flow(resources: object) -> bool:
    data = resources if isinstance(resources, dict) else {}
    buffers = data.get("buffers")
    sync_events = data.get("sync_events")
    buffer_values = buffers.values() if isinstance(buffers, dict) else buffers if isinstance(buffers, list) else []
    sync_values = sync_events.values() if isinstance(sync_events, dict) else sync_events if isinstance(sync_events, list) else []
    has_buffer = any(isinstance(item, dict) and item.get("producer") and item.get("consumer") for item in buffer_values)
    has_sync = any(isinstance(item, dict) and item.get("from") and item.get("to") for item in sync_values)
    return has_buffer and has_sync


def _check_text_encoding(base: Path, warnings: list[str]) -> dict[str, str]:
    hits: list[str] = []
    for path in base.rglob("*"):
        if path.is_file() and path.suffix.lower() in {".yaml", ".yml", ".md"}:
            text = path.read_text(encoding="utf-8", errors="replace")
            if any(marker in text for marker in MOJIBAKE_MARKERS):
                hits.append(path.relative_to(base).as_posix())
    if hits:
        warnings.append("possible mojibake markers in canonical text: " + ", ".join(hits[:8]))
        return {"canonical_text_encoding": "warn"}
    return {"canonical_text_encoding": "pass"}


def _check_cross_layer_graph_completeness(base: Path, warnings: list[str], blockers: list[str]) -> dict[str, str]:
    variables = _read_yaml(base / "tiling" / "variables.yaml")
    behavior = _read_yaml(base / "cross_layer" / "behavior_graph.yaml")
    impact = _read_yaml(base / "cross_layer" / "impact_graph.yaml")
    checks = {"cross_layer_graph_schema": "pass", "cross_layer_graph_coverage": "pass"}
    for rel, graph in (("cross_layer/behavior_graph.yaml", behavior), ("cross_layer/impact_graph.yaml", impact)):
        if graph.get("version") != 1:
            checks["cross_layer_graph_schema"] = "fail"
            blockers.append(f"{rel} was not generated by deterministic graph builder")
    variable_inventory = variables.get("variables") if isinstance(variables.get("variables"), dict) else {}
    variable_count = len(variable_inventory)
    behavior_nodes = behavior.get("nodes") if isinstance(behavior.get("nodes"), list) else []
    impact_nodes = impact.get("nodes") if isinstance(impact.get("nodes"), list) else []
    behavior_edges = behavior.get("edges") if isinstance(behavior.get("edges"), list) else []
    impact_edges = impact.get("edges") if isinstance(impact.get("edges"), list) else []
    if variable_count and (len(behavior_nodes) < max(1, variable_count // 2) or len(impact_nodes) < max(1, variable_count // 2)):
        checks["cross_layer_graph_coverage"] = "fail"
        blockers.append("cross-layer graphs are too small for tiling variable inventory")
    if variable_count > 1 and (not behavior_edges or not impact_edges):
        checks["cross_layer_graph_coverage"] = "fail"
        blockers.append("cross-layer graphs have no edges despite non-trivial tiling variables")
    classification = variables.get("impact_classification") if isinstance(variables.get("impact_classification"), dict) else {}
    scopes_by_name: dict[str, set[str]] = {}
    for scope, names in classification.items():
        if isinstance(names, list):
            for name in names:
                scopes_by_name.setdefault(str(name), set()).add(str(scope))
    conflicts = sorted(name for name, scopes in scopes_by_name.items() if "constant" in scopes and len(scopes) > 1)
    if conflicts:
        checks["cross_layer_graph_coverage"] = "fail"
        blockers.append("tiling/variables.yaml classifies variable as constant and non-constant: " + ", ".join(conflicts[:8]))
    return checks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Understand Operator Phase 3 final quality gate.")
    parser.add_argument("repo", nargs="?", default=".", help="Repository root")
    parser.add_argument("--op-name", help="Operator name. Defaults to repository name.")
    args = parser.parse_args(argv)
    repo_root = Path(args.repo).resolve()
    op_name = safe_op_name(args.op_name, repo_root)
    code, payload = run_quality_gate(repo_root, op_name)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
