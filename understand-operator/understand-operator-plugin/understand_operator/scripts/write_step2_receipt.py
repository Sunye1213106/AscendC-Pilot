from __future__ import annotations

import argparse
import hashlib
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
from understand_operator._operator.spec import catalog_entries, load_spec, spec_bundle_hash


REQUIRED_REPORTS = [
    "checks/step2/host_validation.yaml",
    "checks/step2/compute_validation.yaml",
    "checks/step2/kernel_overview_validation.yaml",
    "checks/step2/review.yaml",
]


def write_step2_receipt(repo_root: Path, op_name: str) -> tuple[int, list[str]]:
    if yaml is None:
        return 2, ["PyYAML is required"]
    repo_root = repo_root.resolve()
    uo_root = existing_operator_root(repo_root, safe_op_name(op_name, repo_root))
    if not uo_root.exists():
        return 2, [f"operator KB root not found: {uo_root}"]

    messages: list[str] = []
    current_fact_hashes = _step2_fact_hashes(uo_root)
    validator_hashes: dict[str, str] = {}
    for rel in REQUIRED_REPORTS:
        path = uo_root / rel
        if not path.exists():
            messages.append(f"missing required Step 2 gate report: {rel}")
            continue
        doc = _read_yaml(path)
        if doc.get("status") != "pass":
            messages.append(f"{rel} status is not pass")
        if doc.get("blocking_findings"):
            messages.append(f"{rel} has blocking_findings")
        if doc.get("errors"):
            messages.append(f"{rel} has errors")
        report_hashes = doc.get("input_hashes")
        if not isinstance(report_hashes, dict):
            messages.append(f"{rel} missing input_hashes")
        elif rel == "checks/step2/review.yaml":
            if report_hashes != current_fact_hashes:
                messages.append(f"{rel} input_hashes do not match current Step 2 facts")
        else:
            validator_hashes.update({str(k): str(v) for k, v in report_hashes.items()})
    if validator_hashes and validator_hashes != current_fact_hashes:
        messages.append("Step 2 validator input_hashes do not match current Step 2 facts")

    if messages:
        return 2, messages

    input_hashes = _step2_input_hashes(uo_root)
    receipt = {
        "version": 1,
        "artifact": {"type": "checks.step2.receipt", "schema_version": 1, "owner": "uo-orchestrator"},
        "snapshot": {
            "run_id": _current_run_id(uo_root),
            "source_snapshot_id": _source_snapshot_id(uo_root),
            "source_revision": _source_revision(uo_root),
            "spec_bundle_hash": spec_bundle_hash(),
        },
        "status": "pass",
        "checked_at": datetime.now(tz=timezone.utc).isoformat(),
        "required_reports": REQUIRED_REPORTS,
        "input_hashes": input_hashes,
        "items": [],
        "relations": [],
        "unresolved": [],
    }
    out = uo_root / "checks" / "step2" / "receipt.yaml"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(receipt, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return 0, [f"wrote {out}"]


def _read_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _step2_input_hashes(uo_root: Path) -> dict[str, str]:
    spec = load_spec()
    paths: list[str] = []
    for entry in catalog_entries(spec):
        rel = str(entry.get("path") or "").replace("\\", "/")
        if entry.get("required_after_stage") == "step2" and (rel.startswith("facts/") or rel in REQUIRED_REPORTS):
            if "*" not in rel:
                paths.append(rel)
    paths.extend(REQUIRED_REPORTS)
    result: dict[str, str] = {}
    for rel in sorted(set(paths)):
        path = uo_root / rel
        if path.exists() and path.is_file():
            result[rel] = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def _step2_fact_hashes(uo_root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for rel_root in ("facts/host", "facts/compute", "facts/kernel/overview"):
        root = uo_root / rel_root
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.yaml")):
            rel = path.relative_to(uo_root).as_posix()
            result[rel] = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def _manifest(uo_root: Path) -> dict[str, Any]:
    path = uo_root / "manifest.yaml"
    if not path.exists():
        return {}
    return _read_yaml(path)


def _current_run_id(uo_root: Path) -> str:
    return str(_manifest(uo_root).get("current_run_id") or "UO_RUN_STEP2")


def _source_snapshot_id(uo_root: Path) -> str:
    source = _manifest(uo_root).get("source")
    if isinstance(source, dict):
        return str(source.get("snapshot_id") or "SOURCE_STEP2")
    return "SOURCE_STEP2"


def _source_revision(uo_root: Path) -> str:
    source = _manifest(uo_root).get("source")
    if isinstance(source, dict):
        return str(source.get("revision") or "unknown")
    return "unknown"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write Step 2 receipt after Python gates and LLM review pass.")
    parser.add_argument("repo", nargs="?", default=".", help="Repository root")
    parser.add_argument("--op-name", help="Operator name. Defaults to repository name.")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo).resolve()
    op_name = safe_op_name(args.op_name, repo_root)
    code, messages = write_step2_receipt(repo_root, op_name)
    stream = sys.stderr if code else sys.stdout
    for message in messages:
        print(message, file=stream)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
