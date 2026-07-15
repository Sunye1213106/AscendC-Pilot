from __future__ import annotations

import argparse
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

from understand_operator._operator.artifacts import existing_operator_root, safe_op_name
from understand_operator._operator.fact_hashes import all_fact_hashes, file_hash
from understand_operator._operator.spec import spec_bundle_hash


def build_compile_gate(repo_root: Path, op_name: str) -> tuple[int, list[str]]:
    if yaml is None:
        return 2, ["PyYAML is required"]
    repo_root = repo_root.resolve()
    uo_root = existing_operator_root(repo_root, safe_op_name(op_name, repo_root))
    if not uo_root.exists():
        return 2, [f"operator KB root not found: {uo_root}"]
    receipt = uo_root / "checks" / "step3" / "receipt.yaml"
    if not receipt.exists() or _read_yaml(receipt).get("status") != "pass":
        return 2, ["checks/step3/receipt.yaml is missing or not pass"]
    facts_hashes = facts_hashes_for(uo_root)
    receipt_hashes = _read_yaml(receipt).get("input_hashes")
    if not isinstance(receipt_hashes, dict):
        return 2, ["checks/step3/receipt.yaml missing input_hashes"]
    receipt_fact_hashes = {str(k): str(v) for k, v in receipt_hashes.items() if str(k).startswith("facts/")}
    if receipt_fact_hashes != facts_hashes:
        return 2, _hash_mismatch_messages("facts do not match Step 3 receipt", receipt_fact_hashes, facts_hashes)
    payload = {
        "version": 1,
        "artifact": {"type": "checks.compile_gate", "schema_version": 1, "owner": "facts-validator"},
        "snapshot": _snapshot(uo_root),
        "status": "pass",
        "checked_at": datetime.now(tz=timezone.utc).isoformat(),
        "step3_receipt_hash": file_hash(receipt),
        "facts_hashes": facts_hashes,
        "items": [],
        "relations": [],
        "unresolved": [],
    }
    out = uo_root / "checks" / "compile_gate.yaml"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return 0, [f"wrote {out}"]


def facts_hashes_for(uo_root: Path) -> dict[str, str]:
    return all_fact_hashes(uo_root)


def compile_gate_errors(uo_root: Path) -> list[str]:
    path = uo_root / "checks" / "compile_gate.yaml"
    if not path.exists():
        return ["checks/compile_gate.yaml is missing"]
    gate = _read_yaml(path)
    if gate.get("status") != "pass":
        return ["checks/compile_gate.yaml is not pass"]
    expected = gate.get("facts_hashes") if isinstance(gate.get("facts_hashes"), dict) else {}
    actual = facts_hashes_for(uo_root)
    errors: list[str] = []
    if expected != actual:
        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))
        changed = sorted(rel for rel in set(expected) & set(actual) if expected[rel] != actual[rel])
        if missing:
            errors.append(f"facts removed after compile gate: {', '.join(missing)}")
        if extra:
            errors.append(f"facts added after compile gate: {', '.join(extra)}")
        if changed:
            errors.append(f"facts changed after compile gate: {', '.join(changed)}")
    receipt = uo_root / "checks" / "step3" / "receipt.yaml"
    if receipt.exists():
        receipt_doc = _read_yaml(receipt)
        receipt_hashes = receipt_doc.get("input_hashes") if isinstance(receipt_doc.get("input_hashes"), dict) else {}
        receipt_fact_hashes = {str(k): str(v) for k, v in receipt_hashes.items() if str(k).startswith("facts/")}
        if receipt_fact_hashes and receipt_fact_hashes != actual:
            errors.extend(_hash_mismatch_messages("facts do not match Step 3 receipt", receipt_fact_hashes, actual))
    return errors


def _hash_mismatch_messages(label: str, expected: dict[str, str], actual: dict[str, str]) -> list[str]:
    messages: list[str] = []
    missing = sorted(set(expected) - set(actual))
    extra = sorted(set(actual) - set(expected))
    changed = sorted(rel for rel in set(expected) & set(actual) if expected[rel] != actual[rel])
    if missing:
        messages.append(f"{label}: missing {', '.join(missing)}")
    if extra:
        messages.append(f"{label}: extra {', '.join(extra)}")
    if changed:
        messages.append(f"{label}: changed {', '.join(changed)}")
    return messages


def _read_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _manifest(uo_root: Path) -> dict[str, Any]:
    path = uo_root / "manifest.yaml"
    return _read_yaml(path) if path.exists() else {}


def _snapshot(uo_root: Path) -> dict[str, str]:
    manifest = _manifest(uo_root)
    source = manifest.get("source") if isinstance(manifest.get("source"), dict) else {}
    return {
        "run_id": str(manifest.get("current_run_id") or "UO_RUN_COMPILE"),
        "source_snapshot_id": str(source.get("snapshot_id") or "SOURCE_COMPILE"),
        "source_revision": str(source.get("revision") or "unknown"),
        "spec_bundle_hash": spec_bundle_hash(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Freeze fact hashes before raw graph compilation.")
    parser.add_argument("repo", nargs="?", default=".", help="Repository root")
    parser.add_argument("--op-name", help="Operator name. Defaults to repository name.")
    args = parser.parse_args(argv)
    repo_root = Path(args.repo).resolve()
    op_name = safe_op_name(args.op_name, repo_root)
    code, messages = build_compile_gate(repo_root, op_name)
    stream = sys.stderr if code else sys.stdout
    for message in messages:
        print(message, file=stream)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
