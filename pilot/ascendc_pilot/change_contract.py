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

CHANGE_CONTRACT_SCHEMA = "tg-change-contract/v2"
CLONE_RECEIPT_SCHEMA = "tg-clone-receipt/v1"
PLAN_PR_CHANGE_REQUIRED = "PLAN_PR_CHANGE_REQUIRED"
PLAN_PR_HUNKS_REQUIRED = "PLAN_PR_HUNKS_REQUIRED"
PIN_HEAD_MISMATCH = "PIN_HEAD_MISMATCH"
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
            ["git", "-C", str(cwd), "rev-parse", spec],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
    except Exception:  # noqa: BLE001
        return ""
    if proc.returncode != 0:
        return ""
    return str(proc.stdout or "").strip()


def _git_workdir(start: Path) -> Path:
    """Nearest ancestor (inclusive) where ``git rev-parse HEAD`` works."""
    cur = Path(start).expanduser()
    try:
        cur = cur.resolve()
    except OSError:
        pass
    for _ in range(8):
        if _git_rev_parse(cur, "HEAD"):
            return cur
        if cur.parent == cur:
            break
        cur = cur.parent
    return Path(start)


def _git_diff_unified(cwd: Path, base_sha: str, head_sha: str) -> str:
    try:
        import subprocess

        proc = subprocess.run(
            ["git", "-C", str(cwd), "diff", "--no-ext-diff", "--unified=0", str(base_sha), str(head_sha)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
    except Exception:  # noqa: BLE001
        return ""
    if proc.returncode not in {0, 1}:
        return ""
    return str(proc.stdout or "")


def _git_merge_base(cwd: Path, a: str, b: str) -> str:
    try:
        import subprocess

        proc = subprocess.run(
            ["git", "-C", str(cwd), "merge-base", str(a), str(b)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
    except Exception:  # noqa: BLE001
        return ""
    if proc.returncode != 0:
        return ""
    return str(proc.stdout or "").strip()


def resolve_pin_base_sha(cwd: Path, head_sha: str, claimed_base: str = "") -> str:
    """Pick a two-dot base that yields hunks. Never three-dot; never invent HEAD==HEAD."""
    git_cwd = _git_workdir(cwd)
    head = str(head_sha or "").strip()
    if not head:
        return ""
    claimed = str(claimed_base or "").strip()
    tried: list[str] = []
    if claimed and claimed != head:
        tried.append(claimed)
        mb = _git_merge_base(git_cwd, claimed, head)
        if mb and mb != head and mb not in tried:
            tried.append(mb)
    for spec in (
        "origin/HEAD",
        "origin/master",
        "origin/main",
        "master",
        "main",
        f"{head}~1",
        f"{head}^",
    ):
        cand = _git_rev_parse(git_cwd, spec)
        if cand and cand != head and cand not in tried:
            tried.append(cand)
        mb = _git_merge_base(git_cwd, cand, head) if cand else ""
        if mb and mb != head and mb not in tried:
            tried.append(mb)
    for base in tried:
        if base and base != head and _git_diff_unified(git_cwd, base, head).strip():
            return base
    return ""


def _hunks_required(*, message_zh: str) -> dict[str, Any]:
    return {
        "ok": False,
        "error": PLAN_PR_HUNKS_REQUIRED,
        "reason_code": PLAN_PR_HUNKS_REQUIRED,
        "retryable": False,
        "failure_class": "format_transport",
        "ask": "human",
        "needs_human_decision": True,
        "ask_question": {
            "header": "PR 改动无法 pin",
            "question": (
                "clone 记录的 SHA 对不上可取出的 PR hunk。"
                "禁止手改 clone_receipt，禁止 git diff HEAD 当 PR 信号。"
                "请选择："
            ),
            "options": [
                {"id": "reclone", "label": "重新 clone 该 PR（pilot_run auto，force_new）"},
                {"id": "abort", "label": "中止本轮"},
            ],
        },
        "message_zh": message_zh,
    }


def capture_changed_hunks(
    *,
    worktree: Path,
    base_sha: str,
    head_sha: str,
) -> dict[str, Any]:
    """Two-sided hunks from an exact SHA pair. Never ``git diff HEAD`` / three-dot."""
    git_cwd = _git_workdir(worktree)
    actual = _git_rev_parse(git_cwd, "HEAD")
    head = str(head_sha or "").strip()
    if not head or actual != head:
        return {
            "ok": False,
            "error": PIN_HEAD_MISMATCH,
            "message_zh": (
                f"worktree HEAD={actual or '(missing)'} 与 pin head_sha={head_sha} 不一致"
            ),
        }
    base = str(base_sha or "").strip()
    if not base or base == head:
        base = resolve_pin_base_sha(git_cwd, head, base)
    if not base:
        return _hunks_required(message_zh="缺少可用的 base_sha，不能构造 changed_hunks")
    diff = _git_diff_unified(git_cwd, base, head)
    from code_engineering.change.capture import parse_unified_hunks

    hunks = parse_unified_hunks(diff)
    if not hunks:
        resolved = resolve_pin_base_sha(git_cwd, head, base)
        if resolved and resolved != base:
            base = resolved
            diff = _git_diff_unified(git_cwd, base, head)
            hunks = parse_unified_hunks(diff)
    if not hunks:
        return _hunks_required(
            message_zh="git diff <base> <head> 没有 hunk，不能 pin pr_regression"
        )
    return {"ok": True, "hunks": hunks, "base_sha": base, "head_sha": head}


def changed_hunks_of(contract: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(contract, dict):
        return []
    rows = contract.get("changed_hunks")
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


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
    worktree = str(worktree_head or root).strip()
    git_cwd = _git_workdir(Path(worktree) if worktree else root)
    head = str(head_sha or "").strip() or _git_rev_parse(git_cwd, "HEAD")
    base = str(base_sha or "").strip()
    if head and (not base or base == head):
        base = resolve_pin_base_sha(git_cwd, head, base)
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
    if kind == PR_REGRESSION:
        if not changed_files_of(doc) or not changed_hunks_of(doc):
            return None
        if str(doc.get("schema") or "") != CHANGE_CONTRACT_SCHEMA:
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
        worktree = Path(str((receipt or {}).get("worktree_head") or root))
        base_sha = str((receipt or {}).get("base_sha") or "").strip()
        head_sha = str((receipt or {}).get("head_sha") or "").strip()
        captured = capture_changed_hunks(
            worktree=worktree, base_sha=base_sha, head_sha=head_sha
        )
        if not captured.get("ok"):
            fail = {
                "ok": False,
                "error": str(captured.get("error") or PLAN_PR_HUNKS_REQUIRED),
                "message_zh": str(captured.get("message_zh") or "无法构造 changed_hunks"),
            }
            for key in (
                "reason_code",
                "retryable",
                "failure_class",
                "ask",
                "needs_human_decision",
                "ask_question",
            ):
                if key in captured:
                    fail[key] = captured[key]
            return fail
        base_sha = str(captured.get("base_sha") or base_sha).strip()
        head_sha = str(captured.get("head_sha") or head_sha).strip()
        if (
            base_sha != str((receipt or {}).get("base_sha") or "").strip()
            or head_sha != str((receipt or {}).get("head_sha") or "").strip()
        ):
            write_clone_receipt(
                root,
                source=(receipt or {}).get("source") if isinstance((receipt or {}).get("source"), dict) else {},
                changed_files=files,
                base_sha=base_sha,
                head_sha=head_sha,
                worktree_head=str(worktree),
            )
        doc = {
            "schema": CHANGE_CONTRACT_SCHEMA,
            "kind": PR_REGRESSION,
            "changed_files": files,
            "changed_hunks": captured.get("hunks") or [],
            "base_sha": base_sha,
            "head_sha": head_sha,
            "enumerate": "",
            "consumers": [str(x) for x in (consumers or ["tg-plan"]) if str(x).strip()],
            "pinned_at": _now(),
        }
    elif kind_s == IMPLEMENTATION_COVERAGE:
        doc = {
            "schema": CHANGE_CONTRACT_SCHEMA,
            "kind": IMPLEMENTATION_COVERAGE,
            "changed_files": [],
            "changed_hunks": [],
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


def verify_pinned_head(project_root: Path | str, contract: dict[str, Any] | None) -> dict[str, Any] | None:
    """Fail closed when the worktree is not the pinned head."""
    if not isinstance(contract, dict) or str(contract.get("kind") or "") != PR_REGRESSION:
        return None
    head = str(contract.get("head_sha") or "").strip()
    git_cwd = _git_workdir(Path(project_root))
    actual = _git_rev_parse(git_cwd, "HEAD")
    if not head or actual != head:
        return {
            "ok": False,
            "engine": "plan_precheck",
            "error": PIN_HEAD_MISMATCH,
            "reason_code": PIN_HEAD_MISMATCH,
            "retryable": True,
            "failure_class": "format_transport",
            "ask": "primary",
            "message_zh": (
                f"worktree HEAD={actual or '(missing)'} 与 pin head_sha={head} 不一致"
            ),
        }
    return None


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
    if contract and changed_files_of(contract) and changed_hunks_of(contract):
        return None
    receipt = load_clone_receipt(project_root)
    if receipt and _is_pr_kind(_source_kind_of((receipt or {}).get("source"))):
        pinned = pin_facts(project_root)
        if pinned.get("ok"):
            return None
        fail = {
            "ok": False,
            "engine": "plan_precheck",
            "error": str(pinned.get("error") or PLAN_PR_HUNKS_REQUIRED),
            "reason_code": str(pinned.get("reason_code") or pinned.get("error") or PLAN_PR_HUNKS_REQUIRED),
            "retryable": bool(pinned.get("retryable")),
            "failure_class": str(pinned.get("failure_class") or "format_transport"),
            "ask": str(pinned.get("ask") or "human"),
            "message_zh": str(
                pinned.get("message_zh")
                or "PR 针对性 plan 无法从 clone_receipt promote change_contract。"
            ),
        }
        if pinned.get("needs_human_decision"):
            fail["needs_human_decision"] = True
        if isinstance(pinned.get("ask_question"), dict):
            fail["ask_question"] = pinned["ask_question"]
        return fail
    return {
        "ok": False,
        "engine": "plan_precheck",
        "error": PLAN_PR_CHANGE_REQUIRED,
        "reason_code": PLAN_PR_CHANGE_REQUIRED,
        "retryable": True,
        "failure_class": "format_transport",
        "ask": "primary",
        "message_zh": (
            "PR 针对性 plan 需要 clone_receipt（含 changed_files）。"
            "缺 clone 不得进入 plan_ingest；不要 git diff HEAD 冒充 PR。"
        ),
    }
