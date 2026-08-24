# -*- coding: utf-8 -*-
"""Human Interaction Broker: request → Host UI → signed decision receipt.

ACP emits ``human_interaction_request`` with a run-bound ``request_id`` nonce.
The Host (OpenCode plugin) must surface the question UI and call
``acp answer``. Finalize / resume / recovery commands consume the receipt;
``--finalize`` alone is never an affirmative human signal.
"""

from __future__ import annotations

import hashlib
import re
import secrets
import time
from pathlib import Path
from typing import Any

import yaml

from ascendc_pilot.paths import AGENT_DIR
from ascendc_pilot.state import load_state


KIND_HUMAN_REQUIRED = "human_required"
KIND_PRIMARY_CONFIRM = "primary_confirm"
KIND_PRIMARY_APPROVE = "primary_approve"
KIND_RESUME = "resume"
KIND_INTAKE = "intake"

_HARNESS_DEFAULT_MARKERS = frozenset(
    {
        "no_repo_uo_query",
        "default_input",
        "none",
        "null",
        "-",
        "__default_input__",
    }
)
_PATH_CANDIDATE = re.compile(
    r"(?:[A-Za-z]:[\\/][^\s\"'<>|*?\n，。；;！!？?]+"
    r"|/(?:[^\s\"'<>|*?\n，。；;！!？?]+))",
)
_CJK_TAIL = re.compile(r"[\u4e00-\u9fff].*$")
_IN_TREE_TEST_DIR_NAMES = frozenset({"tests", "test", "ut", "unittest", "unit_test"})
_HARNESS_SKIP_MARKERS = frozenset({"have_repo", "stop", "custom"})


