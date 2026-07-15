from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
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
from understand_operator._operator.spec import spec_bundle_hash
from understand_operator.scripts.build_compile_gate import compile_gate_errors, facts_hashes_for
from understand_operator.scripts.uo_query_readonly import query_smoke
from understand_operator.scripts.validate_graph_review import validate_graph_review
from understand_operator.scripts.validate_semantic_completeness import validate_semantic_completeness
from understand_operator.scripts.validate_facts import validate_facts
from understand_operator.scripts.verify_derived_graph import verify_derived_graph
from understand_operator.scripts.verify_raw_graph import verify_raw_graph

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

    _check_current_phase0_receipt(base, checks, blockers)
    _check_report(base, checks, blockers, "phase1_validation", "checks/step1/validation.yaml")
    _check_report(base, checks, blockers, "step2_receipt", "checks/step2/receipt.yaml")
    _check_report(base, checks, blockers, "step3_receipt", "checks/step3/receipt.yaml")

    formal_errors = validate_facts(repo_root, resolved_name, stage="step3", scope="all")
    checks["formal_fact_validation"] = "pass" if not formal_errors else "fail"
    blockers.extend(f"formal validation: {error.artifact}: {error.code}: {error.message}" for error in formal_errors)

    _check_receipt_freshness(base, "checks/step2/receipt.yaml", checks, blockers, "step2_receipt_fresh")
    _check_receipt_freshness(base, "checks/step3/receipt.yaml", checks, blockers, "step3_receipt_fresh")

    completeness_code, completeness = validate_semantic_completeness(repo_root, resolved_name)
    checks["semantic_completeness"] = "pass" if completeness_code == 0 and completeness.get("status") == "pass" else "fail"
    if checks["semantic_completeness"] != "pass":
        blockers.extend(f"semantic completeness: {item.get('code')}: {item.get('target')}: {item.get('message')}" for item in completeness.get("blocking_findings") or [])

    compile_errors = compile_gate_errors(base)
    if compile_errors:
        checks["compile_gate_fresh"] = "fail"
        blockers.extend(compile_errors)
    else:
        checks["compile_gate_fresh"] = "pass"

    raw_messages = verify_raw_graph(repo_root, resolved_name)
    checks["raw_graph_fresh"] = "pass" if not raw_messages else "fail"
    blockers.extend(raw_messages)

    derived_messages = verify_derived_graph(repo_root, resolved_name)
    checks["derived_graph_fresh"] = "pass" if not derived_messages else "fail"
    blockers.extend(derived_messages)

    graph_review_code, graph_review = validate_graph_review(repo_root, resolved_name)
    checks["graph_review"] = "pass" if graph_review_code == 0 else "fail"
    blockers.extend(f"graph review: {item}" for item in graph_review.get("errors") or [])
    warnings.extend(f"graph review: {item}" for item in graph_review.get("warnings") or [])
    _check_sqlite_index(base, checks, blockers)

    query_ok = _query_smoke(repo_root, resolved_name, base, blockers)
    checks["query_smoke"] = "pass" if query_ok else "fail"
    checks["no_test_generation_results"] = "pass" if _no_test_generation_results(base, blockers) else "fail"

    status = "fail" if blockers else "pass"
    decision = "not_usable" if blockers else "usable_for_query"
    payload = {
        "version": 1,
        "artifact": {"type": "checks.final", "schema_version": 1, "owner": "facts-validator"},
        "snapshot": _snapshot(base),
        "op_name": resolved_name,
        "status": status,
        "decision": decision,
        "checked_at": datetime.now(tz=timezone.utc).isoformat(),
        "checks": checks,
        "blockers": blockers,
        "warnings": warnings,
        "errors": [{"message": item} for item in blockers],
        "items": [],
        "relations": [],
        "unresolved": [],
        "facts_hashes": facts_hashes_for(base),
    }
    write_text(base / "checks" / "final.yaml", yaml.safe_dump(payload, sort_keys=False, allow_unicode=True))
    return (2 if blockers else 0), payload


def _snapshot(base: Path) -> dict[str, str]:
    manifest = _read_yaml(base / "manifest.yaml")
    source = manifest.get("source") if isinstance(manifest.get("source"), dict) else {}
    return {
        "run_id": str(manifest.get("current_run_id") or "UO_RUN_FINAL"),
        "source_snapshot_id": str(source.get("snapshot_id") or "SOURCE_FINAL"),
        "source_revision": str(source.get("revision") or "unknown"),
        "spec_bundle_hash": spec_bundle_hash(),
    }


def _check_current_phase0_receipt(base: Path, checks: dict[str, str], blockers: list[str]) -> None:
    manifest = _read_yaml(base / "manifest.yaml")
    run_id = manifest.get("current_run_id") if isinstance(manifest, dict) else None
    if not isinstance(run_id, str) or run_id == "UO_RUN_PENDING":
        checks["phase0_receipt"] = "fail"
        blockers.append("phase0_receipt: manifest.current_run_id is not active")
        return
    rel = f"runs/{run_id}/phase0/receipt.yaml"
    path = base / rel
    data = _read_yaml(path)
    if data.get("status") != "pass":
        checks["phase0_receipt"] = "fail"
        blockers.append(f"{rel} status is not pass")
        return
    snapshot = data.get("snapshot") if isinstance(data.get("snapshot"), dict) else {}
    if snapshot.get("run_id") != run_id:
        checks["phase0_receipt"] = "fail"
        blockers.append(f"{rel} run_id does not match manifest.current_run_id")
        return
    expected = data.get("input_hashes") if isinstance(data.get("input_hashes"), dict) else {}
    stale = []
    for item_rel, digest in expected.items():
        item_path = base / str(item_rel)
        if not item_path.exists():
            stale.append(f"{item_rel} missing")
            continue
        actual = "sha256:" + hashlib.sha256(item_path.read_bytes()).hexdigest()
        if actual != digest:
            stale.append(f"{item_rel} changed")
    if stale:
        checks["phase0_receipt"] = "fail"
        blockers.extend(f"{rel} stale: {item}" for item in stale)
        return
    checks["phase0_receipt"] = "pass"


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


def _check_sqlite_index(base: Path, checks: dict[str, str], blockers: list[str]) -> None:
    path = base / "indexes" / "operator_kb.sqlite"
    if not path.exists():
        checks["sqlite_index"] = "fail"; blockers.append("indexes/operator_kb.sqlite is missing"); return
    try:
        with sqlite3.connect(path) as db:
            metadata = dict(db.execute("select key,value from metadata"))
        actual = _tree_hash(base / "facts")
        if metadata.get("facts_hash") != actual:
            checks["sqlite_index"] = "fail"; blockers.append("SQLite index is stale")
        else: checks["sqlite_index"] = "pass"
    except sqlite3.Error as exc:
        checks["sqlite_index"] = "fail"; blockers.append(f"SQLite index invalid: {exc}")


def _tree_hash(folder: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(folder.rglob("*.yaml")) if folder.exists() else []: digest.update(path.read_bytes())
    return "sha256:" + digest.hexdigest()


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
    code, payload = query_smoke(repo_root, op_name)
    if code == 0:
        return True
    blockers.extend(f"query smoke: {error}" for error in payload.get("errors") or ["failed"])
    return False


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
