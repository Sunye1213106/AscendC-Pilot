"""Host dispatch tickets: bind prepare → subagent return → finalize without LLM choreography."""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

_ATTACH_DEPTH = threading.local()

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]


def _ticket_dir(project_root: Path, *, run_id: str = "") -> Path:
    from ascendc_pilot.authorize.lease import run_control_dir
    from ascendc_pilot.paths import agent_root

    rid = str(run_id or "").strip()
    if rid:
        try:
            d = run_control_dir(project_root, run_id=rid) / "dispatch_tickets"
            d.mkdir(parents=True, exist_ok=True)
            return d
        except ValueError:
            pass
    d = agent_root(project_root) / "state" / "dispatch_tickets"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_ticket(project_root: Path, doc: dict[str, Any]) -> None:
    path = _ticket_dir(project_root, run_id=str(doc.get("run_id") or "")) / f"{doc['ticket_id']}.yaml"
    if yaml is not None:
        path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    else:
        path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")


_SLICE_ID_RE = re.compile(
    r"(?:^|\n)\s*(?:AXIS|SLICE_ID)\s*=\s*([A-Za-z0-9_-]+)",
    re.I,
)
_LOCK_STALE_S = 30.0
_LOCK_WAIT_S = 10.0


def _acquire_lockfile(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.time() + _LOCK_WAIT_S
    while True:
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            try:
                os.write(fd, str(os.getpid()).encode("utf-8"))
            finally:
                os.close(fd)
            return
        except FileExistsError:
            try:
                age = time.time() - path.stat().st_mtime
            except OSError:
                age = _LOCK_STALE_S + 1
            if age > _LOCK_STALE_S:
                try:
                    path.unlink()
                    continue
                except OSError:
                    pass
            if time.time() >= deadline:
                raise TimeoutError(f"dispatch ticket lock busy: {path}")
            time.sleep(0.05)


def _release_lockfile(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


@contextmanager
def _ticket_exclusive(project_root: Path, ticket_id: str) -> Iterator[dict[str, Any]]:
    doc = load_dispatch_ticket(project_root, ticket_id)
    lock = _ticket_dir(project_root, run_id=str((doc or {}).get("run_id") or "")) / f"{ticket_id}.lock"
    _acquire_lockfile(lock)
    try:
        yield load_dispatch_ticket(project_root, ticket_id)
    finally:
        _release_lockfile(lock)


def _expected_slices(doc: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for raw in doc.get("expected_slices") or []:
        sid = str(raw or "").strip()
        if sid and sid not in out:
            out.append(sid)
    return out


def infer_slice_id(
    result_text: str,
    expected: list[str],
    acked: dict[str, Any],
    *,
    explicit: str = "",
) -> str:
    """Bind an ACK to one expected slice. Count-complete; order does not matter."""
    want = [str(s).strip() for s in expected if str(s).strip()]
    exp = str(explicit or "").strip()
    if exp and exp in want:
        return exp
    match = _SLICE_ID_RE.search(str(result_text or ""))
    if match:
        found = str(match.group(1) or "").strip()
        if found in want:
            return found
    remaining = [s for s in want if s not in acked]
    if len(remaining) == 1:
        return remaining[0]
    text = str(result_text or "")
    filename_hits = [
        sid
        for sid in remaining
        if re.search(
            rf"(?:^|[^\w.])(?:parts[/\\])?{re.escape(sid)}\.(?:yaml|yml|md)\b",
            text,
            re.I,
        )
    ]
    if len(filename_hits) == 1:
        return filename_hits[0]
    return ""


def _concat_slice_results(expected: list[str], results: dict[str, Any]) -> str:
    parts: list[str] = []
    for sid in expected:
        row = results.get(sid) if isinstance(results.get(sid), dict) else {}
        text = str((row or {}).get("text") or "").strip()
        parts.append(f"## AXIS={sid}\n\n{text}".rstrip())
    return "\n\n".join(parts).strip()


def _remaining_dispatch_tasks(doc: dict[str, Any], acked: dict[str, Any]) -> list[dict[str, str]]:
    remaining = {s for s in _expected_slices(doc) if s not in acked}
    out: list[dict[str, str]] = []
    for row in doc.get("dispatch_tasks") or []:
        if not isinstance(row, dict):
            continue
        sid = str(row.get("slice_id") or "").strip()
        stub = str(row.get("task_prompt_stub") or "").strip()
        if sid in remaining and stub:
            out.append(
                {
                    "slice_id": sid,
                    "focus": str(row.get("focus") or ""),
                    "first_mode": str(row.get("first_mode") or ""),
                    "actor_id": str(row.get("actor_id") or ""),
                    "action_id": str(row.get("action_id") or ""),
                    "task_prompt_stub": stub,
                }
            )
    return out


def _waiting_fanout_host_step(
    project_root: Path,
    doc: dict[str, Any],
    remaining_tasks: list[dict[str, str]],
    remaining_ids: list[str],
) -> dict[str, Any]:
    actor = str(doc.get("actor_id") or "")
    prep: dict[str, Any] = {
        "action_id": str(doc.get("action_id") or ""),
        "actor_id": actor,
        "session_dir": str(doc.get("session_dir") or ""),
        "lease_id": str(doc.get("lease_id") or ""),
        "run_id": str(doc.get("run_id") or ""),
        "task_prompt_stub": "",
        "dispatch_tasks": [],
    }
    ids = ", ".join(remaining_ids)
    if len(remaining_tasks) >= 2:
        prep["dispatch_tasks"] = remaining_tasks
        message = (
            f"切片未齐，禁止 finalize。剩余切片必须在同一条回复里一次性并行派发原生 Task"
            f"（agent={actor}）：{ids}。禁止 session.create / 禁止开新对话。禁止等一个完成再派下一个。"
        )
    elif remaining_tasks:
        prep["task_prompt_stub"] = remaining_tasks[0]["task_prompt_stub"]
        message = (
            f"切片未齐，禁止 finalize。请立刻用原生 Task 派发剩余切片"
            f" `{remaining_tasks[0].get('slice_id') or ids}` 的 task_prompt_stub。"
            "禁止 session.create / 禁止开新对话。禁止再拆成多轮。"
        )
    else:
        message = "切片未齐，另一轴仍在返回中。禁止现在 finalize。禁止开新对话。"
    return build_host_step(
        kind="dispatch_subagent",
        project_root=project_root,
        action_id=str(doc.get("action_id") or ""),
        actor_id=actor,
        ticket=doc,
        prepare=prep,
        message_zh=message,
        extra={
            "waiting_slices": True,
            "remaining_slices": remaining_ids,
            "dispatch_ticket": str(doc.get("ticket_id") or ""),
        },
    )


def ack_fanout_slice(
    project_root: Path,
    ticket_id: str,
    *,
    result_text: str = "",
    slice_id: str = "",
) -> dict[str, Any]:
    """Record one fan-out Task return. Ready when the expected *count* is in.

    ACK 按到达计数。Host 必须一开始就把全部切片拉起。
    禁止把「计数到齐即可」理解成可以逐个派发。
    """
    with _ticket_exclusive(project_root, ticket_id) as doc:
        if not doc:
            return {"ok": False, "error": "TICKET_NOT_FOUND", "ticket_id": ticket_id}
        expected = _expected_slices(doc)
        if len(expected) < 2:
            return {"ok": True, "fanout": False, "ticket": doc}
        status = str(doc.get("status") or "")
        if status in {"consumed", "processing", "blocked_repeat_failure"}:
            return {
                "ok": False,
                "error": "TICKET_NOT_CLAIMABLE",
                "ticket_id": ticket_id,
                "status": status,
            }
        results = dict(doc.get("slice_results") or {})
        remaining_ids = [s for s in expected if s not in results]
        if not remaining_ids:
            combined = _concat_slice_results(expected, results)
            return {
                "ok": True,
                "fanout": True,
                "ready": True,
                "acked_slices": list(expected),
                "remaining_slices": [],
                "dispatch_ticket": ticket_id,
                "ticket": doc,
                "combined_text": combined,
                "slice_results": results,
            }
        sid = infer_slice_id(result_text, expected, results, explicit=slice_id)
        if not sid:
            return {
                "ok": False,
                "error": "SLICE_ID_REQUIRED",
                "ticket_id": ticket_id,
                "expected_slices": expected,
            }
        if sid not in results:
            results[sid] = {
                "text": str(result_text or ""),
                "acked_at": time.time(),
            }
            doc["slice_results"] = results
            doc["status"] = "collecting"
            _write_ticket(project_root, doc)
        remaining_ids = [s for s in expected if s not in results]
        if remaining_ids:
            remaining_tasks = _remaining_dispatch_tasks(doc, results)
            host_step = _waiting_fanout_host_step(
                project_root, doc, remaining_tasks, remaining_ids
            )
            return {
                "ok": True,
                "fanout": True,
                "waiting_slices": True,
                "acked_slices": [s for s in expected if s in results],
                "remaining_slices": remaining_ids,
                "dispatch_ticket": ticket_id,
                "ticket": doc,
                "host_step": host_step,
            }
        combined = _concat_slice_results(expected, results)
        return {
            "ok": True,
            "fanout": True,
            "ready": True,
            "acked_slices": list(expected),
            "remaining_slices": [],
            "dispatch_ticket": ticket_id,
            "ticket": doc,
            "combined_text": combined,
            "slice_results": results,
        }


def reopen_fanout_slices(
    project_root: Path,
    *,
    action_id: str,
    slice_ids: list[str],
    run_id: str = "",
) -> dict[str, Any]:
    """Drop named fan-out ACK + part files so only those slices re-dispatch."""
    from pathlib import Path as P

    wanted = [str(s).strip() for s in slice_ids if str(s).strip()]
    if not wanted:
        return {"ok": False, "error": "REWORK_SLICES_EMPTY"}
    doc = find_dispatch_ticket_for_action(
        project_root, run_id=run_id, action_id=action_id
    )
    if not doc:
        return {"ok": False, "error": "TICKET_NOT_FOUND", "action_id": action_id}
    if "bind" in wanted:
        from testcase_agent.bind_parts import is_bind_chunk_id, list_bind_chunk_paths

        expected = _expected_slices(doc)
        extra = [s for s in expected if is_bind_chunk_id(s)]
        if not extra:
            extra = [
                p.stem
                for p in list_bind_chunk_paths(P(str(doc.get("session_dir") or "")) / "parts")
            ]
        wanted = [s for s in wanted if s != "bind"] + extra
        if not wanted:
            return {"ok": False, "error": "REWORK_SLICES_EMPTY"}
    results = dict(doc.get("slice_results") or {})
    for sid in wanted:
        results.pop(sid, None)
        sdir = P(str(doc.get("session_dir") or ""))
        if sdir.is_dir():
            for name in (f"{sid}.yaml", f"{sid}.md"):
                part = sdir / "parts" / name
                if part.is_file():
                    prev = part.parent / (part.name + ".prev")
                    try:
                        import shutil

                        shutil.copy2(part, prev)
                    except OSError:
                        pass
                    part.unlink()
    doc["slice_results"] = results
    doc["status"] = "collecting"
    _write_ticket(project_root, doc)
    remaining_ids = [s for s in _expected_slices(doc) if s not in results]
    remaining_tasks = _remaining_dispatch_tasks(doc, results)
    return {
        "ok": True,
        "ticket": doc,
        "rework": wanted,
        "remaining_slices": remaining_ids,
        "remaining_tasks": remaining_tasks,
        "host_step": _waiting_fanout_host_step(
            project_root, doc, remaining_tasks, remaining_ids
        ),
    }


def issue_dispatch_ticket(
    project_root: Path,
    *,
    run_id: str,
    action_id: str,
    actor_id: str,
    lease_id: str = "",
    session_dir: str = "",
    task_prompt_stub: str = "",
    session_id: str = "",
    workflow_id: str = "",
    prepare_nonce: str = "",
    uo_digest: str = "",
    source_revision: str = "",
    expected_slices: list[str] | None = None,
    dispatch_tasks: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Create a one-shot ticket for Host Session Driver (status=open)."""
    from ascendc_pilot.occupancy import current_session_id, current_workflow_id, live_digest_for

    raw = f"{run_id}:{action_id}:{actor_id}:{time.time_ns()}"
    ticket_id = "dxt_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]
    sid = str(session_id or current_session_id() or "").strip()
    wid = str(workflow_id or current_workflow_id() or "").strip()
    digest = str(uo_digest or "").strip()
    if not digest:
        try:
            digest = live_digest_for(project_root) or ""
        except Exception:  # noqa: BLE001
            digest = ""
    revision = str(source_revision or "").strip()
    if not revision:
        try:
            from testcase_agent.closure.ledger import baseline_fingerprint

            revision = str((baseline_fingerprint(project_root) or {}).get("source_revision") or "")
        except Exception:  # noqa: BLE001
            revision = ""
    doc = {
        "ticket_id": ticket_id,
        "run_id": run_id,
        "action_id": action_id,
        "actor_id": actor_id,
        "lease_id": lease_id,
        "session_dir": session_dir,
        "session_id": sid,
        "workflow_id": wid,
        "prepare_nonce": prepare_nonce,
        "uo_digest": digest,
        "source_revision": revision,
        "status": "open",
        "created_at": time.time(),
        "task_prompt_stub_sha256": hashlib.sha256(
            (task_prompt_stub or "").encode("utf-8")
        ).hexdigest()
        if task_prompt_stub
        else "",
        "expected_slices": [
            str(s).strip() for s in (expected_slices or []) if str(s).strip()
        ],
        "dispatch_tasks": [dict(row) for row in (dispatch_tasks or []) if isinstance(row, dict)],
        "slice_results": {},
    }
    _write_ticket(project_root, doc)
    return doc


def load_dispatch_ticket(project_root: Path, ticket_id: str) -> dict[str, Any]:
    tid = (ticket_id or "").strip()
    if not tid:
        return {}
    from ascendc_pilot.paths import runs_root

    candidates = [
        _ticket_dir(project_root) / f"{tid}.yaml",
    ]
    try:
        from ascendc_pilot.state import load_state

        rid = str((load_state(project_root) or {}).get("run_id") or "")
        if rid:
            candidates.insert(0, _ticket_dir(project_root, run_id=rid) / f"{tid}.yaml")
    except Exception:  # noqa: BLE001
        pass
    try:
        root = runs_root(project_root)
        if root.is_dir():
            for control in root.glob("*/control/dispatch_tickets"):
                candidates.append(control / f"{tid}.yaml")
    except Exception:  # noqa: BLE001
        pass
    seen: set[str] = set()
    for path in candidates:
        key = str(path)
        if key in seen or not path.is_file():
            continue
        seen.add(key)
        try:
            if yaml is not None:
                data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            else:
                data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data:
                return data
        except Exception:  # noqa: BLE001
            continue
    return {}


def find_dispatch_ticket_for_action(
    project_root: Path,
    *,
    run_id: str,
    action_id: str,
    statuses: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Latest ticket for this run+action, optionally filtered by status."""
    wanted = {str(s) for s in (statuses or ())}
    rid = str(run_id or "").strip()
    aid = str(action_id or "").strip()
    if not rid or not aid:
        return {}
    found: list[dict[str, Any]] = []
    try:
        folder = _ticket_dir(project_root, run_id=rid)
    except Exception:  # noqa: BLE001
        folder = None
    paths: list[Path] = []
    if folder is not None and folder.is_dir():
        paths.extend(sorted(folder.glob("dxt_*.yaml")))
    for path in paths:
        try:
            if yaml is not None:
                data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            else:
                data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(data, dict):
            continue
        if str(data.get("run_id") or "") != rid or str(data.get("action_id") or "") != aid:
            continue
        if wanted and str(data.get("status") or "") not in wanted:
            continue
        found.append(data)
    if not found:
        return {}
    found.sort(key=lambda d: float(d.get("created_at") or 0), reverse=True)
    return found[0]


def discard_dispatch_tickets_for_action(
    project_root: Path,
    *,
    run_id: str,
    action_id: str,
) -> int:
    """Drop tickets for an action so rework can issue a fresh dispatch."""
    rid = str(run_id or "").strip()
    aid = str(action_id or "").strip()
    if not rid or not aid:
        return 0
    try:
        folder = _ticket_dir(project_root, run_id=rid)
    except Exception:  # noqa: BLE001
        return 0
    if not folder.is_dir():
        return 0
    dropped = 0
    for path in list(folder.glob("dxt_*.yaml")):
        try:
            if yaml is not None:
                data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            else:
                data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(data, dict):
            continue
        if str(data.get("run_id") or "") != rid or str(data.get("action_id") or "") != aid:
            continue
        try:
            path.unlink()
            dropped += 1
        except OSError:
            continue
    return dropped


_SKIP_PART_STEMS = frozenset({"merged", "referee"})
_HARVEST_PART_SUFFIXES = {".md", ".yaml", ".yml"}


def _parts_dir_for_ticket(project_root: Path, ticket: dict[str, Any]) -> Path | None:
    """Prefer the ticket session dir; fall back to arch-scoped runs/parts."""
    session_dir = str(ticket.get("session_dir") or "").strip()
    if session_dir:
        direct = Path(session_dir) / "parts"
        if direct.is_dir():
            return direct
    run_id = str(ticket.get("run_id") or "").strip()
    action_id = str(ticket.get("action_id") or "").strip()
    if not run_id or not action_id:
        return None
    try:
        from ascendc_pilot.paths import agent_root

        fallback = (
            agent_root(project_root) / "runs" / run_id / "actions" / action_id / "parts"
        )
    except Exception:  # noqa: BLE001
        return None
    return fallback if fallback.is_dir() else None


def harvest_parts_into_ticket(project_root: Path, ticket: dict[str, Any]) -> dict[str, Any]:
    """Fallback ACK from leftover ``parts/{slice}.md|.yaml`` when Task ACK missed.

    Dual-axis review ACKs from native Task text first. tg-init bind fanout
    writes ``harness.yaml`` / ``bind.yaml``; sequential Task is enough if those
    drafts exist. Disk harvest is not the product path and must not require
    children to Write.
    """
    if not ticket:
        return {}
    expected = _expected_slices(ticket)
    if not expected:
        return ticket
    tid = str(ticket.get("ticket_id") or "")
    if not tid:
        return ticket
    parts_dir = _parts_dir_for_ticket(project_root, ticket)
    if parts_dir is None or not parts_dir.is_dir():
        return ticket
    results = dict(ticket.get("slice_results") or {})
    if "fix" in expected and "fix" not in results:
        harness = parts_dir / "harness.yaml"
        bindp = parts_dir / "bind.yaml"
        if harness.is_file() and bindp.is_file():
            try:
                text = harness.read_text(encoding="utf-8") + "\n" + bindp.read_text(encoding="utf-8")
            except OSError:
                text = "SLICE_ID=fix"
            acked = ack_fanout_slice(project_root, tid, result_text=text, slice_id="fix")
            try:
                from testcase_agent.bind_parts import mark_llm_edited

                mark_llm_edited(harness)
                mark_llm_edited(bindp)
            except Exception:
                pass
            return acked.get("ticket") or load_dispatch_ticket(project_root, tid) or ticket
    if len(expected) < 2:
        return ticket
    for path in sorted(parts_dir.iterdir()):
        if not path.is_file() or path.suffix.lower() not in _HARVEST_PART_SUFFIXES:
            continue
        sid = path.stem.strip()
        if not sid or sid in _SKIP_PART_STEMS or sid not in expected or sid in results:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        acked = ack_fanout_slice(project_root, tid, result_text=text, slice_id=sid)
        try:
            from testcase_agent.bind_parts import mark_llm_edited

            mark_llm_edited(path)
        except Exception:
            pass
        ticket = acked.get("ticket") or load_dispatch_ticket(project_root, tid) or ticket
        results = dict(ticket.get("slice_results") or {})
    return load_dispatch_ticket(project_root, tid) or ticket


def write_axis_merged_part(project_root: Path, ticket: dict[str, Any]) -> Path | None:
    """Primary merge note after both axes ACK. Does not re-dispatch."""
    run_id = str(ticket.get("run_id") or "")
    action_id = str(ticket.get("action_id") or "")
    if not run_id or not action_id:
        return None
    try:
        from ascendc_pilot.paths import agent_root

        parts_dir = (
            agent_root(project_root) / "runs" / run_id / "actions" / action_id / "parts"
        )
    except Exception:  # noqa: BLE001
        return None
    parts_dir.mkdir(parents=True, exist_ok=True)
    expected = _expected_slices(ticket)
    results = ticket.get("slice_results") if isinstance(ticket.get("slice_results"), dict) else {}
    chunks = [
        "# Merged review axes",
        "",
        "Internal concat of native Task text. Primary user-facing merge must be:",
        "1. 审查完成",
        "2. 这个 PR 做什么",
        "3. 改了哪些文件",
        "4. 问题 1/2/3…（path:line）",
        "5. 要测的变量（字段与取值）",
        "Do not paste AXIS=/I5/H0 tables as the user answer.",
        "",
    ]
    for sid in expected:
        row = results.get(sid) if isinstance(results.get(sid), dict) else {}
        chunks.append(f"## AXIS={sid}")
        chunks.append("")
        chunks.append(str(row.get("text") or "")[:8000])
        chunks.append("")
    chunks.append(
        "Do not re-prepare spec/standards. Retract findings that field write_sites / readers disprove."
    )
    path = parts_dir / "merged.md"
    path.write_text("\n".join(chunks), encoding="utf-8")
    return path


def claim_dispatch_ticket(project_root: Path, ticket_id: str) -> dict[str, Any]:
    """open | retryable_failed → processing. Finalize must succeed before consume."""
    doc = load_dispatch_ticket(project_root, ticket_id)
    if not doc:
        return {"ok": False, "error": "TICKET_NOT_FOUND", "ticket_id": ticket_id}
    status = str(doc.get("status") or "")
    if status not in {"open", "retryable_failed", "collecting"}:
        return {
            "ok": False,
            "error": "TICKET_NOT_CLAIMABLE",
            "ticket_id": ticket_id,
            "status": status,
        }
    doc["status"] = "processing"
    doc["claimed_at"] = time.time()
    doc.pop("retryable_error", None)
    _write_ticket(project_root, doc)
    return {"ok": True, "ticket": doc}


def mark_dispatch_ticket_consumed(project_root: Path, ticket_id: str) -> dict[str, Any]:
    """processing → consumed (only after finalize success)."""
    doc = load_dispatch_ticket(project_root, ticket_id)
    if not doc:
        return {"ok": False, "error": "TICKET_NOT_FOUND", "ticket_id": ticket_id}
    if str(doc.get("status") or "") != "processing":
        return {
            "ok": False,
            "error": "TICKET_NOT_PROCESSING",
            "ticket_id": ticket_id,
            "status": doc.get("status"),
        }
    doc["status"] = "consumed"
    doc["consumed_at"] = time.time()
    _write_ticket(project_root, doc)
    return {"ok": True, "ticket": doc}


def release_dispatch_ticket(
    project_root: Path,
    ticket_id: str,
    *,
    error: str = "",
) -> dict[str, Any]:
    """processing → retryable_failed → open so Host can resubmit return payload."""
    doc = load_dispatch_ticket(project_root, ticket_id)
    if not doc:
        return {"ok": False, "error": "TICKET_NOT_FOUND", "ticket_id": ticket_id}
    if str(doc.get("status") or "") != "processing":
        return {
            "ok": False,
            "error": "TICKET_NOT_PROCESSING",
            "ticket_id": ticket_id,
            "status": doc.get("status"),
        }
    doc["status"] = "retryable_failed"
    doc["retryable_error"] = (error or "")[:400]
    doc["failed_at"] = time.time()
    _write_ticket(project_root, doc)
    # Immediately re-open for retry (one-shot claim, multi-attempt finalize).
    doc["status"] = "open"
    doc["reopened_at"] = time.time()
    _write_ticket(project_root, doc)
    return {"ok": True, "ticket": doc, "retryable": True}


def consume_dispatch_ticket(project_root: Path, ticket_id: str) -> dict[str, Any]:
    """Backward-compatible alias: claim (does not finalize-consume).

    Prefer ``claim_dispatch_ticket`` + ``mark_dispatch_ticket_consumed``.
    """
    return claim_dispatch_ticket(project_root, ticket_id)


def _compact_dispatch_tasks(raw: Any) -> list[dict[str, str]]:
    """Keep focused Task stubs for Cursor-style fan-out (1+ bind rework; 2+ review)."""
    if not isinstance(raw, list) or not raw:
        return []
    out: list[dict[str, str]] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        stub = str(row.get("task_prompt_stub") or "").strip()
        if not stub:
            continue
        out.append(
            {
                "slice_id": str(row.get("slice_id") or ""),
                "focus": str(row.get("focus") or ""),
                "first_mode": str(row.get("first_mode") or ""),
                "actor_id": str(row.get("actor_id") or ""),
                "action_id": str(row.get("action_id") or ""),
                "task_prompt_stub": stub,
            }
        )
    if len(out) >= 2:
        return out
    if len(out) == 1 and str(out[0].get("slice_id") or "") in {"harness", "bind", "fix"}:
        return out
    return []


def _fanout_dispatch_message_zh(actor_id: str, tasks: list[dict[str, str]]) -> str:
    ids = ", ".join(t["slice_id"] for t in tasks if t.get("slice_id"))
    n = len(tasks)
    return (
        f"请在同一条回复里并行发出 {n} 个 OpenCode 原生 Task 子代理（agent={actor_id}）。"
        "每个 prompt 必须原样为 host_step.tasks[i].task_prompt_stub。"
        "禁止 session.create / 禁止开顶层新对话。不要用父 task_prompt_stub 再开一个。"
        "插件等全部切片返回后才 finalize（一张 ticket）；先回来的一轴不得结束本步。"
        "主控禁止等一个完成再派下一个。"
        "若已分两轮写完对应 parts，下一轮 pilot_run 从磁盘收齐，禁止重派、禁止 force_new。"
        "禁止只转述某一个，禁止发明子代理没引用的事实。"
        + (f" 切片：{ids}。" if ids else "")
    )


def build_host_step(
    *,
    kind: str,
    project_root: Path | str = "",
    action_id: str = "",
    actor_id: str = "",
    ticket: dict[str, Any] | None = None,
    prepare: dict[str, Any] | None = None,
    ask_question: dict[str, Any] | None = None,
    message_zh: str = "",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Structured Host Session Driver step."""
    prep = prepare or {}
    step: dict[str, Any] = {
        # dispatch_subagent | ask_human | done | failed | continue_goal
        "kind": kind,
        "action_id": action_id or str(prep.get("action_id") or ""),
        "actor_id": actor_id or str(prep.get("actor_id") or ""),
        "cwd": str(project_root or ""),
        "message_zh": message_zh,
    }
    if ticket:
        step["dispatch_ticket"] = str(ticket.get("ticket_id") or "")
        step["ticket"] = ticket
    if prep:
        step["task_prompt_stub"] = prep.get("task_prompt_stub") or ""
        step["session_dir"] = prep.get("session_dir") or ""
        step["lease_id"] = prep.get("lease_id") or ""
        step["run_id"] = prep.get("run_id") or ""
        step["finalize_hint"] = prep.get("finalize_hint") or ""
        tasks = _compact_dispatch_tasks(prep.get("dispatch_tasks"))
        if tasks:
            step["tasks"] = tasks
    if ask_question:
        step["ask_question"] = ask_question
    if extra:
        step.update(extra)
    return step


def dispatch_result(
    project_root: Path,
    *,
    ticket_id: str,
    action_result: dict[str, Any] | None = None,
    result_file: Path | str | None = None,
    result_text: str = "",
    slice_id: str = "",
) -> dict[str, Any]:
    """Claim ticket → finalize action → consume on success (else reopen) → drive.

    Fan-out tickets ACK each slice first; claim/finalize only when every expected
    slice has returned.
    """
    from ascendc_pilot.actions import run_action
    from ascendc_pilot.actions.drive import drive_until_interaction
    from ascendc_pilot.actions.runtime import prepare_action

    acked = ack_fanout_slice(
        project_root,
        ticket_id,
        result_text=result_text,
        slice_id=slice_id,
    )
    if acked.get("waiting_slices"):
        return acked
    if acked.get("ok") is False:
        return acked
    if acked.get("ready"):
        result_text = str(acked.get("combined_text") or result_text or "")
        ready_ticket = acked.get("ticket") or load_dispatch_ticket(project_root, ticket_id) or {}
        if str((ready_ticket or {}).get("action_id") or "") == "code_review":
            try:
                write_axis_merged_part(project_root, ready_ticket)
            except Exception:  # noqa: BLE001
                pass
        if action_result is None:
            action_result = {
                "fanout": True,
                "acked_slices": list(acked.get("acked_slices") or []),
                "result_text": result_text,
                "slice_results": acked.get("slice_results") or {},
            }

    claimed = claim_dispatch_ticket(project_root, ticket_id)
    if not claimed.get("ok"):
        return {**claimed, "ok": False}
    ticket = claimed.get("ticket") or {}
    action_id = str(ticket.get("action_id") or "").strip()
    if not action_id:
        release_dispatch_ticket(project_root, ticket_id, error="TICKET_MISSING_ACTION")
        return {"ok": False, "error": "TICKET_MISSING_ACTION"}

    payload = action_result
    if payload is None and result_text.strip():
        text = result_text.strip()
        if "```" in text:
            import re

            m = re.search(r"```(?:ya?ml)?\s*\n(.*?)```", text, re.S | re.I)
            if m:
                text = m.group(1).strip()
        try:
            if yaml is not None:
                parsed = yaml.safe_load(text)
                if isinstance(parsed, dict):
                    payload = parsed
        except Exception:  # noqa: BLE001
            payload = None

    fin = run_action(
        project_root,
        action_id,
        finalize=True,
        result_file=Path(result_file) if result_file else None,
        action_result=payload,
    )
    if not fin.get("ok"):
        release_dispatch_ticket(
            project_root,
            ticket_id,
            error=str(fin.get("error") or fin.get("message_zh") or "finalize failed"),
        )
        return {
            "ok": False,
            "stop_reason": "finalize_failed",
            "finalize": fin,
            "ticket_retryable": True,
            "dispatch_ticket": ticket_id,
            "host_step": build_host_step(
                kind="failed",
                project_root=project_root,
                action_id=action_id,
                message_zh=str(fin.get("message_zh") or fin.get("error") or "finalize failed"),
                extra={"ticket_retryable": True, "dispatch_ticket": ticket_id},
            ),
        }

    mark_dispatch_ticket_consumed(project_root, ticket_id)

    driven = drive_until_interaction(project_root, prepare=prepare_action)
    driven = attach_host_step(project_root, driven)
    return {
        "ok": bool(driven.get("ok")),
        "finalize": fin,
        "drive": driven,
        "host_step": driven.get("host_step"),
        "todo": driven.get("todo"),
    }


def _posix_abs(path: Path) -> str:
    return Path(path).expanduser().resolve().as_posix()


def _done_read_hint(project_root: Path, complete: dict[str, Any]) -> dict[str, Any]:
    """Point Primary at verify/query artifacts. Do not synthesize a summary here."""
    st = complete.get("state") if isinstance(complete.get("state"), dict) else {}
    if not st:
        try:
            from ascendc_pilot.state import load_state

            st = load_state(project_root) or {}
        except Exception:  # noqa: BLE001
            st = {}
    wid = str(st.get("workflow_id") or complete.get("workflow_id") or "")
    arch = str(st.get("architecture") or "").strip() or None
    run_id = str(st.get("run_id") or "").strip()
    hint: dict[str, Any] = {"workflow_id": wid}
    try:
        if wid in {"uo-init", "uo-update"}:
            stats = {}
            stats_zh = ""
            try:
                from uo_init.diagnostics.quality import load_product_ready_status
                from uo_init.store.reader import find_uo_product

                product = find_uo_product(project_root, architecture=str(arch or ""))
                stats = load_product_ready_status(product)
                if not stats and arch:
                    from ascendc_pilot.paths import uo_root

                    stats = load_product_ready_status(uo_root(project_root, arch=arch))
                if stats.get("grade") is not None:
                    stats_zh = (
                        f"grade={stats.get('grade')}，节点 {stats.get('entity_count')}，"
                        f"关系 {stats.get('relation_count')}，未闭合 {stats.get('unresolved_total')}"
                        f"（locate_blocking={stats.get('locate_blocking')}）。"
                    )
            except Exception:  # noqa: BLE001
                stats = {}
                stats_zh = ""
            prefix = "建库已完成。" + (stats_zh if stats_zh else "")
            hint["message_zh"] = (
                f"{prefix}用 `pilot_cli` `uo-query --status-only` 查看产物是否就绪"
                "（节点/关系/未闭合）。禁止打开 .uo 二进制，禁止仅回复「完成」。"
                "勾掉当前 Todo 后由 Primary `pilot_run` 下一格，不要把建库结束当成整个目标完成。"
            )
            hint.update(stats)
        elif wid == "uo-query" and run_id:
            hint["message_zh"] = (
                "查询完成。请将本次子代理返回的答案正文向用户陈述。"
                "禁止再 Glob/Read yaml。"
            )
    except Exception:  # noqa: BLE001
        pass
    return hint


def _hosted_interaction_envelope(out: dict[str, Any]) -> dict[str, Any]:
    """Prefer the envelope prepare already issued (plan_approve / confirm)."""
    req = out.get("human_interaction_request")
    if isinstance(req, dict) and str(req.get("request_id") or "").strip():
        return req
    prep = out.get("prepare") if isinstance(out.get("prepare"), dict) else {}
    req = prep.get("human_interaction_request")
    return req if isinstance(req, dict) else {}


def attach_host_step(
    project_root: Path,
    drive_payload: dict[str, Any],
    *,
    reenter_drive: bool = True,
) -> dict[str, Any]:
    """Augment drive_until_interaction output with structured host_step + ticket."""
    depth = int(getattr(_ATTACH_DEPTH, "n", 0) or 0)
    if depth > 0:
        reenter_drive = False
    _ATTACH_DEPTH.n = depth + 1
    try:
        return _attach_host_step_body(
            project_root, drive_payload, reenter_drive=reenter_drive
        )
    finally:
        _ATTACH_DEPTH.n = depth


def _attach_host_step_body(
    project_root: Path,
    drive_payload: dict[str, Any],
    *,
    reenter_drive: bool,
) -> dict[str, Any]:
    out = dict(drive_payload or {})
    existing = out.get("host_step")
    if isinstance(existing, dict) and str(existing.get("kind") or "").strip():
        return out
    stop = str(out.get("stop_reason") or "")
    status = str(out.get("status") or "")

    if stop == "workflow_complete" or status == "passed":
        complete = out.get("complete") if isinstance(out.get("complete"), dict) else {}
        next_wf = str(
            complete.get("user_goal_next_workflow_id")
            or out.get("user_goal_next_workflow_id")
            or ""
        ).strip()
        acceptance_failed = bool(
            complete.get("user_goal_acceptance_failed")
            or out.get("user_goal_acceptance_failed")
        )
        if acceptance_failed and not next_wf:
            fail_zh = str(
                complete.get("user_goal_next_summary_zh")
                or complete.get("message_zh")
                or out.get("message_zh")
                or "目标尚未完成：缺少回放验证收据，或测试义务未闭合。"
            )
            out["host_step"] = build_host_step(
                kind="failed",
                project_root=project_root,
                message_zh=fail_zh,
                extra={
                    "status": "failed",
                    "reason_code": "GOAL_ACCEPTANCE_FAILED",
                    "acceptance_failed": True,
                },
            )
            out["message_zh"] = fail_zh
            return out
        from ascendc_pilot.pin_facts import apply_pin_to_payload, host_step_pin_extra
        from ascendc_pilot.state import load_state as _load_pin_state

        live_state: dict[str, Any] = {}
        try:
            live_state = _load_pin_state(project_root) or {}
        except Exception:  # noqa: BLE001
            live_state = {}
        pin_payload = apply_pin_to_payload(
            {}, complete, complete.get("state"), live_state
        )
        if next_wf:
            arch = ""
            intent = ""
            project_from_goal = ""
            try:
                from ascendc_pilot.public_progress import message_zh_for_host
                from ascendc_pilot.user_goal import load_user_goal

                complete_st = (
                    complete.get("state") if isinstance(complete.get("state"), dict) else {}
                )
                goal = load_user_goal(project_root) or {}
                arch = str(goal.get("architecture") or "").strip()
                if not arch:
                    arch = str(complete_st.get("architecture") or "").strip()
                if not arch:
                    from ascendc_pilot.state import load_state

                    arch = str((load_state(project_root) or {}).get("architecture") or "").strip()
                if arch == "goal":
                    arch = ""
                intent_doc = goal.get("intent") if isinstance(goal.get("intent"), dict) else {}
                intent = str(
                    intent_doc.get("text")
                    or goal.get("intent_text")
                    or goal.get("label_zh")
                    or ""
                ).strip()
                project_from_goal = str(goal.get("project") or "").strip()
            except Exception:  # noqa: BLE001
                pass
            msg = str(
                complete.get("user_goal_next_summary_zh")
                or complete.get("message_zh")
                or ""
            )
            try:
                from ascendc_pilot.public_progress import message_zh_for_host

                pub = message_zh_for_host(project_root)
                if pub:
                    msg = pub
            except Exception:  # noqa: BLE001
                pass
            out["host_step"] = build_host_step(
                kind="continue_goal",
                project_root=project_root,
                message_zh=msg or f"continue goal → {next_wf}",
                extra={
                    "status": status or "passed",
                    "next_workflow_id": next_wf,
                    "architecture": arch or pin_payload.get("architecture") or "",
                    "intent": intent,
                    "project": str(project_from_goal or pin_payload.get("project") or ""),
                    "completed_workflow_id": str(
                        (complete.get("state") or {}).get("workflow_id")
                        if isinstance(complete.get("state"), dict)
                        else ""
                    ),
                    **host_step_pin_extra(pin_payload),
                },
            )
            return out
        done = _done_read_hint(project_root, complete)
        extra: dict[str, Any] = {"status": status or "passed"}
        extra.update(host_step_pin_extra(pin_payload))
        extra.update({k: v for k, v in done.items() if k != "message_zh"})
        hint_zh = str(done.get("message_zh") or "").strip()
        out["host_step"] = build_host_step(
            kind="done",
            project_root=project_root,
            message_zh=str(
                hint_zh
                or pin_payload.get("message_zh")
                or complete.get("message_zh")
                or out.get("message_zh")
                or "workflow complete"
            ),
            extra=extra,
        )
        out["message_zh"] = str(out["host_step"].get("message_zh") or "")
        return out

    if stop in {"deterministic_action_failed", "advance_failed", "completion_gate_failed"} or (
        out.get("ok") is False and stop not in {"interaction_required", "workflow_status"}
    ):
        from ascendc_pilot.actions.failure_text import (
            preferred_failure_text,
            with_failure_hint,
        )

        fail = out.get("failure") if isinstance(out.get("failure"), dict) else {}
        eng = fail.get("engine") if isinstance(fail.get("engine"), dict) else {}
        detail = with_failure_hint(
            preferred_failure_text(out, fallback=str(stop or "deterministic_action_failed")),
            out,
        )
        error_detail = preferred_failure_text(
            {"engine": eng, "failure": fail, "error": out.get("error")},
            fallback=str(out.get("error") or ""),
        )
        hint_zh = str(out.get("hint_zh") or "")
        out["message_zh"] = detail
        if not str(out.get("error") or "").strip():
            out["error"] = error_detail or stop
        extra = {
            "stop_reason": stop,
            "failed_action": out.get("failed_action") or "",
            "error_detail": error_detail or detail,
        }
        if hint_zh:
            extra["hint_zh"] = hint_zh
        issues = fail.get("issues") or eng.get("issues") or out.get("issues")
        if issues:
            extra["issues"] = issues
        unresolved = out.get("unresolved")
        if unresolved is None:
            prep = out.get("prepare") if isinstance(out.get("prepare"), dict) else {}
            unresolved = prep.get("unresolved")
        if unresolved:
            extra["unresolved"] = unresolved
            try:
                from ascendc_pilot.observation import record_prepare_failure

                record_prepare_failure(
                    project_root,
                    action_id=str(out.get("failed_action") or ""),
                    result={
                        "error": out.get("error") or error_detail,
                        "message_zh": detail,
                        "unresolved": unresolved,
                    },
                )
            except Exception:
                pass
        out["host_step"] = build_host_step(
            kind="failed",
            project_root=project_root,
            action_id=str(out.get("failed_action") or ""),
            message_zh=detail,
            extra=extra,
        )
        return out

    nxt_preview = out.get("next") if isinstance(out.get("next"), dict) else {}
    hosted_env = _hosted_interaction_envelope(out)
    hosted_exec = str(nxt_preview.get("execution_kind") or "") in {
        "primary_interactive",
        "primary_review",
    }
    hosted_kind = str(hosted_env.get("kind") or "") in {
        "primary_approve",
        "primary_confirm",
        "resume",
    }
    # Intake/harness AskQuestion only. Host-owned plan_approve already attached
    # primary_approve in prepare; rewriting it as intake/test_script_root makes
    # require_decision_receipt return HUMAN_DECISION_RECEIPT_KIND_MISMATCH.
    if (not hosted_exec and not hosted_kind) and (
        out.get("ask_question")
        or (
            stop == "interaction_required"
            and status in {
                "human_required",
                "waiting_for_confirmation",
            }
        )
    ):
        ask = out.get("ask_question") if isinstance(out.get("ask_question"), dict) else None
        nxt = nxt_preview
        if ask:
            from ascendc_pilot.human_interaction import attach_interaction_request

            field = str(ask.get("field") or "")
            out = attach_interaction_request(
                out,
                project_root,
                kind="harness" if field == "test_script_root" else "intake",
                action_id=str(nxt.get("action_id") or out.get("failed_action") or "repo_scan"),
                decision_kind=field or str(out.get("decision_kind") or "test_script_root"),
            )
            req = out.get("human_interaction_request") if isinstance(out.get("human_interaction_request"), dict) else {}
            rid = str(req.get("request_id") or "")
            if rid:
                ask = dict(ask)
                ask["request_id"] = rid
                out["ask_question"] = ask
        extra_ask: dict[str, Any] = {"status": status, "stop_reason": stop}
        req = out.get("human_interaction_request") if isinstance(out.get("human_interaction_request"), dict) else {}
        if req.get("request_id"):
            extra_ask["request_id"] = str(req.get("request_id"))
        out["host_step"] = build_host_step(
            kind="ask_human",
            project_root=project_root,
            action_id=str(nxt.get("action_id") or ""),
            ask_question=out.get("ask_question") if isinstance(out.get("ask_question"), dict) else None,
            message_zh=str(out.get("message_zh") or "human interaction required"),
            extra=extra_ask,
        )
        return out

    nxt = out.get("next") if isinstance(out.get("next"), dict) else {}
    kind = str(nxt.get("execution_kind") or "")
    action_id = str(nxt.get("action_id") or "").strip()
    actor_id = str(nxt.get("actor_id") or "").strip()

    if stop == "interaction_required" and kind in {"subagent", "primary_interactive", "primary_review"} and action_id:
        from ascendc_pilot.actions.runtime import prepare_action
        from ascendc_pilot.state import load_state

        existing_prep = out.get("prepare") if isinstance(out.get("prepare"), dict) else {}
        existing_ask = out.get("ask_question") if isinstance(out.get("ask_question"), dict) else None
        if not existing_ask and isinstance(existing_prep.get("ask_question"), dict):
            existing_ask = existing_prep.get("ask_question")
        if kind == "primary_interactive" and (existing_ask or existing_prep.get("needs_human_decision")):
            env = _hosted_interaction_envelope(out)
            if env:
                out["human_interaction_request"] = env
            if env.get("request_id") and isinstance(existing_ask, dict):
                existing_ask = dict(existing_ask)
                existing_ask["request_id"] = str(env["request_id"])
                out["ask_question"] = existing_ask
            extra_hosted: dict[str, Any] = {}
            if env.get("request_id"):
                extra_hosted["request_id"] = str(env["request_id"])
            out["host_step"] = build_host_step(
                kind="ask_human",
                project_root=project_root,
                action_id=action_id,
                actor_id=actor_id or str(existing_prep.get("actor_id") or ""),
                prepare=existing_prep or None,
                ask_question=existing_ask,
                message_zh=str(
                    out.get("message_zh")
                    or existing_prep.get("message_zh")
                    or "primary interactive"
                ),
                extra=extra_hosted or None,
            )
            if existing_prep:
                out["prepare"] = existing_prep
            return out

        def _drive_again() -> dict[str, Any] | None:
            if not reenter_drive:
                return None
            from ascendc_pilot.actions.drive import drive_until_interaction

            return drive_until_interaction(project_root, prepare=prepare_action)

        def _drain_after_auto() -> dict[str, Any]:
            """PASS / REWORK / consumed ticket: keep draining even if we arrived
            from drive._done(reenter_drive=False). Nested attach (depth>1) must
            not drain again — that re-dispatches a finished action."""
            again = _drive_again()
            if again is not None:
                return again
            depth_now = int(getattr(_ATTACH_DEPTH, "n", 0) or 0)
            if depth_now > 1:
                out["host_step"] = build_host_step(
                    kind="failed",
                    project_root=project_root,
                    action_id=action_id,
                    actor_id=actor_id,
                    message_zh=(
                        f"`{action_id}` 已结束或 ticket 已消费，但推荐下一步仍是它。"
                        "禁止重派。请 `pilot_run` 当前工作流让引擎选下一步。"
                    ),
                )
                return out
            from ascendc_pilot.actions.drive import drive_until_interaction

            return drive_until_interaction(project_root, prepare=prepare_action)

        def _primary_review_host_step(prep: dict[str, Any]) -> dict[str, Any]:
            extra_review = {
                "harness_path": str(prep.get("harness_path") or ""),
                "bind_path": str(prep.get("bind_path") or ""),
                "verdict_path": str(prep.get("verdict_path") or ""),
            }
            unresolved = prep.get("unresolved") or []
            if unresolved:
                extra_review["unresolved"] = unresolved
            if prep.get("error"):
                extra_review["error_detail"] = str(prep.get("error") or "")
            review_msg = str(prep.get("message_zh") or "")
            if action_id == "plan_ingest":
                review_msg = review_msg or (
                    "主控原生 Task 派 Plan Owner；下一发 intent 交 tg-plan/v3 YAML，不要自己写 plan.md"
                )
            else:
                review_msg = review_msg or "主控通读两路草稿；下一发 PASS 或 REWORK"
            out["host_step"] = build_host_step(
                kind="primary_review",
                project_root=project_root,
                action_id=action_id,
                actor_id=actor_id or str(prep.get("actor_id") or "ascendc-pilot"),
                prepare=prep,
                message_zh=review_msg,
                extra=extra_review,
            )
            out["prepare"] = prep
            return out

        if kind == "primary_review" and existing_prep:
            if existing_prep.get("ok") is False:
                unresolved = existing_prep.get("unresolved") or []
                msg = str(
                    existing_prep.get("message_zh")
                    or existing_prep.get("error")
                    or "prepare failed"
                )
                try:
                    from ascendc_pilot.observation import record_prepare_failure

                    record_prepare_failure(
                        project_root,
                        action_id=action_id,
                        result=existing_prep,
                    )
                except Exception:
                    pass
                extra_fail: dict[str, Any] = {"prepare": existing_prep}
                if unresolved:
                    extra_fail["unresolved"] = unresolved
                extra_fail["error_detail"] = str(existing_prep.get("error") or "")
                out["host_step"] = build_host_step(
                    kind="failed",
                    project_root=project_root,
                    action_id=action_id,
                    actor_id=actor_id or str(existing_prep.get("actor_id") or "ascendc-pilot"),
                    message_zh=msg,
                    extra=extra_fail,
                )
                out["prepare"] = existing_prep
                out["unresolved"] = unresolved
                return out
            if existing_prep.get("auto_finalize") or existing_prep.get("continue_drive"):
                return _drain_after_auto()
            return _primary_review_host_step(existing_prep)

        run_id = str((load_state(project_root) or {}).get("run_id") or "").strip()
        live = find_dispatch_ticket_for_action(
            project_root, run_id=run_id, action_id=action_id
        )
        live_status = str((live or {}).get("status") or "")
        if live and live_status == "consumed":
            return _drain_after_auto()
        if live and live_status in {"processing", "blocked_repeat_failure"}:
            out["dispatch_ticket"] = str(live.get("ticket_id") or "")
            out["prepare"] = {"run_id": run_id, "action_id": action_id, "reused_ticket": True}
            out["host_step"] = build_host_step(
                kind="failed" if live_status == "blocked_repeat_failure" else "dispatch_subagent",
                project_root=project_root,
                action_id=action_id,
                actor_id=actor_id,
                ticket=live,
                message_zh="已有 dispatch ticket，禁止重发。",
            )
            return out
        if live and live_status in {"open", "collecting"}:
            live = harvest_parts_into_ticket(project_root, live)
            expected = _expected_slices(live)
            results = dict(live.get("slice_results") or {})
            remaining_ids = [s for s in expected if s not in results]
            if remaining_ids:
                remaining_tasks = _remaining_dispatch_tasks(live, results)
                out["host_step"] = _waiting_fanout_host_step(
                    project_root, live, remaining_tasks, remaining_ids
                )
                out["dispatch_ticket"] = str(live.get("ticket_id") or "")
                out["prepare"] = {"run_id": run_id, "action_id": action_id, "reused_ticket": True}
                return out
            if expected:
                if action_id == "code_review":
                    write_axis_merged_part(project_root, live)
                return dispatch_result(
                    project_root,
                    ticket_id=str(live.get("ticket_id") or ""),
                    result_text="harvest",
                    slice_id="",
                )

        prep = prepare_action(project_root, action_id)
        if not prep.get("ok"):
            out["host_step"] = build_host_step(
                kind="failed",
                project_root=project_root,
                action_id=action_id,
                actor_id=actor_id,
                message_zh=str(prep.get("message_zh") or prep.get("error") or "prepare failed"),
                extra={"prepare": prep},
            )
            out["prepare"] = prep
            return out

        if prep.get("auto_skip_human_gate") and prep.get("auto_finalize"):
            return _drain_after_auto()

        if prep.get("continue_drive"):
            return _drain_after_auto()

        if prep.get("reuse_host_step") and isinstance(prep.get("host_step"), dict):
            out["host_step"] = prep["host_step"]
            out["prepare"] = prep
            return out

        if kind == "primary_review" and prep.get("ok") and prep.get("auto_finalize"):
            return _drain_after_auto()

        if kind == "primary_review" or str(prep.get("host_step_kind") or "") == "primary_review":
            return _primary_review_host_step(prep)

        if kind == "primary_interactive" or prep.get("needs_human_decision"):
            out["host_step"] = build_host_step(
                kind="ask_human",
                project_root=project_root,
                action_id=action_id,
                actor_id=actor_id or str(prep.get("actor_id") or ""),
                prepare=prep,
                ask_question=prep.get("ask_question")
                if isinstance(prep.get("ask_question"), dict)
                else out.get("ask_question"),
                message_zh=str(prep.get("message_zh") or "primary interactive"),
            )
            out["prepare"] = prep
            return out

        merged = Path(str(prep.get("session_dir") or "")) / "parts" / "merged.md"
        if merged.is_file():
            live2 = find_dispatch_ticket_for_action(
                project_root,
                run_id=str(prep.get("run_id") or run_id),
                action_id=action_id,
            )
            live2_status = str((live2 or {}).get("status") or "")
            if live2 and live2_status in {"open", "collecting"}:
                write_axis_merged_part(project_root, live2)
                return dispatch_result(
                    project_root,
                    ticket_id=str(live2.get("ticket_id") or ""),
                    result_text="harvest",
                    slice_id="",
                )
            # Parts already merged; never issue a second ticket from drive._done.
            return _drain_after_auto()

        tasks = _compact_dispatch_tasks(prep.get("dispatch_tasks"))
        ticket = issue_dispatch_ticket(
            project_root,
            run_id=str(prep.get("run_id") or ""),
            action_id=action_id,
            actor_id=str(prep.get("actor_id") or actor_id),
            lease_id=str(prep.get("lease_id") or ""),
            session_dir=str(prep.get("session_dir") or ""),
            task_prompt_stub=str(prep.get("task_prompt_stub") or ""),
            prepare_nonce=str(prep.get("prepare_nonce") or ""),
            workflow_id=str(prep.get("workflow_id") or ""),
            expected_slices=[str(t.get("slice_id") or "") for t in tasks if t.get("slice_id")],
            dispatch_tasks=tasks,
        )
        actor = str(prep.get("actor_id") or actor_id)
        if tasks:
            dispatch_msg = str(prep.get("message_zh") or "") or _fanout_dispatch_message_zh(
                actor, tasks
            )
        else:
            dispatch_msg = str(
                prep.get("message_zh")
                or (
                    f"请用 OpenCode 原生 Task（agent={actor}）"
                    "原样派发 task_prompt_stub；可打开 Task 卡片查看子会话推理过程。禁止改写 stub。"
                )
            )
        out["host_step"] = build_host_step(
            kind="dispatch_subagent",
            project_root=project_root,
            action_id=action_id,
            actor_id=actor,
            ticket=ticket,
            prepare=prep,
            message_zh=dispatch_msg,
        )
        out["prepare"] = prep
        out["dispatch_ticket"] = ticket.get("ticket_id")
        return out

    out["host_step"] = build_host_step(
        kind="failed",
        project_root=project_root,
        message_zh=str(out.get("message_zh") or stop or "drive stopped"),
        extra={"stop_reason": stop, "status": status},
    )
    return out


__all__ = [
    "issue_dispatch_ticket",
    "load_dispatch_ticket",
    "find_dispatch_ticket_for_action",
    "harvest_parts_into_ticket",
    "write_axis_merged_part",
    "claim_dispatch_ticket",
    "mark_dispatch_ticket_consumed",
    "release_dispatch_ticket",
    "consume_dispatch_ticket",
    "ack_fanout_slice",
    "reopen_fanout_slices",
    "discard_dispatch_tickets_for_action",
    "infer_slice_id",
    "build_host_step",
    "dispatch_result",
    "attach_host_step",
]