def _dump(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _control_root(project_root: Path) -> Path:
    """Arch-neutral control plane root (safe before --architecture is known)."""
    return Path(project_root).expanduser().resolve() / AGENT_DIR / "control"


def pending_path(project_root: Path) -> Path:
    return _control_root(project_root) / "pending_interaction.yaml"


def _control_plane_writable(project_root: Path) -> bool:
    """True when writing control files will not create `.ascendc-pilot` on an empty Host cwd."""
    path = Path(project_root)
    if (path / "op_host").is_dir() or (path / "op_kernel").is_dir():
        return True
    return (path / AGENT_DIR).exists()


def _find_pending_elsewhere(project_root: Path) -> str:
    """Best-effort locate pending_interaction.yaml when --project is the Host cwd."""
    root = Path(project_root).expanduser()
    try:
        root = root.resolve()
    except OSError:
        pass
    seen: list[Path] = []
    try:
        from ascendc_pilot.intake import read_last_project_cache

        cached = read_last_project_cache()
        if cached is not None:
            seen.append(Path(cached))
    except Exception:  # noqa: BLE001
        pass
    for base in (root, *root.parents):
        pr_home = base / ".ascendc-pr"
        if not pr_home.is_dir():
            continue
        try:
            hits = list(pr_home.rglob("pending_interaction.yaml"))
        except OSError:
            hits = []
        for hit in hits[:8]:
            seen.append(hit.parent.parent.parent if hit.parent.name == "control" else hit.parent)
        break
    for candidate in seen:
        path = pending_path(candidate)
        if path.is_file() and pending_is_open(_load(path)):
            return str(path)
    return str(pending_path(root))


def decisions_dir(project_root: Path) -> Path:
    return _control_root(project_root) / "decisions"


def load_pending(project_root: Path) -> dict[str, Any]:
    return _load(pending_path(Path(project_root).expanduser().resolve()))


def pending_is_open(pending: dict[str, Any] | None) -> bool:
    """True when a pending AskQuestion is still waiting (not answered/superseded)."""
    if not pending:
        return False
    if not str(pending.get("request_id") or "").strip():
        return False
    return str(pending.get("status") or "pending").strip().lower() == "pending"


def _pending_matches_ask(
    pending: dict[str, Any] | None,
    *,
    kind: str,
    decision: str,
    action_id: str = "",
) -> bool:
    if not pending:
        return False
    if str(pending.get("kind") or "") != kind:
        return False
    if str(pending.get("decision_kind") or "") != decision:
        return False
    got = str(pending.get("action_id") or "")
    if action_id and got and got != action_id:
        return False
    return True


def pending_answered_unconsumed(
    project_root: Path,
    pending: dict[str, Any] | None = None,
) -> bool:
    """True when the user answered but materialize has not consumed the receipt."""
    row = pending if pending is not None else _load(pending_path(Path(project_root)))
    if not row:
        return False
    if str(row.get("status") or "").strip().lower() != "answered":
        return False
    request_id = str(row.get("request_id") or "").strip()
    if not request_id:
        return False
    receipt = _load(decisions_dir(Path(project_root)) / f"{request_id}.yaml")
    return bool(receipt) and not receipt.get("consumed")


def _reuse_interaction_envelope(
    existing: dict[str, Any],
    *,
    kind: str,
    decision: str,
    action_id: str,
    rid: str,
    values: list[str],
    ask_question: dict[str, Any],
    request_id_fallback: str,
) -> dict[str, Any]:
    return {
        "request_id": str(existing.get("request_id") or request_id_fallback),
        "run_id": str(existing.get("run_id") or rid),
        "workflow_id": str(existing.get("workflow_id") or ""),
        "action_id": str(existing.get("action_id") or action_id),
        "kind": kind,
        "decision_kind": decision,
        "allowed_values": list(existing.get("allowed_values") or values),
        "ask_question": existing.get("ask_question") or ask_question,
    }


def pending_is_intake(pending: dict[str, Any] | None) -> bool:
    """True when pending is pre-start intake (architecture / project / uo product)."""
    if not pending_is_open(pending):
        return False
    kind = str(pending.get("kind") or "").strip().lower()
    dkind = str(pending.get("decision_kind") or "").strip().lower()
    return kind == KIND_INTAKE or dkind in {
        "architecture",
        "intake",
        "project",
        "uo_product",
    }


def pending_field(pending: dict[str, Any] | None) -> str:
    if not pending:
        return ""
    ask = pending.get("ask_question") if isinstance(pending.get("ask_question"), dict) else {}
    return str(ask.get("field") or pending.get("decision_kind") or "").strip()


def pending_allows_free_path(pending: dict[str, Any] | None) -> bool:
    if not pending:
        return False
    ask = pending.get("ask_question") if isinstance(pending.get("ask_question"), dict) else {}
    field = pending_field(pending)
    return bool(ask.get("allow_free_text")) and field == "test_script_root"


def extract_existing_directory(text: str) -> str:
    """Return an existing absolute directory mentioned in free text, else empty."""
    raw = str(text or "").strip()
    if not raw:
        return ""
    try:
        direct = Path(raw).expanduser()
        if direct.is_dir():
            return str(direct.resolve())
    except OSError:
        pass
    seen: list[str] = []
    for match in _PATH_CANDIDATE.finditer(raw):
        cand = _CJK_TAIL.sub("", match.group(0))
        cand = cand.rstrip("\\/").rstrip("。，、；;）)］]」'\"`")
        if cand and cand not in seen:
            seen.append(cand)
    for cand in seen:
        try:
            path = Path(cand).expanduser()
            if path.is_dir():
                return str(path.resolve())
        except OSError:
            continue
    return ""


def _git_workspace():
    import sys

    ws = Path(__file__).resolve().parents[2] / "engines" / "workspace"
    if str(ws) not in sys.path:
        sys.path.insert(0, str(ws))
    import git_workspace as gw  # type: ignore[import-not-found]

    return gw


def extract_harness_git_url(text: str) -> str:
    """First allowlisted https repo URL in free text (not a PR)."""
    try:
        gw = _git_workspace()
    except Exception:  # noqa: BLE001
        return ""
    return str(gw.extract_git_repo_url(text) or "").strip()


def _looks_like_fs_path(text: str) -> bool:
    raw = str(text or "").strip()
    if not raw:
        return False
    if _PATH_CANDIDATE.search(raw):
        return True
    try:
        path = Path(raw).expanduser()
    except OSError:
        return False
    return path.is_absolute() or ("/" in raw or "\\" in raw)


def is_in_tree_operator_tests(project_root: Path, path: str) -> bool:
    """True when ``path`` is the operator's own tests/test/ut tree, not an external harness."""
    raw = str(path or "").strip()
    if not raw or raw.lower() in _HARNESS_DEFAULT_MARKERS or raw.lower() in _HARNESS_SKIP_MARKERS:
        return False
    try:
        child = Path(raw).expanduser().resolve()
        parent = Path(project_root).expanduser().resolve()
        rel = child.relative_to(parent)
    except (ValueError, OSError):
        return False
    parts = [p.lower() for p in rel.parts]
    return bool(parts) and parts[0] in _IN_TREE_TEST_DIR_NAMES


def _path_only_in_tree_guess(project_root: Path, text: str, path: str) -> bool:
    """True when ``text`` is just an operator tests/ path with no extra user language."""
    if not path or not is_in_tree_operator_tests(project_root, path):
        return False
    remainder = str(text or "").replace(path, "")
    extracted = extract_existing_directory(text)
    if extracted:
        remainder = remainder.replace(extracted, "")
    remainder = remainder.strip(" \t\"'`\\/")
    return not remainder


def external_harness_seed(project_root: Path, value: str) -> str:
    """Operator-external directory or allowlisted git repo URL. Empty if not a user fact."""
    raw = str(value or "").strip()
    if not raw or raw.lower() in _HARNESS_SKIP_MARKERS or raw.lower() in _HARNESS_DEFAULT_MARKERS:
        return ""
    extracted = extract_existing_directory(raw)
    if extracted and not is_in_tree_operator_tests(project_root, extracted):
        return extracted
    return extract_harness_git_url(raw)


def coerce_test_script_root_arg(value: object, project_root: Path | str | None = None) -> str:
    """Keep git URLs as URLs. Do not Path.resolve() them — that smashes ``https://``."""
    raw = str(value or "").strip()
    if not raw:
        return ""
    git = extract_harness_git_url(raw)
    if git:
        return git
    root = Path(project_root).expanduser() if project_root is not None else None
    if root is not None:
        seed = external_harness_seed(root, raw)
        if seed:
            return seed
    try:
        path = Path(raw).expanduser()
        if path.is_dir():
            return str(path.resolve())
    except OSError:
        pass
    return raw


def harness_pin_path(project_root: Path) -> Path:
    return Path(project_root).expanduser().resolve() / AGENT_DIR / "harness_pin.yaml"


def persist_confirmed_harness_pin(project_root: Path, url: str) -> None:
    """Write a confirmed harness URL so later operator pins / tg-init can inherit it."""
    stored = str(url or "").strip()
    if not stored:
        return
    path = harness_pin_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    _dump(path, {"test_script_root": stored, "test_script_confirmed": True})


def peek_confirmed_harness(project_root: Path) -> str:
    """Confirmed URL from pin sidecar, goal occupancy, or current run-state. Empty is not a hit."""
    root = Path(project_root).expanduser().resolve()
    pin = _load(harness_pin_path(root))
    pinned = str(pin.get("test_script_root") or "").strip()
    if pinned and pin.get("test_script_confirmed") is not False:
        return pinned
    for kwargs in (
        {"arch": "goal", "workflow_id": "auto"},
        {"arch": "goal"},
        {"workflow_id": "auto"},
        {},
    ):
        try:
            st = load_state(root, **kwargs) if kwargs else load_state(root)
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(st, dict):
            continue
        url = str(st.get("test_script_root") or "").strip()
        if url and st.get("test_script_confirmed"):
            return url
    return ""


def copy_confirmed_harness(src_root: Path, dest_root: Path) -> str:
    """Copy a confirmed URL from goal / source occupancy onto the operator pin."""
    url = peek_confirmed_harness(src_root)
    if not url:
        url = peek_confirmed_harness(dest_root)
    if not url:
        return ""
    persist_confirmed_harness_pin(dest_root, url)
    return url


def normalize_start_test_script_root(project_root: Path, value: str) -> tuple[str, bool]:
    """Seed run-state from ``pilot_run`` / CLI. In-tree tests and default markers stay unconfirmed.

    An empty incoming value must not wipe a previously confirmed URL.
    """
    seed = external_harness_seed(project_root, value)
    if seed:
        return seed, True
    if str(value or "").strip():
        return "", False
    inherited = peek_confirmed_harness(project_root)
    if inherited:
        return inherited, True
    return "", False


def resolved_test_script_root(project_root: Path, picked: str = "") -> str:
    """Live tg-init: confirmed state wins; unconfirmed pack overlay is not a harness."""
    root = Path(project_root).expanduser().resolve()
    st = load_state(root) or {}
    if str(st.get("workflow_id") or "") != "tg-init":
        return str(picked or st.get("test_script_root") or "").strip()
    if st.get("test_script_confirmed"):
        url = str(st.get("test_script_root") or "").strip()
        if url:
            return url
        inherited = peek_confirmed_harness(root)
        if inherited:
            return inherited
    raw = str(picked or st.get("test_script_root") or "").strip()
    seeded = external_harness_seed(root, raw)
    if seeded:
        return seeded
    return peek_confirmed_harness(root)


def invalidate_tg_harness_downstream(project_root: Path) -> dict[str, Any]:
    """Drop scan/bind work so a new harness root is scanned on a fresh ticket."""
    from ascendc_pilot.actions.dispatch_legacy import discard_dispatch_tickets_for_action
    from ascendc_pilot.paths import agent_root, tg_root
    from ascendc_pilot.runs import invalidate_action_receipts, receipts_dir
    from ascendc_pilot.state import save_state
    from ascendc_pilot.state.machine import rework_phase

    root = Path(project_root).expanduser().resolve()
    st = load_state(root) or {}
    rid = str(st.get("run_id") or "").strip()
    arch = str(st.get("architecture") or "").strip() or None
    dropped: dict[str, Any] = {}
    if rid:
        scan = receipts_dir(root, rid) / "repo_scan.yaml"
        if scan.is_file():
            try:
                scan.unlink()
                dropped["repo_scan_yaml"] = True
            except OSError:
                dropped["repo_scan_yaml"] = False
        for aid in ("repo_scan", "bind_init", "bind_review", "bind_promote", "validate_init"):
            dropped[aid] = invalidate_action_receipts(root, action_id=aid, run_id=rid)
        dropped["tickets"] = discard_dispatch_tickets_for_action(
            root, run_id=rid, action_id="bind_init"
        )
        action_root = agent_root(root, arch) / "runs" / rid / "actions"
        for rel in (
            "bind_init/parts/harness.yaml",
            "bind_init/parts/bind.yaml",
            "bind_init/staging.yaml",
            "bind_review/verdict.yaml",
        ):
            path = action_root / rel
            if path.is_file():
                try:
                    path.unlink()
                    dropped[rel] = True
                except OSError:
                    dropped[rel] = False
        parts_dir = action_root / "bind_init" / "parts"
        if parts_dir.is_dir():
            for part in parts_dir.glob("*.yaml"):
                try:
                    part.unlink()
                    dropped[part.name] = True
                except OSError:
                    continue
    phase = str(st.get("phase") or "")
    if phase in {"bind", "validate"}:
        if phase == "validate":
            init_path = tg_root(root, arch=arch) / "init.yaml"
            if init_path.is_file():
                try:
                    init_path.unlink()
                    dropped["init_yaml"] = True
                except OSError:
                    dropped["init_yaml"] = False
        try:
            moved = rework_phase(root, to="scan", reason_code="HARNESS_CHANGED")
            dropped["rewound_to"] = str(moved.get("to") or "scan")
        except Exception as exc:  # noqa: BLE001
            dropped["rework_error"] = str(exc)[:200]
            st["phase"] = "scan"
            save_state(root, st)
            dropped["rewound_to"] = "scan"
    return dropped


def adopt_test_script_root(project_root: Path, value: str) -> dict[str, Any]:
    """Persist a confirmed harness choice. ``have_repo`` / ``custom`` / ``stop`` are not roots."""
    from ascendc_pilot.state import save_state

    root = Path(project_root).expanduser().resolve()
    raw = str(value or "").strip()
    if not raw or raw.lower() in _HARNESS_SKIP_MARKERS:
        return {"ok": True, "skipped": True, "test_script_root": ""}
    if raw.lower() in _HARNESS_DEFAULT_MARKERS:
        stored = "no_repo_uo_query"
    else:
        extracted = extract_existing_directory(raw)
        if extracted:
            stored = extracted
        else:
            git_url = extract_harness_git_url(raw)
            if git_url:
                try:
                    gw = _git_workspace()
                except Exception as exc:  # noqa: BLE001
                    return {
                        "ok": False,
                        "error": "GIT_WORKSPACE_IMPORT",
                        "message_zh": str(exc)[:200],
                        "value": raw,
                    }
                cloned = gw.clone_harness_repo(git_url, project_root=root)
                if not cloned.get("ok"):
                    return {
                        "ok": False,
                        "error": str(cloned.get("error") or "HARNESS_CLONE_FAILED"),
                        "message_zh": str(cloned.get("message_zh") or ""),
                        "value": raw,
                    }
                stored = str(cloned.get("path") or "")
            else:
                try:
                    path = Path(raw).expanduser()
                except OSError:
                    path = None
                if path is None or not path.is_dir():
                    return {"ok": False, "error": "NOT_A_DIRECTORY", "value": raw}
                stored = str(path.resolve())
    st = load_state(root) or {}
    if not st:
        return {"ok": True, "test_script_root": stored, "test_script_confirmed": True}
    old = str(st.get("test_script_root") or "").strip()
    st["test_script_root"] = stored
    st["test_script_confirmed"] = True
    save_state(root, st)
    persist_confirmed_harness_pin(root, stored)
    reset: dict[str, Any] = {}
    if old and old != stored:
        reset = invalidate_tg_harness_downstream(root)
    return {
        "ok": True,
        "test_script_root": stored,
        "test_script_confirmed": True,
        "reset": bool(reset),
        "reset_detail": reset,
    }


def _sign(project_root: Path, payload: dict[str, Any]) -> str:
    from ascendc_pilot.runs import sign_receipt_payload

    return sign_receipt_payload(Path(project_root), payload)


def _verify(project_root: Path, payload: dict[str, Any]) -> bool:
    from ascendc_pilot.runs import verify_receipt_signature

    return verify_receipt_signature(Path(project_root), payload)


def issue_interaction_request(
    project_root: Path,
    *,
    kind: str,
    ask_question: dict[str, Any],
    action_id: str = "",
    decision_kind: str = "",
    allowed_values: list[str] | None = None,
    run_id: str = "",
) -> dict[str, Any]:
    """Persist pending interaction and return the public request envelope."""
    project_root = Path(project_root).expanduser().resolve()
    state = load_state(project_root) or {}
    rid = (run_id or str(state.get("run_id") or "")).strip()
    request_id = secrets.token_hex(16)
    values = list(allowed_values or [])
    if not values:
        for opt in ask_question.get("options") or []:
            if not isinstance(opt, dict):
                continue
            for key in ("value", "label"):
                v = str(opt.get(key) or "").strip()
                if v and v not in values:
                    values.append(v)
    decision = decision_kind or kind
    existing = _load(pending_path(project_root))
    reuse = _pending_matches_ask(
        existing, kind=kind, decision=decision, action_id=action_id
    ) and (
        pending_is_open(existing)
        or pending_answered_unconsumed(project_root, existing)
    )
    if reuse:
        return _reuse_interaction_envelope(
            existing,
            kind=kind,
            decision=decision,
            action_id=action_id,
            rid=rid,
            values=values,
            ask_question=ask_question,
            request_id_fallback=request_id,
        )
    _clear_superseded_flag(project_root)
    req = {
        "schema": "human-interaction-request/v1",
        "request_id": request_id,
        "run_id": rid,
        "workflow_id": str(state.get("workflow_id") or ""),
        "action_id": action_id,
        "kind": kind,
        "decision_kind": decision,
        "ask_question": ask_question,
        "allowed_values": values,
        "issued_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "status": "pending",
    }
    if _control_plane_writable(project_root):
        _dump(pending_path(project_root), req)
    else:
        req["ephemeral"] = True
    return {
        "request_id": request_id,
        "run_id": rid,
        "workflow_id": req["workflow_id"],
        "action_id": action_id,
        "kind": kind,
        "decision_kind": req["decision_kind"],
        "allowed_values": values,
        "ask_question": ask_question,
    }


def attach_interaction_request(
    payload: dict[str, Any],
    project_root: Path | str | None,
    *,
    kind: str,
    action_id: str = "",
    decision_kind: str = "",
) -> dict[str, Any]:
    """If payload asks for a human decision, attach + persist a request envelope."""
    if not project_root:
        return payload
    ask = payload.get("ask_question")
    if not payload.get("needs_human_decision") and not ask:
        return payload
    if not isinstance(ask, dict):
        return payload
    root = Path(project_root).expanduser().resolve()
    try:
        env = issue_interaction_request(
            root,
            kind=kind,
            ask_question=ask,
            action_id=action_id or str(payload.get("action_id") or ""),
            decision_kind=decision_kind or str(payload.get("decision_kind") or kind),
            run_id=str(payload.get("run_id") or ""),
        )
    except Exception as exc:  # noqa: BLE001
        payload["human_interaction_error"] = str(exc)[:200]
        return payload
    payload["human_interaction_request"] = env
    payload["primary_instruction_zh"] = (
        str(payload.get("primary_instruction_zh") or "")
        + " Host 弹出 question UI；点选即写入收据。"
        " 若用户打断确认框并在对话里回复：用 `pilot_cli` "
        "`interpret-user-turn --project <算子绝对路径> --text <本轮原文>`，"
        "能对应原选项则记为答复，否则取消上一问并跟新消息。不要重问上一题。不要猜 `--message`。"
        "未点选不等于批准删除/重开。无收据不得 finalize / resume / 破坏性 reinit。"
    ).strip()
    return payload


def record_answer(
    project_root: Path,
    *,
    request_id: str,
    value: str,
) -> dict[str, Any]:
    """Validate pending request + write signed HumanDecisionReceipt."""
    project_root = Path(project_root).expanduser().resolve()
    pending = _load(pending_path(project_root))
    if not pending:
        hinted = _find_pending_elsewhere(project_root)
        return {
            "ok": False,
            "error": "NO_PENDING_INTERACTION",
            "message_zh": (
                "没有待处理的人工交互请求。"
                "若 AskQuestion 写在 PR clone 的算子目录，请对该 --project 再 answer。"
            ),
            "pending_interaction_path": hinted,
        }
    if str(pending.get("request_id") or "") != str(request_id or "").strip():
        return {
            "ok": False,
            "error": "REQUEST_ID_MISMATCH",
            "message_zh": "request_id 与 pending_interaction 不匹配",
            "expected": pending.get("request_id"),
            "got": request_id,
        }
    allowed = [str(v) for v in (pending.get("allowed_values") or [])]
    answer = str(value or "").strip()
    ask = pending.get("ask_question") if isinstance(pending.get("ask_question"), dict) else {}
    if allowed and answer not in allowed:
        # Accept option labels mapped via ask_question.options
        for opt in ask.get("options") or []:
            if not isinstance(opt, dict):
                continue
            if answer in {
                str(opt.get("label") or ""),
                str(opt.get("value") or ""),
            }:
                answer = str(opt.get("value") or opt.get("label") or answer)
                break
    free_path = ""
    git_url = ""
    if pending_allows_free_path(pending):
        free_path = extract_existing_directory(answer) or extract_existing_directory(str(value or ""))
        if free_path:
            answer = free_path
        else:
            git_url = extract_harness_git_url(answer) or extract_harness_git_url(str(value or ""))
            if git_url:
                answer = git_url
    try:
        from ascendc_pilot.run_resume import normalize_decision

        canon = normalize_decision(answer)
        if canon:
            answer = canon
        allowed_canon = {normalize_decision(v) or v for v in allowed} if allowed else set()
    except Exception:  # noqa: BLE001
        canon = None
        allowed_canon = set(allowed)
    path_ok = bool(free_path) or bool(git_url) or (
        pending_allows_free_path(pending)
        and answer.lower() not in _HARNESS_SKIP_MARKERS
        and (answer.lower() in _HARNESS_DEFAULT_MARKERS or Path(answer).is_dir())
    )
    if allowed and answer not in allowed and answer not in allowed_canon and not path_ok:
        if (
            pending_allows_free_path(pending)
            and answer.lower() not in _HARNESS_SKIP_MARKERS
            and not _looks_like_fs_path(answer)
        ):
            return supersede_pending(
                project_root, reason="ask_free_text", user_text=str(value or answer)
            )
        return {
            "ok": False,
            "error": "VALUE_NOT_ALLOWED",
            "allowed_values": allowed,
            "message_zh": f"回答 {value!r} 不在允许选项中",
        }
    state = load_state(project_root) or {}
    run_id = str(pending.get("run_id") or state.get("run_id") or "")
    receipt = {
        "schema": "human-decision-receipt/v1",
        "request_id": str(pending.get("request_id")),
        "run_id": run_id,
        "workflow_id": str(pending.get("workflow_id") or state.get("workflow_id") or ""),
        "action_id": str(pending.get("action_id") or ""),
        "kind": str(pending.get("kind") or ""),
        "decision_kind": str(pending.get("decision_kind") or ""),
        "value": answer,
        "consumed": False,
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "issued_by": "acp-answer",
    }
    receipt["signature"] = _sign(project_root, receipt)
    out = decisions_dir(project_root) / f"{receipt['request_id']}.yaml"
    _dump(out, receipt)
    pending["status"] = "answered"
    pending["answered_value"] = answer
    _dump(pending_path(project_root), pending)
    if pending_field(pending) == "test_script_root" or pending_allows_free_path(pending):
        adopt_test_script_root(project_root, answer)
    return {
        "ok": True,
        "receipt_path": str(out),
        "request_id": receipt["request_id"],
        "value": answer,
        "run_id": run_id,
        "kind": receipt["kind"],
        "action_id": receipt["action_id"],
    }


def require_decision_receipt(
    project_root: Path,
    *,
    expected_values: list[str] | None = None,
    expected_action_id: str = "",
    expected_kind: str = "",
    consume: bool = True,
) -> dict[str, Any]:
    """Require an unconsumed matching HumanDecisionReceipt."""
    project_root = Path(project_root).expanduser().resolve()
    pending = _load(pending_path(project_root))
    request_id = str(pending.get("request_id") or "").strip()
    if not request_id:
        # Fall back: newest unconsumed receipt for this run
        return {
            "ok": False,
            "error": "HUMAN_DECISION_RECEIPT_REQUIRED",
            "message_zh": (
                "缺少 HumanDecisionReceipt。Host 必须先弹出 question UI，"
                "点选写入签名收据后才能继续。"
            ),
        }
    path = decisions_dir(project_root) / f"{request_id}.yaml"
    receipt = _load(path)
    if not receipt:
        return {
            "ok": False,
            "error": "HUMAN_DECISION_RECEIPT_REQUIRED",
            "request_id": request_id,
            "message_zh": "pending interaction 尚未通过 question UI 产生收据",
        }
    if not _verify(project_root, receipt):
        return {
            "ok": False,
            "error": "HUMAN_DECISION_RECEIPT_INVALID",
            "message_zh": "HumanDecisionReceipt 签名无效",
        }
    if receipt.get("consumed"):
        return {
            "ok": False,
            "error": "HUMAN_DECISION_RECEIPT_CONSUMED",
            "message_zh": "HumanDecisionReceipt 已被消费，需重新 AskQuestion",
        }
    state = load_state(project_root) or {}
    run_id = str(state.get("run_id") or "")
    if run_id and str(receipt.get("run_id") or "") not in {"", run_id}:
        return {
            "ok": False,
            "error": "HUMAN_DECISION_RECEIPT_RUN_MISMATCH",
            "message_zh": "收据 run_id 与当前 run 不匹配",
        }
    if expected_action_id and str(receipt.get("action_id") or "") not in {
        "",
        expected_action_id,
    }:
        return {
            "ok": False,
            "error": "HUMAN_DECISION_RECEIPT_ACTION_MISMATCH",
            "expected_action_id": expected_action_id,
            "got": receipt.get("action_id"),
        }
    if expected_kind and str(receipt.get("kind") or "") not in {"", expected_kind}:
        return {
            "ok": False,
            "error": "HUMAN_DECISION_RECEIPT_KIND_MISMATCH",
            "expected_kind": expected_kind,
            "got": receipt.get("kind"),
        }
    value = str(receipt.get("value") or "")
    if expected_values and value not in expected_values:
        try:
            from ascendc_pilot.run_resume import normalize_decision

            got = normalize_decision(value) or value
            allowed = {normalize_decision(v) or v for v in expected_values}
            if got not in allowed:
                return {
                    "ok": False,
                    "error": "HUMAN_DECISION_RECEIPT_VALUE_MISMATCH",
                    "expected_values": list(expected_values),
                    "got": value,
                    "message_zh": f"收据值 {value!r} 不是本次操作所需的肯定选择",
                }
        except Exception:  # noqa: BLE001
            return {
                "ok": False,
                "error": "HUMAN_DECISION_RECEIPT_VALUE_MISMATCH",
                "expected_values": list(expected_values),
                "got": value,
                "message_zh": f"收据值 {value!r} 不是本次操作所需的肯定选择",
            }
    if consume:
        receipt["consumed"] = True
        receipt["consumed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        receipt["signature"] = _sign(project_root, receipt)
        _dump(path, receipt)
        if pending_path(project_root).is_file():
            pending_path(project_root).unlink()
    return {
        "ok": True,
        "value": value,
        "request_id": request_id,
        "receipt": receipt,
    }


def clear_pending(project_root: Path) -> None:
    path = pending_path(Path(project_root))
    if path.is_file():
        path.unlink()


def consume_intake_architecture(
    project_root: Path,
    *,
    architecture: str,
    force_new: bool = False,
) -> dict[str, Any]:
    """Record or clear pre-start intake so start/reinit is not deadlocked.

    Architecture intake is answered with the chosen arch*. ``--force-new``
    may drop a stale intake when no arch is available yet.
    """
    root = Path(project_root).expanduser().resolve()
    pending = load_pending(root)
    if str(pending.get("status") or "") != "pending":
        return {"ok": True, "skipped": True}
    if force_new:
        clear_pending(root)
        return {"ok": True, "cleared": True, "kind": pending.get("kind")}
    if not pending_is_intake(pending):
        return {"ok": True, "skipped": True, "kind": pending.get("kind")}
    arch = str(architecture or "").strip()
    rid = str(pending.get("request_id") or "")
    allowed = [str(v) for v in (pending.get("allowed_values") or [])]
    if arch and rid and (not allowed or arch in allowed):
        rec = record_answer(root, request_id=rid, value=arch)
        if rec.get("ok"):
            return rec
    return {
        "ok": True,
        "pending": True,
        "request_id": rid,
        "kind": pending.get("kind"),
    }


_DESTRUCTIVE_VALUES = frozenset(
    {
        "reinit",
        "force_new",
        "force-new",
        "abort_run",
        "abort",
        "wipe",
    }
)

_ARCH_TOKEN = re.compile(r"\barch[0-9A-Za-z._-]+\b", re.I)


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "")).strip().lower()


