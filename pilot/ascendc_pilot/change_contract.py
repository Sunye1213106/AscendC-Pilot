"""Primary-owned operator pin.

Candidate facts live only in ``clone_receipt.yaml``. This module's
``change_contract.yaml`` is the sole SSOT, written only by ``pin-facts``
promote. Clone must not write the contract. Host run state is not a pin.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

CHANGE_CONTRACT_SCHEMA = "tg-change-contract/v1"
CLONE_RECEIPT_SCHEMA = "tg-clone-receipt/v1"
PLAN_PR_CHANGE_REQUIRED = "PLAN_PR_CHANGE_REQUIRED"
SOURCE_KIND_CONFLICT = "SOURCE_KIND_CONFLICT"
PR_REGRESSION = "pr_regression"
IMPLEMENTATION_COVERAGE = "implementation_coverage"
_KINDS = frozenset({PR_REGRESSION, IMPLEMENTATION_COVERAGE})
_PR_KINDS = frozenset({"pull_request", "pr"})


def _now() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def change_contract_path(project_root: Path | str) -> Path:
    from ascendc_pilot.user_goal_core import control_root

    return control_root(project_root) / "change_contract.yaml"


def clone_receipt_path(project_root: Path | str) -> Path:
    from ascendc_pilot.user_goal_core import control_root

    return control_root(project_root) / "clone_receipt.yaml"


def _git_rev_parse(cwd: Path, spec: str = "HEAD") -> str:
    try:
        import subprocess

        proc = subprocess.run(
            ["git", "rev-parse", spec],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except Exception:  # noqa: BLE001
        return ""
    if int(getattr(proc, "returncode", 1) or 1) != 0:
        return ""
    return str(getattr(proc, "stdout", "") or "").strip()


def _as_files(raw: Any) -> list[str]:
    return [str(x).strip() for x in (raw or []) if str(x).strip()]


def _source_kind_of(source: Any) -> str:
    if not isinstance(source, dict):
        return ""
    return str(source.get("kind") or "").strip().lower()


def _is_pr_kind(kind: str) -> bool:
    return str(kind or "").strip().lower() in _PR_KINDS


def load_clone_receipt(project_root: Path | str) -> dict[str, Any] | None:
    path = clone_receipt_path(project_root)
    if not path.is_file():
        return None
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        return None
    return doc if isinstance(doc, dict) else None


def write_clone_receipt(
    project_root: Path | str,
    *,
    source: dict[str, Any] | None = None,
    changed_files: list[str] | None = None,
    base_sha: str = "",
    head_sha: str = "",
    worktree_head: str = "",
) -> Path:
    """Write operator clone candidate. Failure must propagate; do not swallow."""
    root = Path(project_root).expanduser().resolve()
    src = dict(source or {})
    files = _as_files(changed_files)
    head = str(head_sha or "").strip() or _git_rev_parse(root, "HEAD")
    base = str(base_sha or "").strip() or _git_rev_parse(root, "HEAD")
    worktree = str(worktree_head or root).strip()
    doc = {
        "schema": CLONE_RECEIPT_SCHEMA,
        "source": {
            "kind": str(src.get("kind") or "").strip(),
            "url": str(src.get("url") or src.get("ref") or "").strip(),
        },
        "changed_files": files,
        "base_sha": base,
        "head_sha": head,
        "worktree_head": worktree,
        "written_at": _now(),
    }
    path = clone_receipt_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def load_change_contract(project_root: Path | str) -> dict[str, Any] | None:
    path = change_contract_path(project_root)
    if not path.is_file():
        return None
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(doc, dict):
        return None
    kind = str(doc.get("kind") or "").strip()
    if kind not in _KINDS:
        return None
    if kind == PR_REGRESSION and not changed_files_of(doc):
        return None
    return doc


def pin_facts(
    project_root: Path | str,
    *,
    kind: str = "",
    enumerate: str = "",
    consumers: list[str] | None = None,
) -> dict[str, Any]:
    """Promote clone_receipt → change_contract, or pin local coverage without a PR receipt."""
    root = Path(project_root).expanduser().resolve()
    kind_s = str(kind or "").strip()
    enum_s = str(enumerate or "").strip()
    if kind_s and kind_s not in _KINDS:
        return {
            "ok": False,
            "error": "PIN_KIND_INVALID",
            "message_zh": f"kind 只能是 {sorted(_KINDS)}，收到 {kind_s!r}",
        }
    receipt = load_clone_receipt(root)
    pr_receipt = bool(receipt) and _is_pr_kind(_source_kind_of((receipt or {}).get("source")))
    if pr_receipt:
        if kind_s == IMPLEMENTATION_COVERAGE or enum_s == "legal_keys":
            return {
                "ok": False,
                "error": "PIN_PR_SOURCE_FORBIDDEN",
                "message_zh": "已有 PR clone_receipt 时禁止 implementation_coverage / legal_keys",
            }
        files = _as_files((receipt or {}).get("changed_files"))
        if not files:
            return {
                "ok": False,
                "error": "PIN_FACTS_MISSING",
                "message_zh": "clone_receipt.changed_files 为空，不能 promote",
            }
        doc = {
            "schema": CHANGE_CONTRACT_SCHEMA,
            "kind": PR_REGRESSION,
            "changed_files": files,
            "base_sha": str((receipt or {}).get("base_sha") or "").strip(),
            "head_sha": str((receipt or {}).get("head_sha") or "").strip(),
            "enumerate": "",
            "consumers": [str(x) for x in (consumers or ["tg-plan"]) if str(x).strip()],
            "pinned_at": _now(),
        }
    elif kind_s == IMPLEMENTATION_COVERAGE:
        doc = {
            "schema": CHANGE_CONTRACT_SCHEMA,
            "kind": IMPLEMENTATION_COVERAGE,
            "changed_files": [],
            "base_sha": "",
            "head_sha": "",
            "enumerate": enum_s,
            "consumers": [str(x) for x in (consumers or ["tg-plan"]) if str(x).strip()],
            "pinned_at": _now(),
        }
    else:
        return {
            "ok": False,
            "error": "PIN_FACTS_MISSING",
            "message_zh": "没有 clone_receipt，不能 pin PR 改动；本地覆盖请显式 kind=implementation_coverage",
        }
    path = change_contract_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return {"ok": True, "path": path.as_posix(), "contract": doc}


def changed_files_of(contract: dict[str, Any] | None) -> list[str]:
    if not isinstance(contract, dict):
        return []
    return _as_files(contract.get("changed_files"))


def _user_goal_source_kind(project_root: Path | str) -> str:
    try:
        from ascendc_pilot.user_goal import load_user_goal

        goal = load_user_goal(project_root) or {}
    except Exception:  # noqa: BLE001
        return ""
    source = goal.get("source") if isinstance((goal or {}).get("source"), dict) else {}
    return _source_kind_of(source)


def is_pr_source(project_root: Path | str) -> dict[str, Any]:
    """PR identity from clone_receipt.source, else user_goal.source. Never from contract.kind."""
    receipt = load_clone_receipt(project_root)
    receipt_kind = _source_kind_of((receipt or {}).get("source")) if receipt else ""
    goal_kind = _user_goal_source_kind(project_root)
    if receipt is not None and goal_kind:
        if _is_pr_kind(receipt_kind) != _is_pr_kind(goal_kind):
            return {
                "ok": False,
                "is_pr": False,
                "error": SOURCE_KIND_CONFLICT,
                "message_zh": "clone_receipt.source 与 user_goal.source 的 PR 身份不一致",
            }
        return {"ok": True, "is_pr": _is_pr_kind(receipt_kind)}
    if receipt is not None:
        return {"ok": True, "is_pr": _is_pr_kind(receipt_kind)}
    return {"ok": True, "is_pr": _is_pr_kind(goal_kind)}


def is_pr_regression_intent(project_root: Path | str) -> bool:
    ident = is_pr_source(project_root)
    return bool(ident.get("ok") and ident.get("is_pr"))


def allow_legal_keys(project_root: Path | str) -> bool:
    ident = is_pr_source(project_root)
    if ident.get("is_pr") or not ident.get("ok"):
        return False
    contract = load_change_contract(project_root) or {}
    return str(contract.get("enumerate") or "").strip() == "legal_keys"


def pr_change_gate(project_root: Path | str) -> dict[str, Any] | None:
    """Fail closed when PR-targeted planning has no pinned changed_files."""
    ident = is_pr_source(project_root)
    if not ident.get("ok"):
        return {
            "ok": False,
            "engine": "plan_precheck",
            "error": str(ident.get("error") or SOURCE_KIND_CONFLICT),
            "reason_code": str(ident.get("error") or SOURCE_KIND_CONFLICT),
            "retryable": True,
            "failure_class": "format_transport",
            "ask": "primary",
            "message_zh": str(ident.get("message_zh") or "PR 身份冲突"),
        }
    if not ident.get("is_pr"):
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
                "PR 针对性 plan 需要先 pin-facts --project <算子>，从 clone_receipt promote。"
                "缺 pin 不得进入 plan_ingest。"
            ),
        }
    return None
