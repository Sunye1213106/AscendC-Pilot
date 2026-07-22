from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


STABLE_PREFIXES = (
    "SYM",
    "VAR",
    "REL",
    "EV",
    "SRC",
    "KEY",
    "FAM",
    "COMP",
    "GOLD",
    "KPATH",
    "KBR",
    "KTPL",
    "CL",
    "CON",
    "VIEW",
    "BUF",
    "SYNC",
    "RES",
    "TDF",
    "KVAR",
    "KDEC",
    "PIPE",
    "COV",
    "NUM",
)
STABLE_ID_RE = re.compile(rf"^({'|'.join(STABLE_PREFIXES)})_[A-Z0-9_]+$")
LEGACY_ID_RE = re.compile(r"^(TF\d+|K\d+|C\d+|D\d+|P\d+|R\d+|IR\d+|KR\d+|VC\d+|KU\d+|PR\d+|MG\d+)$")
ID_TOKEN_RE = re.compile(rf"\b(?:{'|'.join(STABLE_PREFIXES)})_[A-Za-z0-9_]+\b")
# Layered KB export required for TG intake (UO no longer ships contracts/testcase.yaml).
REQUIRED_KB_EXPORT_FILES = (
    "test/contract.yaml",
    "tiling/variables.yaml",
    "tiling/key_space.yaml",
    "tiling/exhaustive_key_space.yaml",
    "tiling/constraints.yaml",
    "tiling/families.yaml",
    "tiling/data_model.yaml",
    "tiling/coverage_model.yaml",
    "kernel/compile_model.yaml",
    "kernel/variables.yaml",
    "kernel/paths.yaml",
    "kernel/branches.yaml",
    "kernel/pipeline.yaml",
    "kernel/resources.yaml",
    "cross_layer/impact_graph.yaml",
    "cross_layer/tiling_to_kernel.yaml",
    "flow/golden_model.yaml",
    "flow/numerical_model.yaml",
    "quality.yaml",
)
# Backward-compatible alias (tests / older callers).
REQUIRED_TESTCASE_CONTRACT_FILES = REQUIRED_KB_EXPORT_FILES
HARD_WORDS = {"hard", "blocking", "blocker", "error", "fail", "failed", "conflicting", "unresolved"}
REF_KEYS = {
    "target_ref",
    "target_refs",
    "source_ref",
    "source_refs",
    "evidence_ref",
    "evidence_refs",
    "linked_relations",
    "linked_input_realization",
    "family_ref",
    "family_refs",
    "kernel_path_ref",
    "kernel_path_refs",
    "branch_ref",
    "branch_refs",
}


@dataclass
class ValidationIssue:
    code: str
    severity: str
    message: str
    path: str = ""
    target: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "severity": self.severity,
            "path": self.path,
            "target": self.target,
            "message": self.message,
        }


@dataclass
class ValidationReport:
    status: str = "pass"
    blocking_issues: list[ValidationIssue] = field(default_factory=list)
    warnings: list[ValidationIssue] = field(default_factory=list)
    info: list[ValidationIssue] = field(default_factory=list)

    def add(self, code: str, severity: str, message: str, path: str = "", target: str = "") -> None:
        issue = ValidationIssue(code, severity, message, path, target)
        if severity == "error":
            self.status = "fail"
            self.blocking_issues.append(issue)
        elif severity == "warning":
            if self.status == "pass":
                self.status = "warn"
            self.warnings.append(issue)
        else:
            self.info.append(issue)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "blocking_issues": [issue.to_dict() for issue in self.blocking_issues],
            "warnings": [issue.to_dict() for issue in self.warnings],
            "info": [issue.to_dict() for issue in self.info],
        }


