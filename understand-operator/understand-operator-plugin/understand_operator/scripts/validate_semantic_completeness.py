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

from understand_operator._operator.artifacts import existing_operator_root, safe_op_name, write_text
from understand_operator._operator.spec import spec_bundle_hash

PLACEHOLDERS = {"placeholder", "minimal fixture placeholder", "todo", "unknown", "not analyzed", "not applicable", "待补充", "暂未分析"}


def validate_semantic_completeness(repo_root: Path, op_name: str) -> tuple[int, dict[str, Any]]:
    root = existing_operator_root(repo_root.resolve(), safe_op_name(op_name, repo_root))
    findings: list[dict[str, str]] = []
    warnings: list[str] = []
    artifacts = {
        "facts/host.yaml": _read(root / "facts/host.yaml"),
        "facts/compute.yaml": _read(root / "facts/compute.yaml"),
        "facts/kernel/overview.yaml": _read(root / "facts/kernel/overview.yaml"),
        "facts/kernel/slice_manifest.yaml": _read(root / "facts/kernel/slice_manifest.yaml"),
    }
    artifact_counts = {rel: _confirmed_count(doc) for rel, doc in artifacts.items()}
    section_counts: dict[str, dict[str, int]] = {rel: _section_counts(doc) for rel, doc in artifacts.items()}

    _require_any(artifact_counts, "facts/host.yaml", findings)
    _require_any(artifact_counts, "facts/compute.yaml", findings)
    _require_any(artifact_counts, "facts/kernel/overview.yaml", findings)
    if not _has_any_section(artifacts["facts/host.yaml"], ("tiling_key", "tilingdata_writes", "expressions", "calls", "variables")):
        findings.append(_finding("PHASE2_HOST_INCOMPLETE", "facts/host.yaml", "host needs a tiling key, tilingdata write, expression, call, or runtime variable"))
    if not _has_any_section(artifacts["facts/compute.yaml"], ("operations", "dataflow")):
        findings.append(_finding("PHASE2_COMPUTE_INCOMPLETE", "facts/compute.yaml", "compute needs an operation or data movement/dataflow item"))
    if not _has_any_section(artifacts["facts/kernel/overview.yaml"], ("entries", "functions")):
        findings.append(_finding("PHASE2_KERNEL_OVERVIEW_INCOMPLETE", "facts/kernel/overview.yaml", "kernel overview needs an entry or function"))

    slices = _slice_ids(artifacts["facts/kernel/slice_manifest.yaml"])
    if not slices:
        findings.append(_finding("PHASE3_SLICE_MANIFEST_EMPTY", "facts/kernel/slice_manifest.yaml", "at least one confirmed kernel slice is required"))
    for slice_id in slices:
        rel = f"facts/kernel/slices/{slice_id}.yaml"
        doc = _read(root / rel)
        count = _confirmed_count(doc)
        artifact_counts[rel] = count
        section_counts[rel] = _section_counts(doc)
        if count <= 0:
            findings.append(_finding("PHASE3_SLICE_EMPTY", rel, "each declared slice needs at least one confirmed item"))
        if not _has_any_section(doc, ("tilingdata_reads", "calls", "dataflow", "memory", "synchronization", "branches", "loops")):
            findings.append(_finding("PHASE3_SLICE_SEMANTICS_MISSING", rel, "slice needs at least one concrete semantic category"))

    for rel, doc in list(artifacts.items()) + [(f"facts/kernel/slices/{sid}.yaml", _read(root / f"facts/kernel/slices/{sid}.yaml")) for sid in slices]:
        _check_unresolved(rel, doc, findings, warnings)

    payload = {
        "version": 1,
        "artifact": {"type": "checks.completeness", "schema_version": 1, "owner": "facts-validator"},
        "snapshot": _snapshot(root),
        "status": "fail" if findings else "pass",
        "artifact_counts": artifact_counts,
        "section_counts": section_counts,
        "blocking_findings": findings,
        "warnings": warnings,
        "input_hashes": _input_hashes(root),
        "items": [],
        "relations": [],
        "unresolved": [],
    }
    write_text(root / "checks/completeness.yaml", yaml.safe_dump(payload, sort_keys=False, allow_unicode=True))
    return (2 if findings else 0), payload


