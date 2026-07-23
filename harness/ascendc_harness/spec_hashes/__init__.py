"""Four Spec Hash kinds — keep Chinese UI copy and Agent prompt wording out of kb_schema_hash."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ascendc_harness.workflows.specs import WORKFLOWS
from ascendc_harness.workflows import get_workflow

# Optional: pin schema files that affect KB layout / IR surfaces
_KB_SCHEMA_GLOBS = (
    "engines/uo/spec/*.yaml",
    "engines/uo/uo/_operator/artifacts.py",
)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_text(text: str) -> str:
    return _sha256_bytes(text.encode("utf-8"))


def _stable_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str)


def workflow_spec_hash(workflow_id: str | None = None) -> str:
    """Phases / transitions / gates / retry — not label_zh text."""
    if workflow_id:
        meta = get_workflow(workflow_id)
        payload = {
            "id": workflow_id,
            "entry_state": meta.get("entry_state"),
            "states": [s.get("id") for s in (meta.get("states") or []) if isinstance(s, dict)],
            "transitions": meta.get("transitions"),
            "phase_gates": meta.get("phase_gates"),
            "complete_gates": meta.get("complete_gates"),
            "retry_budget": meta.get("retry_budget"),
            "actions": [
                {
                    "id": a.get("id"),
                    "checker_required": a.get("checker_required"),
                    "referee_required": a.get("referee_required"),
                    "gates": a.get("gates"),
                    "actors": a.get("actors"),
                }
                for a in (meta.get("actions") or [])
                if isinstance(a, dict)
            ],
        }
        return _sha256_text(_stable_json(payload))
    # All workflows
    return _sha256_text(
        _stable_json({wid: workflow_spec_hash(wid) for wid in sorted(WORKFLOWS.keys())})
    )


def agent_contract_hash(repo_root: Path | None = None) -> str:
    """Agent writable surfaces / referee output schemas (file presence + frontmatter-ish)."""
    root = repo_root or Path(__file__).resolve().parents[2]
    parts: list[str] = []
    for rel in (
        "engines/uo/spec/ownership.yaml",
        "agents/uo-confidence-review.md",
        "agents/uo-key-resolve.md",
        "agents/references/init-audit-schema.md",
        "agents/references/csv-contract-schema.md",
    ):
        path = root / rel
        if path.is_file():
            parts.append(f"{rel}:{_sha256_bytes(path.read_bytes())}")
    return _sha256_text("\n".join(parts) if parts else "empty-agent-contract")


def tg_contract_hash(repo_root: Path | None = None) -> str:
    root = repo_root or Path(__file__).resolve().parents[2]
    parts: list[str] = []
    for rel in (
        "engines/tg/testcase_agent/contract.py",
        "engines/tg/testcase_agent/realization_contract.py",
        "engines/tg/testcase_agent/resolve_policy.py",
        "agents/references/csv-contract-schema.md",
    ):
        path = root / rel
        if path.is_file():
            parts.append(f"{rel}:{_sha256_bytes(path.read_bytes())}")
    return _sha256_text("\n".join(parts) if parts else "empty-tg-contract")


def kb_schema_hash(repo_root: Path | None = None) -> str:
    """KB layout / IR schema / ownership product surfaces — NOT Chinese labels or Agent prompts."""
    root = repo_root or Path(__file__).resolve().parents[2]
    parts: list[str] = []
    ownership = root / "engines" / "uo" / "spec" / "ownership.yaml"
    if ownership.is_file():
        parts.append(f"ownership:{_sha256_bytes(ownership.read_bytes())}")
    for rel in (
        "engines/uo/spec/bundle.yaml",
        "engines/uo/uo/_operator/artifacts.py",
    ):
        path = root / rel
        if path.is_file():
            parts.append(f"{rel}:{_sha256_bytes(path.read_bytes())}")
    # IR schema docs if present
    schema_dir = root / "engines" / "uo" / "spec"
    if schema_dir.is_dir():
        for path in sorted(schema_dir.glob("*.yaml")):
            if path.name == "ownership.yaml":
                continue
            parts.append(f"spec/{path.name}:{_sha256_bytes(path.read_bytes())}")
    return _sha256_text("\n".join(parts) if parts else "empty-kb-schema")


def all_spec_hashes(repo_root: Path | None = None, *, workflow_id: str | None = None) -> dict[str, str]:
    root = repo_root or Path(__file__).resolve().parents[2]
    return {
        "kb_schema_hash": kb_schema_hash(root),
        "workflow_spec_hash": workflow_spec_hash(workflow_id),
        "agent_contract_hash": agent_contract_hash(root),
        "tg_contract_hash": tg_contract_hash(root),
    }