def _option_catalog(pending: dict[str, Any]) -> list[tuple[str, list[str]]]:
    """Canonical value → labels that count as that value."""
    rows: list[tuple[str, list[str]]] = []
    seen: set[str] = set()
    ask = pending.get("ask_question") if isinstance(pending.get("ask_question"), dict) else {}
    for opt in ask.get("options") or []:
        if not isinstance(opt, dict):
            continue
        value = str(opt.get("value") or "").strip()
        label = str(opt.get("label") or "").strip()
        if not value and not label:
            continue
        canon = value or label
        labels = [x for x in (value, label) if x]
        if canon in seen:
            for i, (v, labs) in enumerate(rows):
                if v == canon:
                    rows[i] = (v, list(dict.fromkeys([*labs, *labels])))
                    break
            continue
        seen.add(canon)
        rows.append((canon, labels))
    for raw in pending.get("allowed_values") or []:
        value = str(raw or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        rows.append((value, [value]))
    return rows


def match_pending_option(pending: dict[str, Any] | None, text: str) -> str | None:
    """Map a free-text reply onto one pending option. None if it is not a choice.

    Conservative: exact value/label, resume-decision aliases, unique arch* token.
    Short messages may uniquely contain one option token. Long new requests do not
    silently confirm, and wipe/reinit never match a long off-topic message.
    """
    if not pending_is_open(pending):
        return None
    raw = str(text or "").strip()
    if not raw:
        return None
    catalog = _option_catalog(pending or {})
    if not catalog:
        return None
    compact = _compact(raw)
    allowed = {v for v, _ in catalog}
    allowed_l = {v.lower(): v for v in allowed}

    for value, labels in catalog:
        if raw == value or compact == _compact(value):
            return value
        for lab in labels:
            if raw == lab or compact == _compact(lab):
                return value

    try:
        from ascendc_pilot.run_resume import normalize_decision

        canon = normalize_decision(raw)
    except Exception:  # noqa: BLE001
        canon = None
    if canon:
        if canon in allowed:
            return canon
        mapped = allowed_l.get(canon.lower())
        if mapped:
            return mapped

    from ascendc_pilot.goal_turn import is_answer_shaped

    arches = [v for v in allowed if re.fullmatch(r"arch[0-9A-Za-z._-]+", v, re.I)]
    if arches and is_answer_shaped(raw, pending=pending):
        found: list[str] = []
        for token in _ARCH_TOKEN.findall(raw):
            hit = allowed_l.get(token.lower())
            if not hit:
                from uo_init.source_layout import match_on_disk_architecture

                mapped = match_on_disk_architecture(token, arches)
                hit = mapped if mapped in set(arches) else None
            if hit and hit not in found:
                found.append(hit)
        if len(found) == 1:
            return found[0]

    if len(raw) <= 24 and is_answer_shaped(raw, pending=pending):
        hits: list[str] = []
        for value, labels in catalog:
            tokens = [value, *labels]
            if any(_compact(t) and _compact(t) in compact for t in tokens):
                hits.append(value)
        uniq = list(dict.fromkeys(hits))
        if len(uniq) == 1:
            return uniq[0]
    if pending_allows_free_path(pending):
        extracted = extract_existing_directory(raw)
        if extracted:
            return extracted
        git_url = extract_harness_git_url(raw)
        if git_url:
            return git_url
    return None


def _clear_superseded_flag(project_root: Path) -> None:
    from ascendc_pilot.state import load_state, save_state

    st = load_state(project_root)
    if not st:
        return
    if not st.get("human_decision_superseded"):
        return
    st.pop("human_decision_superseded", None)
    st.pop("human_decision_superseded_reason", None)
    save_state(project_root, st)


def supersede_pending(
    project_root: Path,
    *,
    reason: str = "user_interrupted",
    user_text: str = "",
    relation: str = "",
) -> dict[str, Any]:
    """Drop a pending AskQuestion because the user moved on. Never auto-confirms."""
    root = Path(project_root).expanduser().resolve()
    pending = _load(pending_path(root))
    if not pending_is_open(pending):
        return {
            "ok": True,
            "disposition": "idle",
            "needs_human_decision": False,
            "message_zh": "没有待确认的问题",
        }
    ask = pending.get("ask_question") if isinstance(pending.get("ask_question"), dict) else {}
    header = str(ask.get("header") or ask.get("question") or pending.get("kind") or "")
    pending["status"] = "superseded"
    pending["supersede_reason"] = str(reason or "user_interrupted")
    pending["user_text"] = str(user_text or "")[:500]
    pending["relation"] = str(relation or "")
    pending["superseded_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _dump(pending_path(root), pending)

    from ascendc_pilot.state import load_state, save_state

    st = load_state(root)
    if st:
        st["human_decision_superseded"] = True
        st["human_decision_superseded_reason"] = str(reason or "user_interrupted")
        if relation:
            st["last_goal_relation"] = relation
        save_state(root, st)

    from ascendc_pilot.human_voice import FOLLOW_NEW_TURN_ZH

    effects = apply_goal_relation(root, relation or "side_question", user_text)
    paused = bool(effects.get("paused"))
    return {
        "ok": True,
        "disposition": "superseded",
        "relation": relation or effects.get("relation") or "side_question",
        "ask_interrupted": True,
        "paused": paused,
        "needs_human_decision": False,
        "previous_kind": str(pending.get("kind") or ""),
        "previous_header": header,
        "request_id": str(pending.get("request_id") or ""),
        **{k: v for k, v in effects.items() if k not in {"ok"}},
        "message_zh": (
            "上一问确认已被本轮新消息打断，已解除卡住。"
            "请按本轮用户消息继续，不要重问上一题。"
            "未点选不等于批准删除/重开。"
            + FOLLOW_NEW_TURN_ZH
        ),
    }


def apply_goal_relation(
    project_root: Path,
    relation: str,
    user_text: str = "",
) -> dict[str, Any]:
    """Apply Goal Relation side effects (pause lock / revise plan)."""
    from ascendc_pilot.goal_turn import REL_CANCEL, REL_REVISE, REL_SIDE, REL_SWITCH
    from ascendc_pilot.occupancy import LIVENESS_PAUSED, set_lock_lifecycle
    from ascendc_pilot.state import load_state
    from ascendc_pilot.user_goal import pause_user_goal, request_goal_revision

    root = Path(project_root).expanduser().resolve()
    rel = str(relation or "").strip() or REL_SIDE
    st = load_state(root) or {}
    out: dict[str, Any] = {"relation": rel, "paused": False}
    if rel == REL_SIDE:
        return out
    if rel in {REL_SWITCH, REL_CANCEL}:
        set_lock_lifecycle(root, LIVENESS_PAUSED, run_id=str(st.get("run_id") or ""))
        pause_user_goal(root, reason=rel)
        out["paused"] = True
        return out
    if rel == REL_REVISE:
        revised = request_goal_revision(root, user_text)
        out.update(revised)
        return out
    return out


def interpret_user_turn(
    project_root: Path,
    *,
    text: str = "",
    reason: str = "user_message",
) -> dict[str, Any]:
    """Latest user turn vs pending AskQuestion and the active Goal."""
    from ascendc_pilot.goal_turn import REL_ANSWER, classify_goal_turn
    from ascendc_pilot.state import load_state
    from ascendc_pilot.user_goal import load_user_goal

    root = Path(project_root).expanduser().resolve()
    pending = load_pending(root)
    st = load_state(root) or {}
    relation = classify_goal_turn(
        text,
        pending=pending,
        workflow_id=str(st.get("workflow_id") or ""),
        goal=load_user_goal(root),
    )
    if pending_is_open(pending):
        try_match = relation == REL_ANSWER or pending_allows_free_path(pending)
        mapped = match_pending_option(pending, text) if try_match else None
        if mapped and mapped.lower() in _DESTRUCTIVE_VALUES and len(str(text or "").strip()) > 24:
            mapped = None
        if mapped and _path_only_in_tree_guess(root, text, mapped):
            mapped = None
        if mapped:
            rec = record_answer(
                root,
                request_id=str(pending.get("request_id") or ""),
                value=mapped,
            )
            if rec.get("ok"):
                _clear_superseded_flag(root)
                rec["disposition"] = "answered"
                rec["relation"] = REL_ANSWER
                rec["needs_human_decision"] = False
                rec["message_zh"] = f"已把本轮回复记为选项「{mapped}」"
                return rec
        extracted_pending = extract_existing_directory(text)
        if extracted_pending and _path_only_in_tree_guess(root, text, extracted_pending):
            return {
                "ok": True,
                "disposition": "ignored_in_tree_guess",
                "needs_human_decision": True,
                "test_script_root": "",
                "message_zh": (
                    "仓内 tests/ 不是已确认的测试脚本仓。"
                    "请点选 Ask 的仓内项，或在末项输入外部路径 / git URL；不要把发现的 tests/ 代答。"
                ),
            }
        if extracted_pending and (
            pending_allows_free_path(pending) or pending_field(pending) == "test_script_root"
        ):
            rec = record_answer(
                root,
                request_id=str(pending.get("request_id") or ""),
                value=extracted_pending,
            )
            if rec.get("ok"):
                _clear_superseded_flag(root)
                rec["disposition"] = "answered"
                rec["relation"] = REL_ANSWER
                rec["needs_human_decision"] = False
                rec["message_zh"] = f"已把测试脚本仓记为 {extracted_pending}"
                return rec
        git_pending = extract_harness_git_url(text)
        if git_pending and (
            pending_allows_free_path(pending) or pending_field(pending) == "test_script_root"
        ):
            rec = record_answer(
                root,
                request_id=str(pending.get("request_id") or ""),
                value=git_pending,
            )
            if rec.get("ok"):
                _clear_superseded_flag(root)
                rec["disposition"] = "answered"
                rec["relation"] = REL_ANSWER
                rec["needs_human_decision"] = False
                rec["message_zh"] = f"已把测试脚本仓记为 {git_pending}"
                return rec
        return supersede_pending(
            root, reason=reason, user_text=text, relation=relation
        )
    extracted = extract_existing_directory(text)
    if extracted and str(st.get("workflow_id") or "") == "tg-init":
        if is_in_tree_operator_tests(root, extracted):
            # Path-only in-tree is a Primary guess (pilot_run overlay). In-tree
            # harness is only confirmed by AskQuestion / pending option match.
            pass
        else:
            adopted = adopt_test_script_root(root, extracted)
            if adopted.get("ok") and not adopted.get("skipped"):
                reset = bool(adopted.get("reset"))
                return {
                    "ok": True,
                    "disposition": "harness_reset" if reset else "adopted_test_script_root",
                    "value": extracted,
                    "test_script_root": adopted.get("test_script_root") or extracted,
                    "reset": reset,
                    "needs_human_decision": False,
                    "message_zh": (
                        f"已改用测试脚本仓 {extracted}，scan/bind 将按新路径重做"
                        if reset
                        else f"已把测试脚本仓记为 {extracted}"
                    ),
                }
    git_url = extract_harness_git_url(text)
    if git_url and str(st.get("workflow_id") or "") == "tg-init":
        adopted = adopt_test_script_root(root, git_url)
        if adopted.get("ok") and not adopted.get("skipped"):
            reset = bool(adopted.get("reset"))
            stored = str(adopted.get("test_script_root") or git_url)
            return {
                "ok": True,
                "disposition": "harness_reset" if reset else "adopted_test_script_root",
                "value": git_url,
                "test_script_root": stored,
                "reset": reset,
                "needs_human_decision": False,
                "message_zh": (
                    f"已改用测试脚本仓 {stored}，scan/bind 将按新路径重做"
                    if reset
                    else f"已把测试脚本仓记为 {stored}"
                ),
            }
    effects = apply_goal_relation(root, relation, text)
    from ascendc_pilot.human_voice import FOLLOW_NEW_TURN_ZH

    return {
        "ok": True,
        "disposition": relation,
        "relation": relation,
        "needs_human_decision": False,
        "paused": bool(effects.get("paused")),
        "message_zh": FOLLOW_NEW_TURN_ZH,
        **effects,
    }