def _read(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _sections(doc: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    sections = doc.get("sections")
    if isinstance(sections, dict):
        return [(str(k), v) for k, v in sections.items() if isinstance(v, dict)]
    return [("", doc)]


def _confirmed_count(doc: dict[str, Any]) -> int:
    return sum(1 for _section, unit in _sections(doc) for item in unit.get("items") or [] if isinstance(item, dict) and item.get("status") == "confirmed")


def _section_counts(doc: dict[str, Any]) -> dict[str, int]:
    return {section or "$": sum(1 for item in unit.get("items") or [] if isinstance(item, dict) and item.get("status") == "confirmed") for section, unit in _sections(doc)}


def _has_any_section(doc: dict[str, Any], sections: tuple[str, ...]) -> bool:
    counts = _section_counts(doc)
    return any(counts.get(section, 0) > 0 for section in sections)


def _slice_ids(doc: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for _section, unit in _sections(doc):
        for item in unit.get("items") or []:
            if isinstance(item, dict) and item.get("status") == "confirmed":
                raw = item.get("slice_id") or (item.get("identity") or {}).get("normalized", {}).get("slice_id") or item.get("id")
                if raw:
                    values.append(str(raw).replace("SLICE_", "").lower() if str(raw).startswith("SLICE_") else str(raw))
    return sorted(set(values))


def _check_unresolved(rel: str, doc: dict[str, Any], findings: list[dict[str, str]], warnings: list[str]) -> None:
    for section, unit in _sections(doc):
        for index, item in enumerate(unit.get("unresolved") or []):
            if not isinstance(item, dict):
                continue
            text = str(item.get("question") or item.get("description") or item.get("reason") or "").strip().lower()
            label = f"{rel}#{section or '$'}/unresolved/{index}"
            if text in PLACEHOLDERS:
                findings.append(_finding("UNRESOLVED_PLACEHOLDER", label, "unresolved description is only a placeholder"))
            if item.get("reason") != "missing_external_source" and not (item.get("sources") or item.get("candidate_sources")):
                findings.append(_finding("UNRESOLVED_SOURCE_MISSING", label, "unresolved needs source location evidence unless missing_external_source"))
            if item.get("reason") == "not_applicable" and not (section and text and (item.get("sources") or item.get("candidate_sources"))):
                findings.append(_finding("NOT_APPLICABLE_INCOMPLETE", label, "not_applicable needs section, reason, and source evidence"))


def _require_any(counts: dict[str, int], rel: str, findings: list[dict[str, str]]) -> None:
    if counts.get(rel, 0) <= 0:
        findings.append(_finding("PHASE2_ARTIFACT_EMPTY", rel, "artifact needs at least one confirmed item"))


def _finding(code: str, target: str, message: str) -> dict[str, str]:
    return {"code": code, "target": target, "message": message}


def _snapshot(root: Path) -> dict[str, str]:
    manifest = _read(root / "manifest.yaml")
    source = manifest.get("source") if isinstance(manifest.get("source"), dict) else {}
    return {"run_id": str(manifest.get("current_run_id") or ""), "source_snapshot_id": str(source.get("snapshot_id") or ""), "source_revision": str(source.get("revision") or "unknown"), "spec_bundle_hash": spec_bundle_hash()}


def _input_hashes(root: Path) -> dict[str, str]:
    result = {}
    for path in sorted((root / "facts").rglob("*.yaml")) if (root / "facts").exists() else []:
        result[path.relative_to(root).as_posix()] = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("repo", nargs="?", default=".")
    parser.add_argument("--op-name", required=True)
    args = parser.parse_args(argv)
    code, payload = validate_semantic_completeness(Path(args.repo), args.op_name)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
