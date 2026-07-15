from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import yaml

if __package__ in (None, ""):
    _ROOT = Path(__file__).resolve().parents[2]
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))

from understand_operator._operator.artifacts import existing_operator_root, safe_op_name


def validate_graph_review(repo_root: Path, op_name: str) -> tuple[int, dict[str, Any]]:
    root = existing_operator_root(repo_root.resolve(), safe_op_name(op_name, repo_root))
    trigger = _read(root / "checks/graph_review_trigger.yaml")
    report = _read(root / "checks/graph_review.yaml")
    errors: list[str] = []
    warnings: list[str] = []
    if trigger.get("status") != "ready":
        errors.append("checks/graph_review_trigger.yaml is missing or not ready")
    if not report:
        errors.append("checks/graph_review.yaml is missing")
    status = str(report.get("status") or "")
    if status not in {"pass", "warn", "fail"}:
        errors.append("checks/graph_review.yaml status must be pass, warn, or fail")
    expected = trigger.get("input_hashes") if isinstance(trigger.get("input_hashes"), dict) else {}
    actual = {"graphs/raw": _tree_hash(root / "graphs/raw"), "graphs/derived": _tree_hash(root / "graphs/derived"), "checks/completeness.yaml": _file_hash(root / "checks/completeness.yaml")}
    for key, digest in expected.items():
        if actual.get(key) != digest:
            errors.append(f"graph review input hash stale: {key}")
    report_hashes = report.get("input_hashes") if isinstance(report.get("input_hashes"), dict) else {}
    for key, digest in expected.items():
        if report_hashes.get(key) != digest:
            errors.append(f"graph review report did not copy trigger hash: {key}")
    if status == "fail":
        errors.append("graph review status is fail")
    if status == "warn":
        warnings.extend(str(item) for item in report.get("warnings") or ["graph review status is warn"])
    payload = {"status": "fail" if errors else "pass", "review_status": status, "errors": errors, "warnings": warnings}
    return (2 if errors else 0), payload


def _read(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _file_hash(path: Path) -> str:
    return "missing" if not path.exists() else "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _tree_hash(folder: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(folder.rglob("*.yaml")) if folder.exists() else []:
        digest.update(path.relative_to(folder).as_posix().encode("utf-8")); digest.update(path.read_bytes())
    return "sha256:" + digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("repo", nargs="?", default=".")
    parser.add_argument("--op-name", required=True)
    args = parser.parse_args(argv)
    code, payload = validate_graph_review(Path(args.repo), args.op_name)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
