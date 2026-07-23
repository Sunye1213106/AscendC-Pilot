"""Workflow registry — authoritative phase / gate / permission map."""

from __future__ import annotations

from typing import Any

WORKFLOWS: dict[str, dict[str, Any]] = {
    "uo-init": {
        "slash": "/uo-init",
        "engine": "uo",
        "phases": ["prepare", "phase0", "extract", "resolve", "export", "review"],
        "agents": [
            "uo-semantic-resolve",
            "uo-key-resolve",
            "uo-confidence-review",
            "uo-kb-review",
        ],
        "gates": [
            "phase0_receipt",
            "extract_plan_subagent",
            "key_triage_required",
            "key_resolve_receipt",
            "empty_only_producer",
            "confidence_gate",
            "key_report_quality",
            "confidence_closed_high",
            "confidence_reason_review",
            "integrity",
            "kb_review",
        ],
        # Gates that must pass before leaving the listed phase
        "phase_gates": {
            "phase0": ["phase0_receipt"],
            "extract": ["extract_plan_subagent"],
            "resolve": [
                "key_triage_required",
                "key_resolve_receipt",
                "empty_only_producer",
                "confidence_gate",
                "key_report_quality",
                "confidence_closed_high",
                "confidence_reason_review",
            ],
            "export": ["integrity"],
            "review": ["kb_review"],
        },
        "write_roots": ["uo", "runs", "state", "context"],
        "extensions": False,
    },
    "uo-update": {
        "slash": "/uo-update",
        "engine": "uo",
        "phases": ["detect", "plan", "apply", "resolve", "export", "diff"],
        "agents": [
            "uo-semantic-resolve",
            "uo-key-resolve",
            "uo-confidence-review",
            "uo-kb-review",
        ],
        "gates": [
            "key_triage_required",
            "key_resolve_receipt",
            "empty_only_producer",
            "confidence_gate",
            "confidence_reason_review",
            "integrity",
        ],
        "phase_gates": {
            "resolve": [
                "key_triage_required",
                "key_resolve_receipt",
                "confidence_gate",
                "confidence_reason_review",
            ],
            "export": ["integrity"],
        },
        "write_roots": ["uo", "runs", "state", "context"],
    },
    "uo-query": {
        "slash": "/uo-query",
        "engine": "uo",
        "phases": ["route", "lookup", "answer"],
        "agents": ["uo-key-resolve"],
        "gates": ["kb_ready"],
        "write_roots": ["runs", "context", "memory"],
        "read_only_uo": False,
    },
    "uo-code-review": {
        "slash": "/uo-code-review",
        "engine": "uo",
        "phases": ["context", "bug", "functional", "summary"],
        "agents": ["uo-code-reviewer"],
        "gates": ["kb_ready", "context_pack"],
        "write_roots": ["uo/review", "runs", "context"],
    },
    "tg-init": {
        "slash": "/tg-init",
        "engine": "tg",
        "phases": ["intake", "bind", "confirm"],
        "agents": ["tg-csv-contract", "tg-init-audit"],
        "gates": ["uo_ready", "kb_fingerprint"],
        "write_roots": ["tg", "runs", "state", "context"],
        "read_only_uo": True,
    },
    "tg-plan": {
        "slash": "/tg-plan",
        "engine": "tg",
        "phases": ["scope", "obligations", "approve"],
        "agents": [],
        "gates": ["tg_init_confirmed"],
        "write_roots": ["tg", "runs", "state"],
        "read_only_uo": True,
    },
    "tg-solve": {
        "slash": "/tg-solve",
        "engine": "tg",
        "phases": ["solve", "export"],
        "agents": [],
        "gates": ["plan_approved"],
        "write_roots": ["tg", "runs", "state"],
        "read_only_uo": True,
    },
    # Reserved extension seams (not implemented)
    "code-edit": {"slash": None, "engine": "ext", "phases": [], "gates": [], "reserved": True},
    "git-ops": {"slash": None, "engine": "ext", "phases": [], "gates": [], "reserved": True},
    "build": {"slash": None, "engine": "ext", "phases": [], "gates": [], "reserved": True},
    "test-run": {"slash": None, "engine": "ext", "phases": [], "gates": [], "reserved": True},
    "perf-analyze": {"slash": None, "engine": "ext", "phases": [], "gates": [], "reserved": True},
}


def get_workflow(workflow_id: str) -> dict[str, Any]:
    if workflow_id not in WORKFLOWS:
        raise KeyError(f"Unknown workflow: {workflow_id}")
    return dict(WORKFLOWS[workflow_id])


def list_user_workflows() -> list[str]:
    return [wid for wid, meta in WORKFLOWS.items() if meta.get("slash") and not meta.get("reserved")]
