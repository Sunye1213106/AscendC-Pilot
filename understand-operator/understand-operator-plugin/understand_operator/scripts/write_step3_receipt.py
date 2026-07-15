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


REQUIRED_REPORTS = [
    "checks/step3/slice_validations.yaml",
    "checks/step3/review_trigger.yaml",
]


def write_step3_receipt(repo_root: Path, op_name: str) -> tuple[int, list[str]]:
    if yaml is None:
        return 2, ["PyYAML is required"]
    repo_root = repo_root.resolve()
    uo_root = existing_operator_root(repo_root, safe_op_name(op_name, repo_root))
    if not uo_root.exists():
        return 2, [f"operator KB root not found: {uo_root}"]
    step2_receipt = uo_root / "checks" / "step2" / "receipt.yaml"
    if not _report_passes(step2_receipt):
        return 2, ["checks/step2/receipt.yaml is missing or not pass"]
    stale = _hashes_still_match(uo_root, step2_receipt)
    if stale:
        return 2, stale

    messages: list[str] = []
    current_fact_hashes = _all_fact_hashes(uo_root)
    for rel in REQUIRED_REPORTS:
        path = uo_root / rel
        if not path.exists():
            messages.append(f"missing required Step 3 gate report: {rel}")
            continue
        doc = _read_yaml(path)
        allowed_status = {"triggered", "skipped"} if rel.endswith("review_trigger.yaml") else {"pass"}
        if doc.get("status") not in allowed_status:
            messages.append(f"{rel} status is not pass")
        if doc.get("blocking_findings"):
            messages.append(f"{rel} has blocking_findings")
        if doc.get("errors"):
            messages.append(f"{rel} has errors")
        report_hashes = doc.get("input_hashes")
        if not isinstance(report_hashes, dict):
            messages.append(f"{rel} missing input_hashes")
        elif report_hashes != current_fact_hashes:
            messages.append(f"{rel} input_hashes do not match current facts")
    review_trigger = _read_yaml(uo_root / "checks/step3/review_trigger.yaml")
    review_status = review_trigger.get("status")
    trigger_hashes = review_trigger.get("input_hashes") if isinstance(review_trigger.get("input_hashes"), dict) else {}
    if review_status == "triggered":
        review_rel = "checks/step3/review.yaml"
        review_path = uo_root / review_rel
        if not review_path.exists():
            messages.append(f"missing required Step 3 review report: {review_rel}")
        else:
            review_doc = _read_yaml(review_path)
            if review_doc.get("status") != "pass":
                messages.append(f"{review_rel} status is not pass")
            if review_doc.get("blocking_findings"):
                messages.append(f"{review_rel} has blocking_findings")
            if review_doc.get("errors"):
                messages.append(f"{review_rel} has errors")
            if review_doc.get("input_hashes") != trigger_hashes:
                messages.append(f"{review_rel} input_hashes do not match review trigger")
    elif review_status != "skipped":
        messages.append("checks/step3/review_trigger.yaml status must be skipped or triggered")
    if messages:
        return 2, messages

    receipt = {
        "version": 1,
        "artifact": {"type": "checks.step3.receipt", "schema_version": 1, "owner": "uo-orchestrator"},
        "snapshot": _snapshot(uo_root),
        "status": "pass",
        "checked_at": datetime.now(tz=timezone.utc).isoformat(),
        "required_reports": REQUIRED_REPORTS,
        "input_hashes": _hash_inputs(uo_root),
        "items": [],
        "relations": [],
        "unresolved": [],
    }
    out = uo_root / "checks" / "step3" / "receipt.yaml"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(receipt, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return 0, [f"wrote {out}"]


def _report_passes(path: Path) -> bool:
    return path.exists() and _read_yaml(path).get("status") == "pass"


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _manifest(uo_root: Path) -> dict[str, Any]:
    path = uo_root / "manifest.yaml"
    return _read_yaml(path) if path.exists() else {}


def _snapshot(uo_root: Path) -> dict[str, str]:
    manifest = _manifest(uo_root)
    source = manifest.get("source") if isinstance(manifest.get("source"), dict) else {}
    return {
        "run_id": str(manifest.get("current_run_id") or "UO_RUN_STEP3"),
        "source_snapshot_id": str(source.get("snapshot_id") or "SOURCE_STEP3"),
        "source_revision": str(source.get("revision") or "unknown"),
        "spec_bundle_hash": spec_bundle_hash(),
    }


def _hash_inputs(uo_root: Path) -> dict[str, str]:
    paths = list(REQUIRED_REPORTS) + ["checks/step2/receipt.yaml"]
    if (uo_root / "checks/step3/review.yaml").exists():
        paths.append("checks/step3/review.yaml")
    paths.extend(path.relative_to(uo_root).as_posix() for path in sorted((uo_root / "facts").rglob("*.yaml")))
    result: dict[str, str] = {}
    for rel in sorted(set(paths)):
        path = uo_root / rel
        if path.exists() and path.is_file():
            result[rel] = file_hash(path)
    return result


def _all_fact_hashes(uo_root: Path) -> dict[str, str]:
    return all_fact_hashes(uo_root)


def _hashes_still_match(uo_root: Path, receipt: Path) -> list[str]:
    doc = _read_yaml(receipt)
    expected = doc.get("input_hashes") if isinstance(doc.get("input_hashes"), dict) else {}
    errors: list[str] = []
    for rel, digest in expected.items():
        path = uo_root / str(rel)
        if not path.exists():
            errors.append(f"{rel} recorded by Step 2 receipt is missing")
            continue
        actual = file_hash(path)
        if actual != digest:
            errors.append(f"{rel} changed after Step 2 receipt")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write Step 3 receipt after slice validation and review pass.")
    parser.add_argument("repo", nargs="?", default=".", help="Repository root")
    parser.add_argument("--op-name", help="Operator name. Defaults to repository name.")
    args = parser.parse_args(argv)
    repo_root = Path(args.repo).resolve()
    op_name = safe_op_name(args.op_name, repo_root)
    code, messages = write_step3_receipt(repo_root, op_name)
    stream = sys.stderr if code else sys.stdout
    for message in messages:
        print(message, file=stream)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