def validate_intake(export_payload: dict[str, Any], final_validation: dict[str, Any]) -> ValidationReport:
    """Validate UO KB readiness for TG intake. Does not require UO contracts/testcase.yaml."""
    report = ValidationReport()
    files = _as_dict(export_payload.get("files"))
    context_slice = _as_dict(export_payload.get("context_slice"))

    for rel in REQUIRED_KB_EXPORT_FILES:
        if rel not in files:
            report.add(
                "MISSING_CANONICAL_FILE",
                "error",
                f"kb-export missing required layered file: {rel}",
                rel,
                rel,
            )

    # Soft signals: manifest / sqlite / integrity when present in files or via final_validation.
    if "manifest.yaml" not in files and not _as_dict(final_validation).get("manifest_ok"):
        report.add(
            "MANIFEST_MISSING",
            "warning",
            "manifest.yaml not present in export payload (filesystem intake may still load it)",
            "manifest.yaml",
        )

    quality_status = quality_status_from(files)
    if quality_status == "fail":
        report.add("QUALITY_FAIL", "error", "Understand quality status is fail", "quality.yaml", quality_status)
    elif not quality_status:
        report.add("QUALITY_STATUS_MISSING", "warning", "Unable to determine Understand quality status", "quality.yaml")

    if final_validation.get("status") == "fail":
        report.add("FINAL_VALIDATION_FAIL", "error", "Understand final validation failed", target="final_validation")
    elif final_validation.get("status") == "warn":
        report.add("FINAL_VALIDATION_WARN", "warning", "Understand final validation returned warnings", target="final_validation")

    source_hashes = _as_dict(final_validation.get("source_artifact_hashes"))
    if not source_hashes:
        artifact = _as_dict(files.get("checks/artifact_hashes.yaml"))
        source_hashes = _as_dict(artifact.get("hashes"))
    if not source_hashes:
        report.add(
            "SOURCE_HASHES_MISSING",
            "error",
            "Snapshot source artifact hashes are required",
            "checks/artifact_hashes.yaml",
            "hashes",
        )

    # Historical UO contract in payload: ignore (compat warning only).
    if files.get("contracts/testcase.yaml"):
        report.add(
            "LEGACY_UO_CONTRACT_IGNORED",
            "warning",
            "UO contracts/testcase.yaml is retired; TG owns .testcase-generator/<op>/contract/",
            "contracts/testcase.yaml",
        )

    known_ids = collect_known_ids({"files": files, "context_slice": context_slice})
    validate_stable_ids({"files": files, "context_slice": context_slice}, report)
    # Hard-ref checks apply to TG contract after tg-contract writes it — not UO intake.
    del known_ids
    validate_blocking_states(files, report)
    collect_warning_states(files, report)
    return report


def quality_status_from(files: dict[str, Any]) -> str:
    quality = _as_dict(files.get("quality.yaml"))
    candidates = [
        quality.get("status"),
        quality.get("decision"),
        quality.get("quality_status"),
    ]
    for candidate in candidates:
        text = str(candidate or "").strip().lower()
        if text:
            return text
    return ""


def collect_known_ids(value: Any) -> set[str]:
    ids: set[str] = set()

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            for key, child in node.items():
                if key in {"id", "stable_id", "family_id", "source_family", "stable_key"} and isinstance(child, str):
                    ids.add(child)
                visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)

    visit(value)
    return ids


def validate_stable_ids(value: Any, report: ValidationReport) -> None:
    for token, path in _iter_stable_tokens(value):
        if not is_stable_id(token):
            report.add("INVALID_STABLE_ID", "error", f"Invalid stable id format: {token}", path, token)


def validate_hard_refs(contract: dict[str, Any], known_ids: set[str], report: ValidationReport) -> None:
    for item, path in _iter_dicts(contract):
        if not _is_hard_item(item):
            continue
        for key in REF_KEYS:
            if key not in item:
                continue
            for ref in _as_list(item.get(key)):
                if not isinstance(ref, str):
                    continue
                if not (is_stable_id(ref) or LEGACY_ID_RE.match(ref)):
                    report.add("INVALID_HARD_REF_ID", "error", f"Hard reference is not a legal id: {ref}", f"{path}.{key}", ref)
                elif ref not in known_ids:
                    report.add("DANGLING_HARD_REF", "error", f"Hard reference cannot be resolved: {ref}", f"{path}.{key}", ref)


def validate_blocking_states(files: dict[str, Any], report: ValidationReport) -> None:
    for item, path in _iter_dicts(files):
        state = _state_text(item)
        if not state:
            continue
        if any(word in state for word in ("stale", "conflicting", "unresolved")) and _is_blocking_item(item):
            report.add("BLOCKING_UNDERSTAND_ISSUE", "error", f"Blocking stale/conflicting/unresolved issue: {state}", path, str(item.get("id") or ""))


