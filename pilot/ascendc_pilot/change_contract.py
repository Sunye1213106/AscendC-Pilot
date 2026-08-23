"""Primary-owned operator pin. Clone receipts are candidates; this file is SSOT."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

CHANGE_CONTRACT_SCHEMA = "tg-change-contract/v1"
PLAN_PR_CHANGE_REQUIRED = "PLAN_PR_CHANGE_REQUIRED"
PR_REGRESSION = "pr_regression"
IMPLEMENTATION_COVERAGE = "implementation_coverage"
_KINDS = frozenset({PR_REGRESSION, IMPLEMENTATION_COVERAGE})


def _now() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def change_contract_path(project_root: Path | str) -> Path:
    from ascendc_pilot.user_goal_core import control_root

    return control_root(project_root) / "change_contract.yaml"


def load_change_contract(project_root: Path | str) -> dict[str, Any] | None:
    path = change_contract_path(project_root)
    if not path.is_file():
        return None
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        return None
    return doc if isinstance(doc, dict) else None


def pin_facts(
    project_root: Path | str,
    *,
    key: str = "change_contract",
    kind: str = "",
    changed_files: list[str] | None = None,
    base_sha: str = "",
    head_sha: str = "",
    enumerate: str = "",
    consumers: list[str] | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Write operator control pin. Primary calls this; clone must not."""
    del key
    root = Path(project_root).expanduser().resolve()
    body = dict(payload or {})
    kind_s = str(kind or body.get("kind") or "").strip()
    files = [
        str(x).strip()
        for x in (changed_files if changed_files is not None else body.get("changed_files") or [])
        if str(x).strip()
    ]
    if kind_s and kind_s not in _KINDS:
        return {
            "ok": False,
            "error": "PIN_KIND_INVALID",
            "message_zh": f"kind 只能是 {sorted(_KINDS)}，收到 {kind_s!r}",
        }
    doc = {
        "schema": CHANGE_CONTRACT_SCHEMA,
        "kind": kind_s,
        "changed_files": files,
        "base_sha": str(base_sha or body.get("base_sha") or "").strip(),
        "head_sha": str(head_sha or body.get("head_sha") or "").strip(),
        "enumerate": str(enumerate or body.get("enumerate") or "").strip(),
        "consumers": [str(x) for x in (consumers or body.get("consumers") or ["tg-plan"]) if str(x).strip()],
        "pinned_at": _now(),
    }
    path = change_contract_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    try:
        from ascendc_pilot.user_goal_core import load_user_goal, write_user_goal

        goal = load_user_goal(root)
        if isinstance(goal, dict):
            arts = dict(goal.get("artifacts") or {})
            arts["changeset"] = {
                "changed_files": files,
                "base_sha": doc["base_sha"],
                "head_sha": doc["head_sha"],
            }
            goal["artifacts"] = arts
            write_user_goal(root, goal)
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, "path": path.as_posix(), "contract": doc}


def changed_files_of(contract: dict[str, Any] | None) -> list[str]:
    if not isinstance(contract, dict):
        return []
    return [str(x).strip() for x in (contract.get("changed_files") or []) if str(x).strip()]


def _source_kind(project_root: Path | str) -> str:
    try:
        from ascendc_pilot.user_goal import load_user_goal

        goal = load_user_goal(project_root) or {}
    except Exception:  # noqa: BLE001
        return ""
    source = goal.get("source") if isinstance((goal or {}).get("source"), dict) else {}
    return str(source.get("kind") or "").strip().lower()


def is_pr_regression_intent(project_root: Path | str) -> bool:
    """PR-targeted planning is source.kind=pull_request, not user_goal.kind.

    ``user_goal.kind`` is the deliverable label (``generate_change_tests``).
    ``change_contract.kind`` is the planning axis after pin.
    """
    contract = load_change_contract(project_root) or {}
    pinned = str(contract.get("kind") or "").strip()
    if pinned == IMPLEMENTATION_COVERAGE:
        return False
    if pinned == PR_REGRESSION:
        return True
    return _source_kind(project_root) in {"pull_request", "pr"}


def pr_change_gate(project_root: Path | str) -> dict[str, Any] | None:
    """Fail closed when PR-targeted planning has no pinned changed_files."""
    if not is_pr_regression_intent(project_root):
        return None
    contract = load_change_contract(project_root)
    if not contract or not changed_files_of(contract):
        return {
            "ok": False,
            "engine": "plan_precheck",
            "error": PLAN_PR_CHANGE_REQUIRED,
            "reason_code": PLAN_PR_CHANGE_REQUIRED,
            "retryable": True,
            "failure_class": "format_transport",
            "ask": "primary",
            "message_zh": (
                "PR 针对性 plan 需要先 pin_facts(change_contract.changed_files)。"
                "clone 回执不是 SSOT；缺 pin 不得当 implementation_coverage。"
            ),
        }
    return None
