from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


EVIDENCE_ID_RE = re.compile(r"^(?:EV|SRC)_[A-Z0-9_]+$")
SOURCE_ID_RE = re.compile(r"^SRC_[A-Z0-9_]+$")


@dataclass(frozen=True)
class EvidenceIssue:
    code: str
    message: str
    artifact: str
    target: str = ""
    severity: str = "error"
    expected_format: str = "EV_* or SRC_* registered in registry/evidence.yaml"
    repair_action: str = "resume the owning agent with source-backed Candidate JSON evidence"

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "severity": self.severity,
            "artifact": self.artifact,
            "target": self.target,
            "message": self.message,
            "expected_format": self.expected_format,
            "repair_action": self.repair_action,
        }


def validate_evidence_closure(docs: dict[str, Any]) -> list[EvidenceIssue]:
    registry = _as_dict(docs.get("registry/evidence.yaml"))
    fact_index = _as_dict(docs.get("evidence/fact_index.yaml"))
    source_index = _as_dict(docs.get("evidence/source_index.yaml"))
    issues: list[EvidenceIssue] = []
    seen: set[tuple[str, str, str, str]] = set()

    def add(issue: EvidenceIssue) -> None:
        key = (issue.code, issue.artifact, issue.target, issue.message)
        if key not in seen:
            seen.add(key)
            issues.append(issue)

    registry_ids: set[str] = set()
    fingerprints: dict[str, str] = {}
    for index, item in enumerate(_entries(registry.get("evidence"))):
        ev_id = str(item.get("id") or "").strip()
        target = f"evidence[{index}]"
        if not ev_id:
            add(EvidenceIssue("MISSING_EVIDENCE_ID", "evidence entry missing id", "registry/evidence.yaml", target))
            continue
        if not EVIDENCE_ID_RE.fullmatch(ev_id):
            add(
                EvidenceIssue(
                    "BAD_EVIDENCE_REF_FORMAT",
                    f"evidence id must be canonical EV_/SRC_: {ev_id!r}",
                    "registry/evidence.yaml",
                    ev_id,
                )
            )
            continue
        registry_ids.add(ev_id)
        file_name = str(item.get("file") or item.get("path") or "").strip()
        if not file_name or Path(file_name).is_absolute() or ".." in Path(file_name).parts:
            add(EvidenceIssue("BAD_EVIDENCE_PATH", f"evidence {ev_id} must use repo-relative file", "registry/evidence.yaml", ev_id))
        if not _valid_lines(item.get("lines")):
            add(EvidenceIssue("BAD_EVIDENCE_LINES", f"evidence {ev_id} has invalid lines", "registry/evidence.yaml", ev_id))
        for required in ("symbol", "kind", "status"):
            if not item.get(required):
                add(
                    EvidenceIssue(
                        "EVIDENCE_SCHEMA_ERROR",
                        f"evidence {ev_id} missing required field {required}",
                        "registry/evidence.yaml",
                        ev_id,
                        expected_format="id, file, lines, symbol, kind, status",
                    )
                )
        fp = repr({key: item.get(key) for key in ("file", "path", "lines", "symbol", "kind", "source_hash", "excerpt_hash")})
        previous = fingerprints.get(ev_id)
        if previous and previous != fp:
            add(EvidenceIssue("EVIDENCE_ID_CONFLICT", f"evidence {ev_id} has conflicting definitions", "registry/evidence.yaml", ev_id))
        fingerprints[ev_id] = fp

    fact_refs = set(_fact_index_refs(fact_index))
    source_refs = set(_source_index_refs(source_index))
    all_refs: list[tuple[str, str, str]] = []
    for rel, doc in docs.items():
        for refs, path in _find_keys(doc, "evidence_refs"):
            if not isinstance(refs, (list, dict)):
                issues.append(EvidenceIssue("BAD_EVIDENCE_REFS_TYPE", "evidence_refs must be a YAML list", rel, path))
                continue
            values = refs.keys() if isinstance(refs, dict) else refs
            for ref in values:
                all_refs.append((rel, path, str(ref).strip()))

    for source_name, refs, code in (
        ("fact_index", fact_refs, "FACT_INDEX_REGISTRY_MISMATCH"),
        ("source_index", source_refs, "SOURCE_INDEX_REGISTRY_MISMATCH"),
    ):
        artifact = "evidence/fact_index.yaml" if source_name == "fact_index" else "evidence/source_index.yaml"
        for ref in sorted(refs):
            if source_name == "source_index" and not SOURCE_ID_RE.fullmatch(ref):
                add(EvidenceIssue("SOURCE_INDEX_BAD_PREFIX", f"source_index source_spans ref must be SRC_*: {ref!r}", artifact, ref, expected_format="SRC_*"))
            elif not EVIDENCE_ID_RE.fullmatch(ref):
                add(EvidenceIssue("BAD_EVIDENCE_REF_FORMAT", f"{source_name} ref must be EV_/SRC_: {ref!r}", artifact, ref))
            elif ref not in registry_ids:
                add(EvidenceIssue(code, f"{source_name} ref {ref} is not registered", artifact, ref))

    for rel, path, ref in all_refs:
        if not ref or not EVIDENCE_ID_RE.fullmatch(ref):
            add(EvidenceIssue("BAD_EVIDENCE_REF_FORMAT", f"evidence ref must be a stable EV_/SRC_ id: {ref!r}", rel, path))
        elif ref not in registry_ids:
            add(EvidenceIssue("DANGLING_EVIDENCE_REF", f"unknown evidence ref {ref}", rel, path))
            add(EvidenceIssue("EVIDENCE_REGISTRY_MISSING_ENTRY", f"registry/evidence.yaml missing {ref}", "registry/evidence.yaml", ref))
    return issues


def _fact_index_refs(fact_index: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for item in _entries(fact_index.get("facts")):
        refs.extend(str(ref) for ref in _as_list(item.get("evidence_refs")))
    evidence_refs = fact_index.get("evidence_refs")
    if isinstance(evidence_refs, dict):
        refs.extend(str(ref) for ref in evidence_refs)
    elif isinstance(evidence_refs, list):
        for item in evidence_refs:
            refs.append(str(item.get("id") if isinstance(item, dict) else item))
    return refs


def _source_index_refs(source_index: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    source_spans = source_index.get("source_spans")
    if not isinstance(source_spans, dict):
        # Legacy flat source indexes used SP* keys. They are not authoritative
        # evidence refs unless explicitly linked through source_spans.
        return []
    for key, item in _mapping_entries(source_spans):
        ref = str(item.get("registry_ref") or item.get("id") or key)
        refs.append(ref)
    return refs


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


def _entries(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        return [item for item in value.values() if isinstance(item, dict)]
    return []


def _mapping_entries(value: Any) -> list[tuple[str, dict[str, Any]]]:
    if not isinstance(value, dict):
        return []
    return [(str(key), item if isinstance(item, dict) else {"value": item}) for key, item in value.items()]


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value in (None, "", {}, []):
        return []
    return [value]


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