def collect_warning_states(files: dict[str, Any], report: ValidationReport) -> None:
    for item, path in _iter_dicts(files):
        state = _state_text(item)
        if "warning" in state or "warn" in state:
            report.add("UNDERSTAND_WARNING", "warning", f"Understand warning carried into intake: {state}", path, str(item.get("id") or ""))
        if item.get("severity") == "warning":
            report.add("UNDERSTAND_WARNING", "warning", str(item.get("message") or item.get("reason") or "warning"), path, str(item.get("id") or ""))


def validate_contract_schema(contract: dict[str, Any], report: ValidationReport) -> None:
    for idx, item in enumerate(_iter_schema_items(contract.get("input_realization"))):
        if not isinstance(item, dict):
            report.add("INPUT_REALIZATION_SCHEMA", "error", "input_realization item must be a mapping", f"contracts/testcase.yaml.input_realization[{idx}]")
            continue
        if not item.get("id"):
            report.add("INPUT_REALIZATION_SCHEMA", "error", "input_realization item missing id", f"contracts/testcase.yaml.input_realization[{idx}]")

    for idx, item in enumerate(_kernel_branch_items(contract)):
        if not isinstance(item, dict):
            report.add("KERNEL_BRANCH_SCHEMA", "error", "kernel branch obligation must be a mapping", f"contracts/testcase.yaml.kernel_branch_obligations[{idx}]")
            continue
        branch_id = item.get("branch_id") or item.get("id") or item.get("target_ref")
        variants = _as_list(item.get("variants"))
        if variants and not branch_id:
            report.add("KERNEL_BRANCH_SCHEMA", "error", "kernel branch variants require branch id", f"contracts/testcase.yaml.kernel_branch_obligations[{idx}]")


def _kernel_branch_items(contract: dict[str, Any]) -> list[Any]:
    items: list[Any] = []
    items.extend(_iter_schema_items(contract.get("kernel_branch_obligations")))
    coverage = _as_dict(contract.get("coverage_obligations"))
    items.extend(_iter_schema_items(coverage.get("kernel_branches")))
    items.extend(_iter_schema_items(coverage.get("kernel_paths")))
    return items


def is_stable_id(value: str) -> bool:
    return bool(STABLE_ID_RE.match(value))


def _iter_stable_tokens(value: Any, path: str = "$") -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if isinstance(child, str):
                if key in {"id", "stable_id"} and (child.startswith(tuple(prefix + "_" for prefix in _stable_prefixes())) or ID_TOKEN_RE.search(child)):
                    found.append((child, child_path))
                for token in ID_TOKEN_RE.findall(child):
                    found.append((token, child_path))
            found.extend(_iter_stable_tokens(child, child_path))
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            found.extend(_iter_stable_tokens(child, f"{path}[{idx}]"))
    return found


def _stable_prefixes() -> tuple[str, ...]:
    return STABLE_PREFIXES


def _iter_schema_items(value: Any) -> list[Any]:
    if isinstance(value, dict):
        return [{**item, "id": str(key)} if isinstance(item, dict) and not item.get("id") else item for key, item in sorted(value.items())]
    return _as_list(value)


def _iter_dicts(value: Any, path: str = "$") -> list[tuple[dict[str, Any], str]]:
    found: list[tuple[dict[str, Any], str]] = []
    if isinstance(value, dict):
        found.append((value, path))
        for key, child in value.items():
            found.extend(_iter_dicts(child, f"{path}.{key}"))
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            found.extend(_iter_dicts(child, f"{path}[{idx}]"))
    return found


def _is_hard_item(item: dict[str, Any]) -> bool:
    text = " ".join(str(item.get(key) or "").lower() for key in ("priority", "severity", "requirement_level", "level", "obligation_level"))
    return any(word in text.split() for word in {"hard", "blocking", "blocker", "error", "fail"})


def _is_blocking_item(item: dict[str, Any]) -> bool:
    text = _state_text(item)
    explicit = " ".join(str(item.get(key) or "").lower() for key in ("priority", "severity", "level", "blocking"))
    return (
        any(word in explicit for word in HARD_WORDS)
        or item.get("blocking") is True
        or text in {"conflicting", "unresolved", "stale"}
    )


def _state_text(item: dict[str, Any]) -> str:
    return " ".join(str(item.get(key) or "").lower() for key in ("status", "state", "severity", "kind", "type", "reason"))


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value in (None, "", {}, []):
        return []
    return [value]
