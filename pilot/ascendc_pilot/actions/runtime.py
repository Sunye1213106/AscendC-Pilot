"""Two-phase Action runtime: prepare → (actor) → finalize."""

from __future__ import annotations

import hashlib
import re
import secrets
import shutil
from contextvars import ContextVar, Token
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

from ascendc_pilot.actions.engines import (
    OUTPUT_CONTRACT_MATCH_ANY,
    OUTPUT_CONTRACT_NONEMPTY_GLOBS,
    OUTPUT_CONTRACT_PATHS,
    invoke_engine,
)
from ascendc_pilot.paths import (
    agent_root,
    discover_arch,
    ensure_control_layout,
    ensure_tg_layout,
    require_architecture,
    runs_root,
    tg_root,
    uo_root,
)
from ascendc_pilot.runs import append_event, file_sha256, issue_receipt, run_dir
from ascendc_pilot.state import load_state
from ascendc_pilot.workflows import actions_for_phase, get_workflow

_TURN_INTENT: ContextVar[str] = ContextVar("acp_turn_intent", default="")


def bind_turn_intent(text: str) -> Token[str]:
    return _TURN_INTENT.set(str(text or ""))


def current_turn_intent() -> str:
    return str(_TURN_INTENT.get() or "")


def _run_action_gates(
    project_root: Path,
    gate_ids: list[str],
) -> list[dict[str, Any]]:
    """Run named gates and persist outcomes. Empty list → no-op."""
    from ascendc_pilot.gates import run_named_gate
    from ascendc_pilot.state import record_gate

    results: list[dict[str, Any]] = []
    for gid in gate_ids:
        name = str(gid or "").strip()
        if not name:
            continue
        g = run_named_gate(project_root, name)
        results.append(g)
        try:
            record_gate(
                project_root,
                str(g.get("gate") or name),
                ok=bool(g.get("ok")),
                detail=g if isinstance(g, dict) else None,
                bump=False,
            )
        except Exception:  # noqa: BLE001
            pass
    return results



def _arch_for(project_root: Path, state: dict[str, Any] | None = None) -> str:
    if state is not None:
        arch = str(state.get("architecture") or "").strip()
        if arch:
            return arch
    return discover_arch(project_root)


def _write_active_action(project_root: Path, payload: dict[str, Any]) -> Path:
    """Persist current action context for OpenCode plugin / subagent writes."""
    from ascendc_pilot.authorize.lease import active_action_path

    arch = str(payload.get("architecture") or "").strip() or None
    try:
        arch = discover_arch(project_root) if arch is None else require_architecture(arch)
    except ValueError:
        arch = None
    run_id = str(payload.get("run_id") or "").strip()
    path = active_action_path(project_root, run_id=run_id, arch=arch)
    _dump(path, payload)
    return path


LIST_STATE_KEYS = ("targets", "constraints")
REQUIRED_NONEMPTY_STATE_KEYS = frozenset({"intent"})


def _pilot_params(project_root: Path | None, state: dict[str, Any]) -> dict[str, Any]:
    if project_root is None:
        return {}
    try:
        from ascendc_pilot.paths import context_root, discover_arch

        arch = str(state.get("architecture") or "").strip() or discover_arch(project_root)
        return _load_yaml_file(context_root(project_root, arch=arch) / "pilot_params.yaml")
    except Exception:  # noqa: BLE001
        return {}


def _eng_ctx_from_state(
    state: dict[str, Any],
    run_id: str,
    *,
    consumes_state: list[str] | None = None,
    project_root: Path | None = None,
) -> dict[str, Any]:
    params = _pilot_params(project_root, state)
    architecture = str(state.get("architecture") or params.get("architecture") or "").strip()
    if not architecture:
        return {
            "ok": False,
            "reason_code": "ARCHITECTURE_MISSING_IN_RUN_STATE",
            "error": "ARCHITECTURE_MISSING_IN_RUN_STATE",
        }
    picked_tsr = str(state.get("test_script_root") or params.get("test_script_root") or "")
    if str(state.get("workflow_id") or "") == "tg-init":
        confirmed_url = str(state.get("test_script_root") or "").strip()
        if state.get("test_script_confirmed") and confirmed_url:
            test_script_root = confirmed_url
        elif project_root is not None:
            from ascendc_pilot.human_interaction import (
                peek_confirmed_harness,
                resolved_test_script_root,
            )

            test_script_root = resolved_test_script_root(project_root, picked_tsr)
            if not str(test_script_root or "").strip():
                test_script_root = peek_confirmed_harness(project_root)
        else:
            test_script_root = ""
        if not str(test_script_root or "").strip():
            test_script_root = ""
    else:
        test_script_root = picked_tsr
    ctx: dict[str, Any] = {
        "run_id": run_id,
        "op_name": state.get("op_name") or params.get("op_name") or "",
        "architecture": architecture,
        "arch_dir": architecture,
        "workflow_id": str(state.get("workflow_id") or ""),
        "test_script_root": test_script_root,
        "level": state.get("level") or params.get("level") or "L0",
        "focus": state.get("focus") or params.get("focus") or "",
    }
    declared = [str(k).strip() for k in (consumes_state or []) if str(k).strip()]
    for key in declared:
        if key in ctx:
            continue
        if key in LIST_STATE_KEYS:
            raw = state.get(key)
            ctx[key] = list(raw) if isinstance(raw, list) else []
            continue
        value = state.get(key)
        if key == "description" and value in (None, ""):
            value = state.get("intent") or ""
        if key == "intent" and value in (None, ""):
            value = state.get("description") or ""
        ctx[key] = "" if value is None else value
        if key == "intent" and ctx.get("description") in (None, ""):
            ctx["description"] = ctx["intent"]
    for key in declared:
        if key not in REQUIRED_NONEMPTY_STATE_KEYS:
            continue
        if str(ctx.get(key) or "").strip():
            continue
        code = f"{key.upper()}_MISSING_IN_RUN_STATE"
        return {
            "ok": False,
            "reason_code": code,
            "error": code,
            "message_zh": f"run state 缺少引擎必需字段 {key}",
        }
    return ctx



def _dump(path: Path, data: dict[str, Any]) -> None:
    if yaml is None:
        raise RuntimeError("PyYAML required")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _load(path: Path) -> dict[str, Any]:
    if yaml is None or not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


# Mutable execution overlay. Identity/contract live in bundle.yaml.
SESSION_STATE_FILENAME = "session_state.yaml"
SESSION_STATE_LEGACY = "session.yaml"
_SESSION_STATE_KEYS = (
    "status",
    "lease_id",
    "prepare_nonce",
    "action_session_id",
    "run_id",
    "action_id",
    "actor_id",
    "role_id",
    "workflow_id",
    "phase",
    "execution_mode",
    "output_contract_id",
    "output_mode",
    "identity",
    "prepared_at",
    "finalized_at",
    "dispatch_id",
    "result_digest",
    "failure",
    "engine",
    "receipt",
    "checker_result",
    "bundle_digest",
    "captured_result",
)


def _session_state_from_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    row = {"kind": "session_state", "version": 1}
    for key in _SESSION_STATE_KEYS:
        if key in bundle:
            row[key] = bundle[key]
    return row


def _session_overlay_path(sdir: Path) -> Path:
    modern = Path(sdir) / SESSION_STATE_FILENAME
    legacy = Path(sdir) / SESSION_STATE_LEGACY
    if modern.is_file() or not legacy.is_file():
        return modern
    return legacy


def _capture_return_value(
    *,
    result_file: Path | str | None = None,
    action_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist a subagent return_value into the Action session (not a TG product)."""
    text = ""
    doc: dict[str, Any] | None = None
    if result_file:
        path = Path(result_file)
        if path.is_file():
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                text = ""
    payload = action_result if isinstance(action_result, dict) else {}
    if not text:
        for key in ("result_text", "text", "body", "markdown", "content", "answer_zh", "answer"):
            raw = payload.get(key) if payload else None
            if raw:
                text = str(raw)
                break
    if not text and isinstance(action_result, str):
        text = action_result
    keep_keys = (
        "requirement",
        "targets",
        "guards",
        "candidate_dimensions",
        "schema",
        "columns",
        "rows",
        "recipe",
        "refinement",
        "coverage",
        "dimensions",
    )
    if payload and any(k in payload for k in keep_keys):
        doc = {k: payload[k] for k in payload if k in keep_keys or k in {"construct_hint", "untestable"}}
        if not text:
            try:
                import yaml as _yaml

                text = _yaml.safe_dump(doc, allow_unicode=True, sort_keys=False)
            except Exception:  # noqa: BLE001
                text = str(doc)
    if not text and not doc:
        return {}
    return {"text": str(text or ""), "doc": doc or {}}


def _scope_answer_for_fuse(captured: dict[str, Any]) -> str:
    """plan_scope is uo-query-like: natural language only. Prefer captured text."""
    body = str((captured or {}).get("text") or "").strip()
    if body:
        return body
    doc = (captured or {}).get("doc")
    if isinstance(doc, dict) and doc:
        try:
            import yaml as _yaml

            return str(_yaml.safe_dump(doc, allow_unicode=True, sort_keys=False) or "").strip()
        except Exception:  # noqa: BLE001
            return str(doc).strip()
    return ""


def _load_tg_captured(project_root: Path, run_id: str, action_id: str) -> dict[str, Any]:
    sdir = _session_dir(project_root, run_id, action_id)
    captured = _load(sdir / "captured.yaml")
    if captured:
        return captured
    session = _load_action_session(sdir)
    row = session.get("captured_result")
    return row if isinstance(row, dict) else {}


def _dump_session_state(sdir: Path, bundle: dict[str, Any]) -> None:
    _dump(Path(sdir) / SESSION_STATE_FILENAME, _session_state_from_bundle(bundle))


def _load_action_session(sdir: Path) -> dict[str, Any]:
    """Merge immutable bundle + mutable session overlay."""
    merged = dict(_load(sdir / "bundle.yaml"))
    overlay = _load(_session_overlay_path(sdir))
    if overlay:
        merged.update(overlay)
    return merged


def _repo_root(project_root: Path) -> Path:
    root = Path(project_root).resolve()
    if (root / "skills").is_dir():
        return root
    here = Path(__file__).resolve().parents[3]
    if (here / "skills").is_dir():
        return here
    return root


def _action_spec(
    workflow_id: str,
    action_id: str,
    phase: str,
    *,
    project_root: Path | None = None,
) -> dict[str, Any] | None:
    allowed = actions_for_phase(workflow_id, phase, project_root=project_root)
    for row in allowed:
        if str(row.get("id") or "") == action_id:
            return row
    # Also allow lookup in full workflow for clearer error messages
    meta = get_workflow(workflow_id, project_root=project_root)
    for row in meta.get("actions") or []:
        if isinstance(row, dict) and str(row.get("id") or "") == action_id:
            return {**row, "_not_in_phase": True}
    return None


def _session_dir(project_root: Path, run_id: str, action_id: str) -> Path:
    return run_dir(project_root, run_id) / "actions" / action_id


def _load_yaml_file(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}




def _render_placeholders(
    text: str,
    *,
    run_id: str,
    action_id: str,
    workflow_id: str,
    actor_id: str,
    project_root: str = "",
    uo_root: str = "",
    tg_root_path: str = "",
    topic: str = "",
    op_name: str = "",
    target: str = "",
    architecture: str = "",
    role_id: str = "",
    lease_id: str = "",
    action_session_id: str = "",
    candidates_sha256: str = "",
    shard_id: str = "",
    **_ignored: Any,
) -> str:
    repl = {
        "<RUN_ID>": run_id,
        "<ACTION_ID>": action_id,
        "<WORKFLOW_ID>": workflow_id,
        "<ACTOR_ID>": actor_id,
        "<TARGET_IDS_OR_FILES>": target or "(see human input)",
        "<TARGET>": target or "(see dispatch_targets / batch file)",
        "<SHARD_ID>": shard_id or "(see dispatch_tasks[].shard_id)",
        "<OP_NAME>": op_name,
        "<PROJECT_ROOT>": project_root,
        "<UO_ROOT>": uo_root,
        "<TG_ROOT>": tg_root_path,
        "<TOPIC>": topic,
        "<ARCHITECTURE>": architecture or "[UNRESOLVED:ARCHITECTURE]",
        "<ROLE_ID>": role_id,
        "<LEASE_ID>": lease_id,
        "<ACTION_SESSION_ID>": action_session_id,
        "<CANDIDATES_SHA256>": candidates_sha256
        or "(copy from task_prompt_stub candidates_sha256=…)",
    }
    out = text
    for k, v in repl.items():
        out = out.replace(k, v)
    # Angle-bracket leftovers that look like template tokens → mark unresolved
    out = re.sub(r"<([A-Z][A-Z0-9_]{2,})>", r"[UNRESOLVED:\1]", out)
    return out


def build_task_stub(
    *,
    actor_id: str,
    action_id: str,
    run_id: str,
    session_dir: str,
    prompt_path: str,
    method_path: str,
    bundle_path: str,
    dispatch_targets: dict[str, Any] | None = None,
    agent_root_path: str = "",
    project_root: str = "",
    architecture: str = "",
    candidates_sha256: str = "",
    environment_path: str = "",
    write_paths: list[str] | None = None,
    user_question: str = "",
) -> tuple[str, Any]:
    """Minimal Host→subagent Task body + typed pointers. Stub is human-readable."""
    from ascendc_pilot.actions.method_bundle import TaskStubPointers
    lines = [
        f"action_id={action_id}",
        f"actor_id={actor_id}",
        f"run_id={run_id}",
        "Follow ONLY these session files (read them first; do not invent extra goals):",
        f"  prompt: {prompt_path}",
        f"  method: {method_path}",
        f"  bundle: {bundle_path}",
        f"session_dir: {session_dir}",
    ]
    if project_root:
        lines.append(
            f"pilot_cli commands must pass --project {project_root} "
            "(Host cwd is the Pilot checkout; always this absolute operator path, not the op name alone)"
        )
    dt = dispatch_targets or {}
    root = str(agent_root_path or "").rstrip("/\\")

    def _abs_under_agent(rel: str) -> str:
        r = str(rel or "").replace("\\", "/").lstrip("/")
        if not r or not root:
            return r
        if r.lower().startswith(root.replace("\\", "/").lower()):
            return r
        return f"{Path(root).as_posix()}/{r}"

    if dt.get("read"):
        # Absolute paths under .ascendc-pilot — relative ``uo/ir/...`` is often
        # misread as ``<op>/uo/ir/...`` (missing .ascendc-pilot) by subagents.
        lines.append("read: " + ", ".join(_abs_under_agent(str(x)) for x in dt["read"]))
    write_list = list(dt.get("write") or []) or list(write_paths or [])
    if action_id == "kb_lookup":
        # return_value: Explorer must not Write. Dialogue contract only.
        lines.append(
            "write: (none — Explorer return_value only; do not Write answer.yaml)"
        )
    elif write_list:
        lines.append("write: " + ", ".join(_abs_under_agent(str(x)) for x in write_list))
    if dt.get("forbid_read"):
        lines.append("forbid_read: " + ", ".join(str(x) for x in dt["forbid_read"]))
    if candidates_sha256:
        lines.append(f"candidates_sha256: {candidates_sha256}")
    if environment_path:
        lines.append(f"environment: {environment_path}")
    q = str(user_question or "").strip()
    if q:
        lines.append("USER QUESTION (answer this against the CodeMap / minimal source windows):")
        lines.append(q)
        if "SLICE_ID=" in q or "AXIS=" in q:
            lines.append(
                "Hard stop: this Task answers ONLY the FOCUS / SLICE_ID above. "
                "Ignore other parts of prompt.md User question."
            )
    # Public: any Action that lists *.summary.yaml in dispatch read gets MUST_READ_ORDER.
    from ascendc_pilot.ir_summary import large_ir_must_read_order_lines

    read_list = [str(x) for x in (dt.get("read") or [])]
    lines.extend(large_ir_must_read_order_lines(read_list))
    if action_id == "kb_lookup":
        lines.append(
            "Final message is the native Task return (Cursor Explore style): "
            "complete answer with file:line evidence in the body. "
            "Do not compress the answer into YAML. "
            "Optional trailing `schema: kb-answer-v1` fence is status-only "
            "(status/adequacy/citations). "
            "OpenCode Task delivers the full message to Primary; "
            "do not Write answer.yaml or scratch."
        )
        lines.append(
            "Do NOT write uo/checks/* or modify the `.uo` product; those are not this Action's outputs."
        )
        lines.append(
            "Hard stop: answer the USER QUESTION from CodeMap; do not stall on routing."
        )
        lines.append(
            "After a directed source Read for high confidence, run "
            "`pilot_cli` command=`inspect evidence-window --project <op> --path <rel> --lines A-B` "
            "for evidence_window_sha256 + snippet; do not invent hashes or "
            "self-downgrade to medium when the window proof is available."
        )
    if action_id == "kb_lookup":
        lines.extend(
            [
                "Final message is the complete native Task return to Primary.",
                "Do NOT finalize; Host `pilot_run` holds finalize after the Task returns.",
            ]
        )
    else:
        lines.extend(
            [
                "Return a short summary when done.",
                "Do NOT finalize; Host `pilot_run` holds finalize for `"
                + action_id
                + "`.",
            ]
        )
    write_for_ptr = [] if action_id == "kb_lookup" else list(write_list)
    pointers = TaskStubPointers(
        prompt=prompt_path,
        method=method_path,
        bundle=bundle_path,
        environment=environment_path,
        session_dir=session_dir,
        project_root=project_root,
        run_id=run_id,
        action_id=action_id,
        actor_id=actor_id,
        read=[_abs_under_agent(str(x)) for x in (dt.get("read") or [])],
        write=[_abs_under_agent(str(x)) for x in write_for_ptr],
        forbid_read=[str(x) for x in (dt.get("forbid_read") or [])],
    )
    return "\n".join(lines) + "\n", pointers


def _build_task_prompt_stub(
    *,
    actor_id: str,
    action_id: str,
    run_id: str,
    session_dir: str,
    prompt_path: str,
    method_path: str,
    bundle_path: str,
    dispatch_targets: dict[str, Any] | None = None,
    agent_root_path: str = "",
    project_root: str = "",
    architecture: str = "",
    candidates_sha256: str = "",
    environment_path: str = "",
    write_paths: list[str] | None = None,
    user_question: str = "",
) -> str:
    stub, _ = build_task_stub(
        actor_id=actor_id,
        action_id=action_id,
        run_id=run_id,
        session_dir=session_dir,
        prompt_path=prompt_path,
        method_path=method_path,
        bundle_path=bundle_path,
        dispatch_targets=dispatch_targets,
        agent_root_path=agent_root_path,
        project_root=project_root,
        architecture=architecture,
        candidates_sha256=candidates_sha256,
        environment_path=environment_path,
        write_paths=write_paths,
        user_question=user_question,
    )
    return stub


_BIND_REWORK_SLICES = frozenset({"harness", "bind"})


def _axis_matches_bind_rework(axis_id: str, rework_slices: set[str]) -> bool:
    aid = str(axis_id or "").strip()
    if aid in rework_slices:
        return True
    from testcase_agent.bind_parts import is_bind_chunk_id

    return "bind" in rework_slices and is_bind_chunk_id(aid)


def _expand_bind_axes_for_session(
    axes_spec: list[dict[str, Any]],
    sdir: Path,
    run_id: str,
) -> list[dict[str, Any]]:
    """Host counts table headers and splits the bind axis into ≤20-column Tasks."""
    if not any(str(row.get("id") or "").strip() == "bind" for row in axes_spec):
        return list(axes_spec)
    from testcase_agent.bind_parts import (
        BIND_COLUMN_CHUNK_SIZE,
        bind_part_column_names,
        emit_bind_chunks,
        expand_bind_fanout_axes,
    )

    parts = sdir / "parts"
    names = bind_part_column_names(parts)
    size = BIND_COLUMN_CHUNK_SIZE
    for row in axes_spec:
        if str(row.get("id") or "").strip() == "bind":
            try:
                size = int(row.get("chunk_size") or size)
            except (TypeError, ValueError):
                size = BIND_COLUMN_CHUNK_SIZE
            break
    expanded = expand_bind_fanout_axes(
        axes_spec, columns=names, run_id=run_id, chunk_size=size
    )
    bind_path = parts / "bind.yaml"
    if bind_path.is_file() and yaml is not None:
        try:
            bind = yaml.safe_load(bind_path.read_text(encoding="utf-8")) or {}
        except Exception:
            bind = {}
        if isinstance(bind, dict):
            ident = dict(bind.get("artifact_identity") or {})
            ident.setdefault("run_id", bind.get("run_id") or run_id)
            emit_bind_chunks(parts, bind, identity=ident or None, chunk_size=size)
    return expanded
_BIND_PASS_HEAD = re.compile(r"^\s*(PASS|OK|通过)\b", re.I)
_BIND_REWORK_HEAD = re.compile(r"^\s*(REWORK|打回)\b", re.I)


def _load_bind_rework(sdir: Path) -> dict[str, Any]:
    path = Path(sdir) / "rework.yaml"
    if not path.is_file() or yaml is None:
        return {}
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        return {}
    return doc if isinstance(doc, dict) else {}


def _stage_bind_part_for_rework(part: Path) -> None:
    if not part.is_file():
        return
    prev = part.parent / (part.name + ".prev")
    try:
        shutil.copy2(part, prev)
    except OSError:
        pass


class FanoutPrepareError(Exception):
    """Fanout axis declared refs or knowledge_refs that did not materialize."""

    def __init__(self, result: dict[str, Any]):
        self.result = dict(result or {})
        super().__init__(str(self.result.get("message_zh") or self.result.get("error") or "FANOUT_PREPARE_FAILED"))


FanoutKnowledgeError = FanoutPrepareError


def _review_axis_fanout_tasks(
    *,
    action: dict[str, Any],
    action_id: str,
    actor_id: str,
    phase: str,
    sdir: Path,
    stub_kwargs: dict[str, Any],
    repo: Path,
    dispatch_targets: dict[str, Any] | None,
    write_paths: list[str] | None,
    project_root: str,
    architecture: str,
) -> list[dict[str, str]]:
    """Parallel axis Tasks so slices do not share context.

    Axes come from Workflow Spec ``execution_variant=review_axis_fanout`` +
    ``fanout_axes``. The bind axis is expanded from table headers into
    ``bind0..bindN`` (≤20 columns each); runtime does not invent a new kind.
    """
    del write_paths
    if str(action.get("execution_variant") or "") != "review_axis_fanout":
        return []
    if str(phase or "").strip() not in {str(p) for p in (action.get("phases") or [])}:
        return []
    axes_spec = list(action.get("fanout_axes") or [])
    if len(axes_spec) < 2:
        return []
    run_id = str(stub_kwargs.get("run_id") or "").strip() or "current"
    if (sdir / "parts" / "merged.md").is_file():
        return []
    rework_doc = _load_bind_rework(sdir)
    rework_slices = {
        str(s).strip()
        for s in (rework_doc.get("slices") or [])
        if str(s).strip() in _BIND_REWORK_SLICES
    }
    rework_reason = str(rework_doc.get("reason") or "").strip()
    if rework_slices == {"harness", "bind"}:
        axes_spec = [row for row in axes_spec if str(row.get("id") or "").strip() in rework_slices]
        if not axes_spec:
            return []
    if rework_slices == {"harness", "bind"} and len(axes_spec) >= 2:
        dt = dict(dispatch_targets or {})
        artifacts: list[str] = []
        prevs: list[str] = []
        first_row = axes_spec[0]
        for axis_row in axes_spec:
            axis = str(axis_row.get("id") or "").strip()
            cap = str(axis_row.get("capability_id") or "").strip()
            artifact = str(axis_row.get("artifact") or "").replace("{run_id}", run_id)
            skill = str(axis_row.get("skill") or cap or "").strip()
            if not axis or not cap or not artifact:
                artifacts = []
                break
            artifacts.append(artifact)
            prevs.append(f"{artifact}.prev")
            mp = _axis_method_path(repo, axis_row)
            if mp.is_file():
                axis_prompt_text = ""
                axis_tpid = str(axis_row.get("task_prompt_id") or "").strip()
                if axis_tpid:
                    src_prompt = _task_prompt_path(repo, axis_tpid)
                    if src_prompt.is_file():
                        axis_prompt_text = src_prompt.read_text(encoding="utf-8")
                        (sdir / f"prompt_{axis}.md").write_text(axis_prompt_text, encoding="utf-8")
                _materialize_fanout_axis(
                    repo=repo,
                    sdir=sdir,
                    axis_row=axis_row,
                    axis=axis,
                    prompt_text=axis_prompt_text,
                )
            else:
                axis_tpid = str(axis_row.get("task_prompt_id") or "").strip()
                if axis_tpid:
                    src_prompt = _task_prompt_path(repo, axis_tpid)
                    if src_prompt.is_file():
                        (sdir / f"prompt_{axis}.md").write_text(
                            src_prompt.read_text(encoding="utf-8"), encoding="utf-8"
                        )
        if len(artifacts) >= 2:
            first_method = sdir / f"method_{str(first_row.get('id') or 'harness')}.md"
            axis_dt = dict(dt)
            axis_dt["write"] = list(artifacts)
            forbid = [p for p in list(axis_dt.get("forbid_read") or []) if p not in artifacts]
            axis_dt["forbid_read"] = forbid
            question = (
                "AXIS=fix\n"
                f"FOCUS: 按裁判原因 patch 两轴草稿，不要从零重写。原因：{rework_reason}\n"
                "SLICE_ID=fix\n"
                f"Read `{prevs[0]}` and `{prevs[1]}` if present. "
                f"Write `{artifacts[0]}` and `{artifacts[1]}`. "
                "Do not Write canonical tg/init.yaml."
            )
            axis_kwargs = {
                **stub_kwargs,
                "method_path": first_method.as_posix() if first_method.is_file() else stub_kwargs.get("method_path"),
                "dispatch_targets": axis_dt,
                "write_paths": list(artifacts),
                "user_question": question,
            }
            first_prompt = sdir / f"prompt_{str(first_row.get('id') or 'harness')}.md"
            if first_prompt.is_file():
                axis_kwargs["prompt_path"] = first_prompt.as_posix()
            slice_stub = _build_task_prompt_stub(**axis_kwargs)
            tasks = [
                {
                    "slice_id": "fix",
                    "focus": rework_reason or "patch harness and bind",
                    "first_mode": "fix",
                    "actor_id": actor_id,
                    "action_id": action_id,
                    "task_prompt_stub": slice_stub,
                }
            ]
            (sdir / "task_prompt_stub_fix.md").write_text(slice_stub, encoding="utf-8")
            _dump(
                sdir / "review_axes.yaml",
                {
                    "phase": phase,
                    "axes": [{"slice_id": "fix", "focus": rework_reason}],
                },
            )
            return tasks
    axes_spec = _expand_bind_axes_for_session(axes_spec, sdir, run_id)
    if rework_slices:
        axes_spec = [
            row
            for row in axes_spec
            if _axis_matches_bind_rework(str(row.get("id") or ""), rework_slices)
        ]
        if not axes_spec:
            return []
    dt = dict(dispatch_targets or {})
    tasks: list[dict[str, str]] = []
    for axis_row in axes_spec:
        axis = str(axis_row.get("id") or "").strip()
        cap = str(axis_row.get("capability_id") or "").strip()
        artifact = str(axis_row.get("artifact") or "").replace("{run_id}", run_id)
        other = str(axis_row.get("other") or "").replace("{run_id}", run_id)
        focus = str(axis_row.get("focus") or "").strip()
        skill = str(axis_row.get("skill") or cap or "").strip()
        allow_write = bool(axis_row.get("allow_write"))
        if not axis or not cap or not artifact:
            return []
        if allow_write and not rework_slices:
            part_name = Path(artifact.replace("\\", "/")).name
            part_path = sdir / "parts" / part_name
            skip = False
            try:
                from testcase_agent.bind_parts import is_bind_chunk_id, is_llm_edited

                if is_bind_chunk_id(axis) and is_llm_edited(sdir / "parts" / "bind.yaml"):
                    skip = True
                elif part_name and part_path.is_file():
                    skip = is_llm_edited(part_path)
            except Exception:
                skip = bool(part_name and part_path.is_file())
            if skip:
                continue
        mp = _axis_method_path(repo, axis_row)
        if not mp.is_file():
            return []
        axis_prompt_path = ""
        axis_prompt_text = ""
        axis_tpid = str(axis_row.get("task_prompt_id") or "").strip()
        if axis_tpid:
            src_prompt = _task_prompt_path(repo, axis_tpid)
            if src_prompt.is_file():
                axis_prompt_text = src_prompt.read_text(encoding="utf-8")
                prompt_key = str(axis_row.get("prompt_alias") or axis).strip() or axis
                axis_prompt = sdir / f"prompt_{prompt_key}.md"
                axis_prompt.write_text(axis_prompt_text, encoding="utf-8")
                axis_prompt_path = axis_prompt.as_posix()
        _materialize_fanout_axis(
            repo=repo,
            sdir=sdir,
            axis_row=axis_row,
            axis=axis,
            prompt_text=axis_prompt_text,
        )
        axis_method_name = str(axis_row.get("method_filename") or f"method_{axis}.md")
        axis_method = sdir / axis_method_name
        axis_dt = dict(dt)
        axis_write = [artifact] if allow_write else []
        axis_dt["write"] = axis_write
        forbid = list(axis_dt.get("forbid_read") or [])
        blocked = [other] if other else []
        try:
            from testcase_agent.bind_parts import is_bind_chunk_id, list_bind_chunk_paths

            if is_bind_chunk_id(axis):
                blocked.append(f"runs/{run_id}/actions/bind_init/parts/bind.yaml")
            if axis == "harness" or is_bind_chunk_id(axis):
                mine = Path(artifact.replace("\\", "/")).name
                for sibling in list_bind_chunk_paths(sdir / "parts"):
                    if sibling.name != mine:
                        blocked.append(
                            f"runs/{run_id}/actions/bind_init/parts/{sibling.name}"
                        )
        except Exception:
            pass
        if cap in {"spec-review", "standards-review", "standalone-review"} or skill in {
            "code-review",
            "standalone-review",
            "spec-review",
            "standards-review",
        }:
            blocked.extend(
                (
                    "ce/review/functional_report.yaml",
                    "ce/review/bug_report.yaml",
                    "ce/review/index.yaml",
                    "ce/review/**",
                )
            )
        for item in blocked:
            if item and item not in forbid:
                forbid.append(item)
        if rework_slices and other:
            forbid = [p for p in forbid if p != other]
        axis_dt["forbid_read"] = forbid
        if allow_write and rework_slices:
            prev = f"{artifact}.prev"
            question = (
                f"AXIS={axis}\n"
                f"FOCUS: 按裁判原因 patch 已有草稿，不要从零重写。原因：{rework_reason or focus}\n"
                f"SLICE_ID={axis}\n"
                f"Read `{prev}` if present. Write only `{artifact}`. "
                f"You MAY Read {other} to align contradictions. "
                "Do not Write canonical tg/init.yaml."
            )
        elif allow_write:
            question = (
                f"AXIS={axis}\n"
                f"FOCUS: {focus}\n"
                f"SLICE_ID={axis}\n"
                f"Read only the method path in this stub. "
                f"Write only `{artifact}`. Do not Write the other axis or canonical products. "
                f"Do not Read {other}." if other else f"Write only `{artifact}`."
            )
        else:
            question = (
                f"AXIS={axis}\n"
                f"FOCUS: {focus}\n"
                f"SLICE_ID={axis}\n"
                "Read only the method path in this stub. "
                "Put findings in the Task return. Do not Write harvest files or ce/**. "
                f"Do not Read {other}."
            )
        axis_kwargs = {
            **stub_kwargs,
            "method_path": axis_method.as_posix(),
            "dispatch_targets": axis_dt,
            "write_paths": axis_write,
            "user_question": question,
        }
        if axis_prompt_path:
            axis_kwargs["prompt_path"] = axis_prompt_path
        slice_stub = _build_task_prompt_stub(**axis_kwargs)
        tasks.append(
            {
                "slice_id": axis,
                "focus": focus,
                "first_mode": axis,
                "actor_id": actor_id,
                "action_id": action_id,
                "task_prompt_stub": slice_stub,
            }
        )
        (sdir / f"task_prompt_stub_{axis}.md").write_text(slice_stub, encoding="utf-8")
    if len(tasks) < 1:
        return []
    _dump(
        sdir / "review_axes.yaml",
        {
            "phase": phase,
            "axes": [
                {k: t[k] for k in ("slice_id", "focus")}
                for t in tasks
            ],
        },
    )
    return tasks


def _bind_review_slices_from_intent(intent: str) -> list[str]:
    text = str(intent or "")
    found = {
        sid
        for sid in _BIND_REWORK_SLICES
        if re.search(rf"\b{sid}\b", text, re.I)
    }
    return [sid for sid in ("harness", "bind") if sid in found]


def _parse_bind_review_intent(intent: str) -> dict[str, Any] | None:
    """Start-of-string PASS / REWORK only. Original NL must not count as PASS."""
    text = str(intent or "").strip()
    if not text:
        return None
    if _BIND_PASS_HEAD.match(text):
        return {"ok": True}
    if _BIND_REWORK_HEAD.match(text):
        slices = _bind_review_slices_from_intent(text)
        if not slices:
            return {"ok": False, "rework": [], "incomplete": True}
        return {"ok": False, "rework": slices}
    return None


def _complete_bind_review_prepare(
    project_root: Path,
    *,
    run_id: str,
    sdir: Path,
    result: dict[str, Any],
    intent: str = "",
) -> dict[str, Any]:
    """Primary reads both bind drafts; next pilot_run carries PASS/REWORK. Never writes yaml."""
    from ascendc_pilot.actions.dispatch_legacy import reopen_fanout_slices

    turn = str(intent or current_turn_intent() or "").strip()
    bind_init_sdir = _session_dir(project_root, run_id, "bind_init")
    bind_parts = bind_init_sdir / "parts"
    harness = bind_parts / "harness.yaml"
    bindp = bind_parts / "bind.yaml"
    verdict_path = sdir / "verdict.yaml"
    prompted = sdir / "review_prompted.yaml"
    result["harness_path"] = harness.as_posix()
    result["bind_path"] = bindp.as_posix()
    result["verdict_path"] = verdict_path.as_posix()
    result["dispatch_task"] = False
    result["needs_human_decision"] = False
    parsed = _parse_bind_review_intent(turn)
    from ascendc_pilot.yaml_check import format_yaml_error_zh, parse_yaml_mapping

    _, harness_err = parse_yaml_mapping(harness)
    bind_doc, bind_err = parse_yaml_mapping(bindp)
    part_err = harness_err or bind_err
    rework = list(parsed.get("rework") or []) if parsed else []
    if part_err and not rework:
        result["ok"] = False
        result["error"] = "BIND_PART_YAML_INVALID"
        result["host_step_kind"] = "primary_review"
        result["message_zh"] = format_yaml_error_zh(part_err)
        result["line"] = part_err.get("line")
        result["column"] = part_err.get("column")
        result["path"] = part_err.get("path")
        return result
    if parsed and parsed.get("ok") is True:
        bind_errors: list[str] = []
        if isinstance(bind_doc, dict):
            try:
                from testcase_agent import products

                bind_errors = products.validate_bind_part(bind_doc)
            except Exception:  # noqa: BLE001
                bind_errors = []
        if bind_errors:
            result["ok"] = False
            result["error"] = "BIND_PART_INVALID"
            result["host_step_kind"] = "primary_review"
            result["errors"] = bind_errors
            result["message_zh"] = "bind 草稿非法：" + "；".join(bind_errors)
            return result
        doc = {"schema": "tg-bind-review-verdict/v1", "ok": True}
        _dump(verdict_path, doc)
        try:
            if prompted.is_file():
                prompted.unlink()
        except OSError:
            pass
        fin = finalize_action(
            project_root, "bind_review", engine_result={"ok": True, "verdict": doc}
        )
        result["auto_finalize"] = True
        result["finalize"] = fin
        result["ok"] = bool(fin.get("ok"))
        result["message_zh"] = "主控裁判已放行。"
        return result
    if parsed and parsed.get("incomplete"):
        result["ok"] = False
        result["error"] = "NEED_BIND_REVIEW_SLICES"
        result["message_zh"] = (
            "REWORK 必须点名 harness 和/或 bind，例如 `REWORK bind` 或 `REWORK harness,bind`。"
        )
        return result
    rework = list(parsed.get("rework") or []) if parsed else []
    if parsed and parsed.get("ok") is False and rework:
        try:
            if verdict_path.is_file():
                verdict_path.unlink()
        except OSError:
            pass
        leftover = sdir / "referee.yaml"
        try:
            if leftover.is_file():
                leftover.unlink()
        except OSError:
            pass
        try:
            if prompted.is_file():
                prompted.unlink()
        except OSError:
            pass
        _dump(
            bind_init_sdir / "rework.yaml",
            {"schema": "tg-bind-rework/v1", "slices": rework, "reason": turn},
        )
        for sid in rework:
            _stage_bind_part_for_rework(bind_parts / f"{sid}.yaml")
        from ascendc_pilot.actions.dispatch_legacy import discard_dispatch_tickets_for_action
        from ascendc_pilot.runs import invalidate_action_receipts

        reopen_fanout_slices(
            project_root, action_id="bind_init", slice_ids=rework, run_id=run_id
        )
        discard_dispatch_tickets_for_action(
            project_root, run_id=run_id, action_id="bind_init"
        )
        invalidate_action_receipts(project_root, action_id="bind_init")
        result["ok"] = True
        result["continue_drive"] = True
        result["rework"] = rework
        result["message_zh"] = (
            "裁判未通过，只重开 " + ",".join(rework) + " 切片。子代理按原因 patch 后再进入 bind_review。"
        )
        return result
    if prompted.is_file() and not parsed:
        result["ok"] = False
        result["error"] = "NEED_BIND_REVIEW_INTENT"
        result["message_zh"] = (
            "需要 PASS 或 REWORK bind / REWORK harness,bind，不要空跑 pilot_run。"
        )
        return result
    _dump(prompted, {"schema": "tg-bind-review-prompted/v1"})
    result["ok"] = True
    result["host_step_kind"] = "primary_review"
    result["message_zh"] = (
        "请通读 harness.yaml 与 bind.yaml（不要只做字段差集）。"
        "不要写文件、不要问用户。parts 已齐时禁止 force_new。"
        "没问题：下一发 `pilot_run(tg-init)` intent=`PASS`。"
        "有问题：intent=`REWORK bind` 或 `REWORK harness,bind`，后面跟原因。"
        "必须点名 harness 和/或 bind，不要只写 REWORK。"
    )
    return result


def _complete_plan_narrate_prepare(
    project_root: Path,
    *,
    run_id: str,
    sdir: Path,
    result: dict[str, Any],
    intent: str = "",
) -> dict[str, Any]:
    """Primary writes the three plan.md headings; next pilot_run captures them."""
    from ascendc_pilot.actions.tg_product import _has_plan_prose

    turn = str(intent or current_turn_intent() or "").strip()
    prompted = sdir / "narrate_prompted.yaml"
    result["dispatch_task"] = False
    result["needs_human_decision"] = False
    result["host_step_kind"] = "primary_review"
    if _has_plan_prose(turn):
        captured = {"text": turn, "doc": {}}
        _dump(sdir / "captured.yaml", captured)
        try:
            if prompted.is_file():
                prompted.unlink()
        except OSError:
            pass
        fin = finalize_action(
            project_root,
            "plan_narrate",
            engine_result={"ok": True, "text": turn, "result_text": turn},
        )
        result["auto_finalize"] = True
        result["finalize"] = fin
        result["ok"] = bool(fin.get("ok"))
        result["message_zh"] = "plan_narrate 三节散文已捕获，继续 plan_promote。"
        return result
    if prompted.is_file() and not turn:
        result["ok"] = False
        result["error"] = "NEED_PLAN_NARRATE"
        result["message_zh"] = (
            "需要三节散文：## 测什么 / ## 覆盖什么 / ## 怎么判定。"
            "下一发 `pilot_run(tg-plan)` 把这三节作为 intent，不要空跑。"
        )
        return result
    _dump(prompted, {"schema": "tg-plan-narrate-prompted/v1"})
    result["ok"] = True
    result["message_zh"] = (
        "读 plan_scope 回答与 plan_fuse YAML，写 ## 测什么 / ## 覆盖什么 / ## 怎么判定。"
        "不要编覆盖模型，不要 Write plan.md。下一发 `pilot_run(tg-plan)` intent=这三节全文。"
    )
    return result


def _skill_path(repo: Path, skill_id: str) -> Path:
    """``skills/<skill_id>/SKILL.md`` — one document per executable step."""
    return repo / "skills" / str(skill_id or "").strip() / "SKILL.md"


def _normalize_skill_id(raw: str) -> str:
    token = str(raw or "").strip()
    if "/" in token:
        token = token.rsplit("/", 1)[-1].strip()
    return token


def _skill_method_ref_path(repo: Path, skill_id: str, method_ref: str) -> Path:
    """Disclosed playbook: ``skills/<id>/references/<method_ref>``."""
    rel = str(method_ref or "").strip().replace("\\", "/").lstrip("/")
    if rel.startswith("references/"):
        rel = rel[len("references/") :]
    return repo / "skills" / str(skill_id or "").strip() / "references" / rel


def _capability_method_path(repo: Path, domain: str, capability: str) -> Path:
    """Fanout axis playbook: ``capability`` is the Skill id."""
    del domain
    return _skill_path(repo, capability)


def _axis_method_path(repo: Path, axis_row: dict[str, Any]) -> Path:
    """Slice playbook: ``method_ref`` under the axis skill, else ``SKILL.md``."""
    skill = str(axis_row.get("skill") or axis_row.get("capability_id") or "").strip()
    method_ref = str(axis_row.get("method_ref") or "").strip()
    if method_ref and skill:
        return _skill_method_ref_path(repo, skill, method_ref)
    cap = str(axis_row.get("capability_id") or skill).strip()
    return _skill_path(repo, cap)


def _axis_playbook_text(repo: Path, axis_row: dict[str, Any]) -> str:
    """Branch HOW plus one-level pointers for this slice only.

    ``references/*.md`` hops are forbidden inside reference files, so the
    axis ``refs`` list is appended here (the composed session method is not
    a reference file).
    """
    path = _axis_method_path(repo, axis_row)
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    refs = [str(r).strip().replace("\\", "/").lstrip("/") for r in (axis_row.get("refs") or [])]
    refs = [r[len("references/") :] if r.startswith("references/") else r for r in refs if r]
    knowledge = [
        str(r).strip().replace("\\", "/").lstrip("/")
        for r in (axis_row.get("knowledge_refs") or [])
        if str(r).strip()
    ]
    knowledge = [
        r[len("knowledge/") :] if r.startswith("knowledge/") else r for r in knowledge
    ]
    axis = str(axis_row.get("id") or "").strip()
    knowledge_ns = axis if str(axis_row.get("method_ref") or "").strip() else ""
    if not refs and not knowledge:
        return text
    lines = [text.rstrip(), "", "## 指针", ""]
    for rel in refs:
        lines.append(f"- `references/{rel}`")
    for rel in knowledge:
        prefix = f"knowledge/{knowledge_ns}/" if knowledge_ns else "knowledge/"
        lines.append(f"- `{prefix}{rel}`")
    return "\n".join(lines) + "\n"


def _materialize_fanout_axis(
    *,
    repo: Path,
    sdir: Path,
    axis_row: dict[str, Any],
    axis: str,
    prompt_text: str = "",
) -> str:
    """Write ``method_{axis}.md`` and copy only this slice's refs."""
    skill = str(axis_row.get("skill") or axis_row.get("capability_id") or "").strip()
    body = _axis_playbook_text(repo, axis_row)
    from ascendc_pilot.actions.method_bundle import materialize_method_bundle

    refs_ns = axis if str(axis_row.get("method_ref") or "").strip() else ""
    mat = materialize_method_bundle(
        sdir,
        skill_ids=[skill],
        existing_method=body,
        project_root=repo,
        prompt=prompt_text,
        current_skill_id=skill,
        method_filename=str(axis_row.get("method_filename") or f"method_{axis}.md"),
        refs_ns=str(axis_row.get("refs_ns") or "").strip()
        or (axis if str(axis_row.get("method_ref") or "").strip() else ""),
        explicit_refs=[str(r).strip() for r in (axis_row.get("refs") or []) if str(r).strip()],
    )
    if not mat.get("ok"):
        raise FanoutPrepareError(mat)
    from ascendc_pilot.actions.method_bundle import materialize_knowledge_refs

    know = materialize_knowledge_refs(
        sdir,
        list(axis_row.get("knowledge_refs") or []),
        project_root=repo,
        knowledge_ns=refs_ns,
    )
    if not know.get("ok"):
        raise FanoutKnowledgeError(know)
    return body


def _uo_query_method_path(repo: Path) -> Path:
    return _skill_path(repo, "uo-query")


def _resolve_capability_method(repo: Path, action: dict[str, Any]) -> Path | None:
    """Map ``skill_id`` (+ optional ``method_ref``) onto a playbook. Missing files fail closed."""
    sid = _normalize_skill_id(
        str(action.get("skill_id") or action.get("action_method_id") or "")
    )
    if not sid:
        return None
    method_ref = str(action.get("method_ref") or "").strip()
    if method_ref:
        return _skill_method_ref_path(repo, sid, method_ref)
    return _skill_path(repo, sid)


def _task_prompt_path(repo: Path, tpid: str) -> Path:
    """``prompts/tasks/<domain>/<name>.md`` for ``domain/name`` prompt ids."""
    token = str(tpid or "").strip()
    if "/" in token:
        dom, name = token.split("/", 1)
        return repo / "prompts" / "tasks" / dom / f"{name}.md"
    return repo / "prompts" / "tasks" / f"{token}.md"


def _load_method_and_prompt(repo: Path, action: dict[str, Any]) -> tuple[str, str]:
    """Load task prompt and optional Skill METHOD playbook.

    Spec remains identity authority; METHOD is the query state machine for
    ephemeral workflows such as ``uo-query`` (not a second Spec).
    Deterministic Actions have no ``task_prompt_id`` and therefore load no prompt.
    """
    method = ""
    prompt = ""
    tpid = str(action.get("task_prompt_id") or "")
    if tpid:
        pp = _task_prompt_path(repo, tpid)
        if pp.is_file():
            prompt = pp.read_text(encoding="utf-8")
    mp = _resolve_capability_method(repo, action)
    if mp is not None and mp.is_file():
        method = mp.read_text(encoding="utf-8")
    method = _append_action_ref_pointers(method, action)
    return method, prompt


def _append_action_ref_pointers(text: str, action: dict[str, Any]) -> str:
    """Axis HOW files cannot hop; Action ``refs`` become one-level pointers."""
    refs = [str(r).strip().replace("\\", "/").lstrip("/") for r in (action.get("refs") or [])]
    refs = [r[len("references/") :] if r.startswith("references/") else r for r in refs if r]
    knowledge = [
        str(r).strip().replace("\\", "/").lstrip("/")
        for r in (action.get("knowledge_refs") or [])
        if str(r).strip()
    ]
    knowledge = [
        r[len("knowledge/") :] if r.startswith("knowledge/") else r for r in knowledge
    ]
    if (not refs and not knowledge) or not str(text or "").strip():
        return text
    if refs:
        refs = [rel for rel in refs if f"`references/{rel}`" not in text]
    if knowledge:
        knowledge = [rel for rel in knowledge if f"`knowledge/{rel}`" not in text]
    if not refs and not knowledge:
        return text
    lines = [text.rstrip(), "", "## 指针", ""]
    for rel in refs:
        lines.append(f"- `references/{rel}`")
    for rel in knowledge:
        lines.append(f"- `knowledge/{rel}`")
    return "\n".join(lines) + "\n"


def _resolve_contract_paths(root: Path, rel: str) -> list[Path]:
    """Resolve exact or glob contract paths under agent root."""
    if any(ch in rel for ch in "*?["):
        return sorted(p for p in root.glob(rel) if p.exists())
    path = root / rel
    return [path] if path.exists() else []


_PRODUCER_OWNED_ARTIFACT_NAMES: set[str] = set()
_ACTION_OWNED_ARTIFACT_NAMES = _PRODUCER_OWNED_ARTIFACT_NAMES | {
    "scope_validated.yaml",
    "receipt.yaml",
}
# Public Action is ``prepare``; machine gate stamp is ``scope_validated``.
_SCOPE_GATE_ACTION_IDS = frozenset({"prepare", "scope_validated"})


def _is_run_scoped_scope_artifact(path: Path) -> bool:
    posix = path.as_posix().replace("\\", "/")
    return path.name in {"scope_validated.yaml", "receipt.yaml"} and "/scope/" in posix


def _hash_prepare_nonce(prepare_nonce: str = "", prepare_nonce_hash: str = "") -> str:
    if prepare_nonce_hash:
        return str(prepare_nonce_hash).strip()
    if not prepare_nonce:
        return ""
    return hashlib.sha256(str(prepare_nonce).encode("utf-8")).hexdigest()


def _declared_artifact_identity(data: dict[str, Any]) -> dict[str, str]:
    identity = data.get("artifact_identity") if isinstance(data.get("artifact_identity"), dict) else {}
    snapshot = data.get("snapshot") if isinstance(data.get("snapshot"), dict) else {}
    checks: dict[str, str] = {}
    for field in (
        "run_id",
        "workflow_id",
        "phase",
        "action_id",
        "actor_id",
        "role_id",
        "action_session_id",
        "lease_id",
        "prepare_nonce_hash",
        "produced_by",
    ):
        checks[field] = str(identity.get(field) or data.get(field) or "").strip()
    # Scope receipt from finalize_scope historically nested run_id under snapshot only.
    # Accept that so contract check can pass before pilot-finalizer stamps artifact_identity.
    if not checks["run_id"]:
        checks["run_id"] = str(snapshot.get("run_id") or "").strip()
    declared_nonce = str(identity.get("prepare_nonce") or data.get("prepare_nonce") or "").strip()
    if declared_nonce and not checks["prepare_nonce_hash"]:
        checks["prepare_nonce_hash"] = _hash_prepare_nonce(declared_nonce)
    return checks


def _contract_identity_ok(
    path: Path,
    *,
    run_id: str,
    workflow_id: str,
    phase: str = "",
    action_id: str = "",
    actor_id: str = "",
    role_id: str = "",
    action_session_id: str = "",
    lease_id: str = "",
    prepare_nonce_hash: str = "",
    prepare_nonce: str = "",
    require_finalizer_stamp: bool = False,
) -> dict[str, Any]:
    """Validate declared artifact identity against the current Action session."""
    if yaml is None or not path.is_file() or path.suffix.lower() not in {".yaml", ".yml"}:
        return {"ok": True, "skipped": True}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        return {"ok": True, "skipped": True}
    if not isinstance(data, dict):
        return {"ok": True, "skipped": True}
    checks = _declared_artifact_identity(data)
    expected = {
        "run_id": str(run_id or "").strip(),
        "workflow_id": str(workflow_id or "").strip(),
        "phase": str(phase or "").strip(),
        "action_id": str(action_id or "").strip(),
        "actor_id": str(actor_id or "").strip(),
        "role_id": str(role_id or "").strip(),
        "action_session_id": str(action_session_id or "").strip(),
        "lease_id": str(lease_id or "").strip(),
        "prepare_nonce_hash": _hash_prepare_nonce(prepare_nonce, prepare_nonce_hash),
    }
    posix = path.as_posix()
    action_owned = path.name in _ACTION_OWNED_ARTIFACT_NAMES or "/runs/" in posix

    # Missing identity on older artifacts is a migration error for run-scoped contracts.
    # Only the run-scoped scope receipts require identity before finalizer
    # stamping.  Do not match the substring ``receipt.yaml`` in deterministic
    # IR names such as ``host_extract_receipt.yaml``.
    if "/runs/" in posix or path.name in {"scope_validated.yaml", "receipt.yaml"}:
        if not checks["run_id"]:
            return {
                "ok": False,
                "error": "ARTIFACT_IDENTITY_MISSING",
                "path": path.as_posix(),
                "message": "run-scoped artifact missing identity; re-prepare / re-finalize",
            }

    if action_owned and (require_finalizer_stamp or checks["produced_by"] == "pilot-finalizer"):
        for field in (
            "run_id",
            "workflow_id",
            "phase",
            "action_id",
            "actor_id",
            "role_id",
            "action_session_id",
            "lease_id",
            "prepare_nonce_hash",
        ):
            if expected[field] and not checks[field]:
                return {
                    "ok": False,
                    "error": "ARTIFACT_IDENTITY_MISSING",
                    "field": field,
                    "path": path.as_posix(),
                    "message": "finalized artifact missing trusted identity field",
                }
        if not checks["produced_by"]:
            return {
                "ok": False,
                "error": "ARTIFACT_IDENTITY_MISSING",
                "field": "produced_by",
                "path": path.as_posix(),
                "message": "finalized artifact missing pilot-finalizer stamp",
            }

    if action_owned and checks["produced_by"] and checks["produced_by"] != "pilot-finalizer":
        return {
            "ok": False,
            "error": "ARTIFACT_OWNER_MISMATCH",
            "field": "produced_by",
            "path": path.as_posix(),
            "expected": "pilot-finalizer",
            "actual": checks["produced_by"],
        }

    error_by_field = {
        "action_session_id": "ARTIFACT_SESSION_MISMATCH",
        "lease_id": "ARTIFACT_LEASE_MISMATCH",
        "prepare_nonce_hash": "ARTIFACT_NONCE_MISMATCH",
    }
    for field, actual in checks.items():
        if field == "produced_by":
            continue
        expected_value = expected.get(field, "")
        if not expected_value or not actual or actual == expected_value:
            continue
        # Public Action is ``prepare``; machine Clang scope stamps
        # ``scope_validated``. Treat the gate/Action spellings as one owner
        # on run-scoped scope artifacts (ses_00bb).
        if (
            field == "action_id"
            and _is_run_scoped_scope_artifact(path)
            and {str(expected_value), str(actual)} <= _SCOPE_GATE_ACTION_IDS
        ):
            continue
        # Shared / upstream IR (e.g. tg/init.yaml on tg-plan plan_precheck)
        # keeps its originating run_id/workflow_id. Only action-owned writes must
        # match the current finalize identity.
        if not action_owned:
            continue
        return {
            "ok": False,
            "error": error_by_field.get(field, "ARTIFACT_OWNER_MISMATCH"),
            "field": field,
            "path": path.as_posix(),
            "expected": expected_value,
            "actual": actual,
        }

    return {"ok": True}


def _collect_output_hashes(
    project_root: Path,
    contract_id: str,
    *,
    run_id: str = "",
    workflow_id: str = "",
    phase: str = "",
    action_id: str = "",
    actor_id: str = "",
    role_id: str = "",
    action_session_id: str = "",
    lease_id: str = "",
    prepare_nonce_hash: str = "",
    prepare_nonce: str = "",
) -> dict[str, str]:
    from ascendc_pilot.ownership import expand_contract_paths

    root = agent_root(project_root, _arch_for(project_root))
    hashes: dict[str, str] = {}
    import hashlib

    for rel in expand_contract_paths(
        list(OUTPUT_CONTRACT_PATHS.get(contract_id, [])),
        run_id=run_id,
        workflow_id=workflow_id,
        action_id=action_id,
        actor_id=actor_id,
        action_session_id=action_session_id,
    ):
        matches = _resolve_contract_paths(root, rel)
        if not matches:
            continue
        if len(matches) == 1 and matches[0].is_file():
            hashes[rel] = file_sha256(matches[0])
            continue
        if len(matches) == 1 and matches[0].is_dir():
            files = sorted(p for p in matches[0].rglob("*") if p.is_file())[:20]
            blob = "\n".join(f"{p.relative_to(root).as_posix()}:{file_sha256(p)}" for p in files)
            hashes[rel] = hashlib.sha256(blob.encode("utf-8")).hexdigest() if files else "empty_dir"
            continue
        # Glob → fingerprint matched files
        files = sorted(p for p in matches if p.is_file())[:20]
        blob = "\n".join(f"{p.relative_to(root).as_posix()}:{file_sha256(p)}" for p in files)
        hashes[rel] = hashlib.sha256(blob.encode("utf-8")).hexdigest() if files else "empty_glob"
    return hashes


def _check_required_outputs_writable(
    *,
    workflow_id: str,
    action_id: str,
    actor_id: str,
    contract_id: str,
    output_mode: str,
    write_paths: list[str],
    run_id: str,
    project_root: Path,
) -> dict[str, Any]:
    """Fail-closed prepare: contract outputs must be materializable.

    ``return_value`` / ``output_transport=return_value``: dialogue contract
    with no disk payload — agent write_scopes may be empty (Explorer does not Write).
    ``direct`` / default: each required output must match
    ``agent.write_scopes ∩ action.allowed_write_paths``.
    """
    from ascendc_pilot.agents_registry import agent_write_scopes, path_matches_scope
    from ascendc_pilot.ownership import expand_contract_paths

    mode = str(output_mode or "direct").strip().lower()
    if mode in {"return_value", "return"}:
        return {"ok": True, "skipped": True, "reason": "return_value_finalizer"}
    if not contract_id or contract_id not in OUTPUT_CONTRACT_PATHS:
        return {"ok": True, "skipped": True}
    required = expand_contract_paths(
        list(OUTPUT_CONTRACT_PATHS.get(contract_id) or []),
        run_id=run_id,
        workflow_id=workflow_id,
        action_id=action_id,
        actor_id=actor_id,
    )
    if not required:
        return {"ok": True, "skipped": True}
    scopes = agent_write_scopes(actor_id, project_root) if actor_id else []
    lease_writes = [str(p).replace("\\", "/") for p in write_paths]
    unwritable: list[str] = []
    for rel in required:
        norm = str(rel).replace("\\", "/")
        in_lease = path_matches_scope(norm, lease_writes) if lease_writes else False
        in_agent = path_matches_scope(norm, scopes) if scopes else False
        if not (in_lease and in_agent):
            unwritable.append(norm)
    if unwritable:
        return {
            "ok": False,
            "error": "OUTPUT_NOT_WRITABLE",
            "reason_code": "OUTPUT_NOT_WRITABLE",
            "required": required,
            "unwritable": unwritable,
            "agent_write_scopes": scopes,
            "action_write_paths": lease_writes,
            "message_zh": (
                "prepare 拒绝：合同产物不在 agent.write_scopes ∩ action.allowed_write_paths 内；"
                "请先修 Agent/Action 写面，勿派发子代理。"
            ),
        }
    return {"ok": True, "required": required}


def _check_output_contract(
    project_root: Path,
    contract_id: str,
    *,
    run_id: str = "",
    workflow_id: str = "",
    phase: str = "",
    action_id: str = "",
    actor_id: str = "",
    role_id: str = "",
    action_session_id: str = "",
    lease_id: str = "",
    prepare_nonce_hash: str = "",
    prepare_nonce: str = "",
    require_finalizer_stamp: bool = False,
) -> dict[str, Any]:
    """Fail-closed: missing or unregistered contracts never pass."""
    from ascendc_pilot.ownership import expand_contract_paths

    if not contract_id:
        return {
            "ok": False,
            "skipped": False,
            "error": "missing_contract_id",
            "message": "output_contract_id is required; cannot skip validation",
        }
    paths = OUTPUT_CONTRACT_PATHS.get(contract_id)
    if paths is None:
        return {
            "ok": False,
            "skipped": False,
            "error": "unknown_contract",
            "message": f"unregistered output contract {contract_id!r}; finalize denied",
        }
    root = agent_root(project_root, _arch_for(project_root))
    expanded = expand_contract_paths(
        list(paths),
        run_id=run_id,
        workflow_id=workflow_id,
        action_id=action_id,
        actor_id=actor_id,
        action_session_id=action_session_id,
    )
    # Unconstrained run wildcards are forbidden once identity templates are available.
    for rel in expanded:
        if "runs/*/" in rel.replace("\\", "/"):
            return {
                "ok": False,
                "skipped": False,
                "error": "CONTRACT_RUN_WILDCARD_FORBIDDEN",
                "message": f"run-scoped contract must use {{run_id}}, got {rel!r}",
                "contract_id": contract_id,
            }
    missing = []
    empty = []
    identity_errors: list[dict[str, Any]] = []
    match_any = contract_id in OUTPUT_CONTRACT_MATCH_ANY
    any_nonempty = False
    for rel in expanded:
        matches = _resolve_contract_paths(root, rel)
        if not matches:
            if not match_any:
                missing.append(rel)
            continue
        nonempty = False
        for path in matches:
            if path.is_file() and path.stat().st_size > 0:
                nonempty = True
                id_check = _contract_identity_ok(
                    path,
                    run_id=run_id,
                    workflow_id=workflow_id,
                    phase=phase,
                    action_id=action_id,
                    actor_id=actor_id,
                    role_id=role_id,
                    action_session_id=action_session_id,
                    lease_id=lease_id,
                    prepare_nonce_hash=prepare_nonce_hash,
                    prepare_nonce=prepare_nonce,
                    require_finalizer_stamp=require_finalizer_stamp,
                )
                if not id_check.get("ok"):
                    identity_errors.append(id_check)
                break
            if path.is_dir() and any(p.is_file() and p.stat().st_size > 0 for p in path.rglob("*")):
                nonempty = True
                break
        if nonempty:
            any_nonempty = True
        elif not match_any:
            empty.append(rel)
    if match_any and not any_nonempty:
        missing = list(expanded)

    # Stronger nonempty globs for TG plan/solve contracts
    glob_miss: list[str] = []
    for pattern in expand_contract_paths(
        list(OUTPUT_CONTRACT_NONEMPTY_GLOBS.get(contract_id, [])),
        run_id=run_id,
        workflow_id=workflow_id,
        action_id=action_id,
        actor_id=actor_id,
        action_session_id=action_session_id,
    ):
        matches = [p for p in root.glob(pattern) if p.is_file() and p.stat().st_size > 0]
        if not matches:
            # Also try rglob-style ** manually
            if "**" in pattern:
                prefix, _, suffix = pattern.partition("**/")
                base = root / prefix.rstrip("/")
                matches = [
                    p
                    for p in (base.rglob(suffix) if base.exists() else [])
                    if p.is_file() and p.stat().st_size > 0
                ]
            if not matches:
                glob_miss.append(pattern)

    ok = not missing and not empty and not glob_miss and not identity_errors
    parts = []
    if missing:
        parts.append(f"missing outputs: {missing}")
        if any(str(m).replace("\\", "/").startswith("runs/") for m in missing):
            parts.append(
                "subagent must Write these lease paths before primary finalize; "
                "do not invent uo/checks/* as a substitute"
            )
    if empty:
        parts.append(f"empty outputs: {empty}")
    if glob_miss:
        parts.append(f"missing nonempty artifacts: {glob_miss}")
    if identity_errors:
        parts.append(f"identity errors: {[e.get('error') for e in identity_errors]}")
    return {
        "ok": ok,
        "contract_id": contract_id,
        "missing": missing,
        "empty": empty,
        "missing_globs": glob_miss,
        "identity_errors": identity_errors,
        "message": "ok" if ok else "; ".join(parts),
    }


def prepare_action(
    project_root: Path,
    action_id: str,
    *,
    turn_intent: str = "",
) -> dict[str, Any]:
    try:
        arch = discover_arch(project_root)
    except ValueError:
        return {
            "ok": False,
            "error": "ARCHITECTURE_MISSING_IN_RUN_STATE",
            "reason_code": "ARCHITECTURE_MISSING_IN_RUN_STATE",
            "message_zh": "缺少 architecture；请先 Host `pilot_run` 并带上 architecture",
        }
    ensure_control_layout(project_root, arch=arch)
    state = load_state(project_root, arch=arch)
    if not state:
        return {"ok": False, "error": "no_active_workflow", "message_zh": "无活动 workflow；请先 Host `pilot_run`"}
    arch = require_architecture(str(state.get("architecture") or arch))
    wid = str(state.get("workflow_id") or "")
    if wid.startswith("tg-"):
        ensure_tg_layout(project_root, arch=arch)
    phase = str(state.get("phase") or "")
    run_id = str(state.get("run_id") or "")
    action = _action_spec(wid, action_id, phase, project_root=project_root)
    if action is None:
        return {
            "ok": False,
            "error": "unknown_action",
            "message_zh": f"未知 action {action_id!r}",
            "phase": phase,
        }
    if action.get("_not_in_phase"):
        return {
            "ok": False,
            "error": "action_not_allowed",
            "message_zh": f"动作 {action_id!r} 不在当前阶段 {phase!r} 的 allowed_actions 中",
            "phase": phase,
            "allowed": [a.get("id") for a in actions_for_phase(wid, phase, project_root=project_root)],
        }

    # Prefer pipeline order: block Host skip ahead of recommended_next_action.
    status = str(state.get("status") or "running")
    if status == "running":
        from ascendc_pilot.workflows.pipeline import recommend_next_action

        recommended = recommend_next_action(
            project_root,
            workflow_id=wid,
            phase=phase,
            allowed_actions=actions_for_phase(wid, phase, project_root=project_root),
        )
        rec_reason = str((recommended or {}).get("reason") or "")
        rec_id = (recommended or {}).get("id")
        if rec_reason == "pipeline_complete":
            return {
                "ok": False,
                "error": "PIPELINE_COMPLETE_ADVANCE_REQUIRED",
                "message_zh": (
                    "本阶段流水线已完成；禁止再 prepare 任意 Action。"
                    "请 Host `pilot_run` 进入下一阶段。"
                ),
                "recommended_next_action": recommended,
                "requested_action": action_id,
                "phase": phase,
            }
        if rec_id and rec_id != action_id:
            return {
                "ok": False,
                "error": "PIPELINE_SKIP_DENIED",
                "message_zh": (
                    f"禁止跳步：当前 recommended_next_action=`{rec_id}`，"
                    f"不可直接跑 `{action_id}`。缺少前置 Action；请先 `pilot_cli next`。"
                ),
                "recommended_next_action": recommended,
                "requested_action": action_id,
                "prerequisite_action": rec_id,
                "phase": phase,
            }
    elif status == "rework_required":
        lf = state.get("last_failure") if isinstance(state.get("last_failure"), dict) else {}
        failed = str(lf.get("action_id") or "")
        recovery = [str(x) for x in (lf.get("recovery_actions") or []) if str(x).strip()]
        if failed and action_id != failed and action_id not in recovery:
            return {
                "ok": False,
                "error": "rework_action_not_allowed",
                "message_zh": (
                    f"rework_required：仅可重试 `{failed}`"
                    + (f" 或恢复动作 {recovery}" if recovery else "")
                ),
                "failed_action": failed,
                "recovery_actions": recovery,
            }

    actor_id = str(action.get("agent_id") or (action.get("actors") or ["unknown"])[0])
    role_id = str(action.get("role_id") or "")
    from ascendc_pilot.ownership import (
        EXECUTION_DETERMINISTIC,
        EXECUTION_PRIMARY_INTERACTIVE,
        EXECUTION_PRIMARY_REVIEW,
        EXECUTION_SUBAGENT,
        action_session_id as make_action_session_id,
        action_write_paths,
        build_bundle_identity,
        expand_path_template,
        infer_execution_mode,
        prompt_has_unresolved,
        staging_dir,
        unresolved_placeholders,
    )

    execution_mode = infer_execution_mode(
        agent_id=actor_id if actor_id != "unknown" else None,
        role_id=role_id,
        execution_mode=str(action.get("execution_mode") or "") or None,
    )
    from ascendc_pilot.authorize.lease import active_action_path

    existing_active = _load(active_action_path(project_root, run_id=run_id, arch=arch))
    existing_sdir = Path(str(existing_active.get("session_dir") or "") or "")
    reuse_prepared = (
        execution_mode != EXECUTION_DETERMINISTIC
        and str(existing_active.get("status") or "") == "prepared"
        and str(existing_active.get("run_id") or "") == run_id
        and str(existing_active.get("action_id") or "") == action_id
        and existing_sdir.is_dir()
        and (
            (existing_sdir / SESSION_STATE_FILENAME).is_file()
            or (existing_sdir / SESSION_STATE_LEGACY).is_file()
            or (existing_sdir / "bundle.yaml").is_file()
        )
    )
    if reuse_prepared:
        session_prev = _load_action_session(existing_sdir)
        prepare_nonce = str(
            existing_active.get("prepare_nonce") or session_prev.get("prepare_nonce") or ""
        ).strip()
        if not prepare_nonce:
            reuse_prepared = False
            prepare_nonce = secrets.token_hex(16)
        nonce = prepare_nonce
        action_sid = str(
            existing_active.get("action_session_id")
            or make_action_session_id(run_id, action_id, prepare_nonce)
        )
        sdir = existing_sdir
        sdir.mkdir(parents=True, exist_ok=True)
        staging_dir(sdir).mkdir(parents=True, exist_ok=True)
    if not reuse_prepared:
        prepare_nonce = secrets.token_hex(16)
        nonce = prepare_nonce  # mirror for legacy readers; finalize requires prepare_nonce
        action_sid = make_action_session_id(run_id, action_id, prepare_nonce)
        sdir = _session_dir(project_root, run_id, action_id)
        sdir.mkdir(parents=True, exist_ok=True)
        staging_dir(sdir).mkdir(parents=True, exist_ok=True)

    repo = _repo_root(project_root)
    method, prompt = _load_method_and_prompt(repo, action)
    if execution_mode == EXECUTION_SUBAGENT and str(action.get("task_prompt_id") or "").strip():
        mp = _resolve_capability_method(repo, action)
        if mp is None or not mp.is_file() or not str(method or "").strip():
            sid = str(action.get("skill_id") or action.get("action_method_id") or "")
            return {
                "ok": False,
                "error": "SKILL_MISSING",
                "reason_code": "SKILL_MISSING",
                "message_zh": (
                    f"Action {action_id} missing SKILL.md for {sid or '(no skill_id)'}。"
                ),
                "skill_id": sid,
            }
    if execution_mode in {EXECUTION_SUBAGENT, EXECUTION_PRIMARY_INTERACTIVE}:
        tpid = str(action.get("task_prompt_id") or "")
        if tpid and not str(prompt or "").strip():
            return {
                "ok": False,
                "error": "TASK_PROMPT_MISSING",
                "message_zh": f"Action {action_id} missing task prompt {tpid}",
                "task_prompt_id": tpid,
            }
    if execution_mode == EXECUTION_PRIMARY_INTERACTIVE:
        if not str(method or "").strip():
            method = (
                "# Host-owned confirmation\n"
                "Surface ask_question.options verbatim. Do not load domain skills.\n"
            )
        if not str(prompt or "").strip():
            prompt = "# Host-owned confirmation\n"
    root_s = Path(project_root).expanduser().resolve().as_posix()
    try:
        architecture = require_architecture(str(state.get("architecture") or ""))
    except ValueError:
        return {
            "ok": False,
            "error": "ARCHITECTURE_MISSING_IN_RUN_STATE",
            "reason_code": "ARCHITECTURE_MISSING_IN_RUN_STATE",
        }
    uo_s = uo_root(project_root, arch=architecture).as_posix()
    tg_s = tg_root(project_root, arch=architecture).as_posix()
    op_name = str(state.get("op_name") or Path(project_root).name or "")
    ph_kwargs = {
        "run_id": run_id,
        "action_id": action_id,
        "workflow_id": wid,
        "actor_id": actor_id,
        "project_root": root_s,
        "uo_root": uo_s,
        "tg_root_path": tg_s,
        "topic": action_id,
        "op_name": op_name,
        "architecture": architecture,
        "role_id": role_id,
        "action_session_id": action_sid,
    }
    method_r = _render_placeholders(method, **ph_kwargs)
    prompt_r = _render_placeholders(prompt, **ph_kwargs)
    if action_id == "plan_fuse":
        captured = _load_tg_captured(project_root, run_id, "plan_scope")
        body = _scope_answer_for_fuse(captured)
        prompt_r = (
            prompt_r.rstrip()
            + "\n\n## Scope answer (not a file; Primary already read this)\n\n"
            + (body or "(empty — Primary must state what to test before fuse)")
            + "\n"
        )
    user_question = str(state.get("intent") or "").strip()
    if (
        user_question
        and action_id == "kb_lookup"
        and "## User question" not in prompt_r
    ):
        prompt_r = (
            prompt_r.rstrip()
            + "\n\n## User question\n\n"
            + user_question
            + "\n"
        )

    identity = build_bundle_identity(
        run_id=run_id,
        workflow_id=wid,
        phase=phase,
        action_id=action_id,
        actor_id=actor_id,
        role_id=role_id,
        action_session_id=action_sid,
        prepare_nonce=prepare_nonce,
        lease_id="",
        execution_mode=execution_mode,
    )
    bundle = {
        "version": 1,
        "identity": identity,
        "run_id": run_id,
        "workflow_id": wid,
        "phase": phase,
        "action_id": action_id,
        "actor_id": actor_id,
        "role_id": role_id,
        "execution_mode": execution_mode,
        "action_session_id": action_sid,
        "prepare_nonce": prepare_nonce,
        "nonce": nonce,
        "policy_ids": list(action.get("policy_ids") or []),
        "capability_ids": list(action.get("capability_ids") or []),
        "action_method_id": action.get("action_method_id"),
        "skill_id": action.get("skill_id"),
        "method_ref": action.get("method_ref"),
        "task_prompt_id": action.get("task_prompt_id"),
        "refs": list(action.get("refs") or []),
        "knowledge_refs": list(action.get("knowledge_refs") or []),
        "output_contract_id": action.get("output_contract_id"),
        "output_mode": str(action.get("output_mode") or "direct"),
        "staging_contract_id": action.get("staging_contract_id"),
        "checker_required": bool(action.get("checker_required", True)),
        "referee_required": bool(action.get("referee_required", False)),
        "pre_gates": list(action.get("pre_gates") or []),
        "post_gates": list(action.get("post_gates") or []),
        "project_root": root_s,
        "uo_root": uo_s,
        "tg_root": tg_s,
        "op_name": op_name,
        "architecture": architecture,
        "status": "prepared",
        "identity_note": (
            "Bundle identity supplied by Pilot is authoritative. "
            "Identity from any other artifact must not be used."
        ),
    }

    eng_ctx = _eng_ctx_from_state(
        state,
        run_id,
        consumes_state=list(action.get("consumes_state") or []),
        project_root=project_root,
    )
    if eng_ctx.get("ok") is False:
        return eng_ctx
    prepare_engine: dict[str, Any] | None = None
    # Staged LLM producers are not in ENGINE_REGISTRY. Deterministic promote
    # actions run at finalize, never auto-finalize a subagent scaffold.
    if execution_mode == EXECUTION_SUBAGENT:
        from ascendc_pilot.actions.engines import ENGINE_REGISTRY

        if (wid, action_id) in ENGINE_REGISTRY:
            try:
                scaffold = invoke_engine(project_root, wid, action_id, ctx=eng_ctx)
            except Exception:  # noqa: BLE001
                scaffold = None
            if isinstance(scaffold, dict) and scaffold.get("ok"):
                prepare_engine = scaffold
                bundle["prepare_engine"] = {
                    "ok": True,
                    "scaffold": True,
                    "engine": scaffold.get("engine"),
                }

    # Fail-closed: never dispatch a half-rendered prompt/method.
    unresolved = unresolved_placeholders(prompt_r) + unresolved_placeholders(method_r)
    if unresolved or prompt_has_unresolved(prompt_r) or prompt_has_unresolved(method_r):
        return {
            "ok": False,
            "error": "PROMPT_IDENTITY_UNRESOLVED",
            "unresolved": unresolved,
            "message_zh": "Task Prompt / METHOD 仍有未解析占位符；禁止派发",
        }

    prompt_path = (sdir / "prompt.md").as_posix()
    method_path = (sdir / "method.md").as_posix()
    bundle_path = (sdir / "bundle.yaml").as_posix()
    agent_root_posix = agent_root(project_root, architecture).as_posix()

    from ascendc_pilot.environment_capabilities import (
        source_scope_for_lease,
        write_environment_capabilities,
    )

    env_posix = ""
    if execution_mode != EXECUTION_DETERMINISTIC:
        env_path = write_environment_capabilities(
            sdir,
            project_root,
            architecture=architecture,
            run_id=run_id,
            host="opencode",
        )
        env_posix = env_path.as_posix()
    # Stub is built after write_paths are known (see below).
    stub = ""
    stub_pointers = None

    from ascendc_pilot.authorize.lease import issue_action_lease
    from datetime import datetime, timezone

    write_paths = list(action.get("allowed_write_paths") or [])
    if not write_paths:
        write_paths = action_write_paths(wid, action_id, run_id=run_id)
    else:
        write_paths = [expand_path_template(p, run_id=run_id) for p in write_paths]
    # Map-Reduce: prefer producer-only write paths from ownership + dispatch_targets.
    dt = bundle.get("dispatch_targets") if isinstance(bundle.get("dispatch_targets"), dict) else {}
    if dt.get("map_reduce"):
        from ascendc_pilot.ownership import action_producer_write_paths

        prod_writes = action_producer_write_paths(wid, action_id, run_id=run_id)
        if prod_writes:
            write_paths = list(prod_writes)
        if dt.get("write"):
            write_paths = [expand_path_template(p, run_id=run_id) for p in list(dt.get("write") or [])]
    forbid_write = [
        expand_path_template(p, run_id=run_id)
        for p in list(action.get("forbidden_write_paths") or [])
    ]
    if dt.get("forbid_write"):
        for p in dt.get("forbid_write") or []:
            ep = expand_path_template(str(p), run_id=run_id)
            if ep not in forbid_write:
                forbid_write.append(ep)
    read_paths = list(action.get("allowed_read_paths") or [])
    if not read_paths:
        from ascendc_pilot.ownership import action_read_paths

        read_paths = action_read_paths(wid, action_id, run_id=run_id)
    else:
        read_paths = [expand_path_template(p, run_id=run_id) for p in read_paths]
    if dt.get("map_reduce") and dt.get("read"):
        # Narrow action-level reads to Map-Reduce allow-list (+ session pack below).
        read_paths = [expand_path_template(p, run_id=run_id) for p in list(dt.get("read") or [])]
    # Session pack always readable (env capabilities + stubs).
    # Map-Reduce: do NOT open actions/{action_id}/** (would re-expose all batches).
    session_extras = [
        f"runs/{run_id}/actions/{action_id}/environment_capabilities.yaml",
        f"runs/{run_id}/actions/{action_id}/prompt.md",
        f"runs/{run_id}/actions/{action_id}/method.md",
        f"runs/{run_id}/actions/{action_id}/bundle.yaml",
        f"runs/{run_id}/actions/{action_id}/session_state.yaml",
        f"runs/{run_id}/actions/{action_id}/knowledge/**",
    ]
    if not dt.get("map_reduce"):
        session_extras.insert(0, f"runs/{run_id}/actions/{action_id}/**")
    for extra in session_extras:
        if extra not in read_paths:
            read_paths.append(extra)
    forbid_read = [
        expand_path_template(p, run_id=run_id)
        for p in list(action.get("forbidden_read_paths") or [])
    ]
    if not forbid_read:
        from ascendc_pilot.ownership import action_forbidden_read_paths

        forbid_read = action_forbidden_read_paths(wid, action_id, run_id=run_id)
    # Dispatch targets may further narrow write paths for producers.
    if dt.get("write"):
        write_paths = [expand_path_template(str(p), run_id=run_id) for p in dt["write"]]
    if dt.get("forbid_write"):
        forbid_write = [
            expand_path_template(str(p), run_id=run_id) for p in dt["forbid_write"]
        ] + forbid_write
    if dt.get("read") and not dt.get("map_reduce"):
        read_paths = [expand_path_template(str(p), run_id=run_id) for p in dt["read"]]
    if dt.get("forbid_read"):
        forbid_read = [
            expand_path_template(str(p), run_id=run_id) for p in dt["forbid_read"]
        ] + forbid_read
    # Always allow re-reading Action write targets (producer self-check / rework).
    # Root cause: write-only lease blocked Read of write targets after Write.
    for wp in write_paths:
        wps = expand_path_template(str(wp), run_id=run_id)
        if wps and wps not in read_paths:
            read_paths.append(wps)
    # Stub tells producer to read prompt/method/bundle first — lease the
    # prepared action session pack. Map-Reduce must NOT open actions/** or
    # every batch becomes readable again (narrow reads already set above).
    if run_id and action_id and not dt.get("map_reduce"):
        session_pack = f"runs/{run_id}/actions/{action_id}/**"
        read_paths = [session_pack, *read_paths]
    # De-dupe while preserving order.
    if forbid_read:
        seen_fr: set[str] = set()
        deduped_fr: list[str] = []
        for p in forbid_read:
            if p not in seen_fr:
                seen_fr.add(p)
                deduped_fr.append(p)
        forbid_read = deduped_fr
    if read_paths:
        seen_rp: set[str] = set()
        deduped_rp: list[str] = []
        for p in read_paths:
            if p not in seen_rp:
                seen_rp.add(p)
                deduped_rp.append(p)
        read_paths = deduped_rp
    if execution_mode == EXECUTION_PRIMARY_INTERACTIVE:
        writable = {"ok": True, "skipped": True, "reason": "host_owned_confirm"}
    else:
        output_mode = str(action.get("output_mode") or "direct")
        if output_mode == "staged":
            check_contract_id = str(action.get("staging_contract_id") or "")
        else:
            check_contract_id = str(action.get("output_contract_id") or "")
        writable = _check_required_outputs_writable(
            workflow_id=wid,
            action_id=action_id,
            actor_id=actor_id,
            contract_id=check_contract_id,
            output_mode=output_mode,
            write_paths=write_paths,
            run_id=run_id,
            project_root=project_root,
        )
    if not writable.get("ok"):
        return {
            "ok": False,
            "error": str(writable.get("error") or "OUTPUT_NOT_WRITABLE"),
            "reason_code": "OUTPUT_NOT_WRITABLE",
            "writable_check": writable,
            "message_zh": str(writable.get("message_zh") or "合同产物写面未闭合"),
        }
    allowed_targets = [str(x) for x in (dt.get("target_ids") or []) if str(x).strip()]
    # Outer containment: workflow write_roots; precise paths are Action lease.
    wf_roots = list((get_workflow(wid, project_root=project_root) or {}).get("write_roots") or [])
    src_scope = source_scope_for_lease(project_root, run_id=run_id)
    lease = issue_action_lease(
        project_root,
        state=state,
        action_id=action_id,
        actor_id=actor_id,
        mode="normal",
        allowed_read_roots=[sdir.as_posix()],
        allowed_write_roots=wf_roots,
        allowed_write_paths=write_paths,
        allowed_read_paths=read_paths,
        forbidden_write_paths=forbid_write,
        forbidden_read_paths=forbid_read,
        allowed_target_ids=allowed_targets,
        allowed_source_roots=src_scope.get("allowed_source_roots") or [],
        allowed_source_files=src_scope.get("allowed_source_files") or [],
    )
    lease_id = str(lease.get("lease_id") or "")
    prepared_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    bundle["lease_id"] = lease_id
    bundle["prepared_at"] = prepared_at
    bundle["identity"] = build_bundle_identity(
        run_id=run_id,
        workflow_id=wid,
        phase=phase,
        action_id=action_id,
        actor_id=actor_id,
        role_id=role_id,
        action_session_id=action_sid,
        prepare_nonce=prepare_nonce,
        lease_id=lease_id,
        execution_mode=execution_mode,
    )
    bundle["allowed_write_paths"] = write_paths
    bundle["forbidden_write_paths"] = forbid_write
    bundle["allowed_read_paths"] = read_paths
    bundle["forbidden_read_paths"] = forbid_read
    bundle["allowed_target_ids"] = allowed_targets
    bundle["staging_dir"] = staging_dir(sdir).as_posix()

    if execution_mode == EXECUTION_SUBAGENT and not dt.get("map_reduce"):
        stub_kwargs = {
            "actor_id": actor_id,
            "action_id": action_id,
            "run_id": run_id,
            "session_dir": sdir.as_posix(),
            "prompt_path": prompt_path,
            "method_path": method_path,
            "bundle_path": bundle_path,
            "dispatch_targets": dt if isinstance(dt, dict) else None,
            "agent_root_path": agent_root_posix,
            "project_root": root_s,
            "architecture": architecture,
            "candidates_sha256": str(
                bundle.get("candidates_sha256") or ph_kwargs.get("candidates_sha256") or ""
            ),
            "environment_path": env_posix,
            "write_paths": write_paths,
            "user_question": user_question,
        }
        stub, stub_pointers = build_task_stub(**stub_kwargs)
        bundle["task_prompt_stub"] = stub
        bundle["stub_pointers"] = stub_pointers.as_dict()
        try:
            fanout = _review_axis_fanout_tasks(
                action=action,
                action_id=action_id,
                actor_id=actor_id,
                phase=phase,
                sdir=sdir,
                stub_kwargs=stub_kwargs,
                repo=repo,
                dispatch_targets=dt if isinstance(dt, dict) else None,
                write_paths=write_paths,
                project_root=root_s,
                architecture=architecture,
            )
        except FanoutPrepareError as exc:
            know = exc.result
            return {
                "ok": False,
                "error": str(know.get("error") or "KNOWLEDGE_MISSING"),
                "reason_code": str(know.get("reason_code") or "KNOWLEDGE_MISSING"),
                "missing": know.get("missing") or [],
                "message_zh": str(know.get("message_zh") or "knowledge_refs 缺失；禁止派发"),
                "action_id": action_id,
                "session_dir": sdir.as_posix(),
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "ok": False,
                "error": "METHOD_BUNDLE_FAILED",
                "reason_code": "METHOD_BUNDLE_FAILED",
                "message_zh": f"fanout METHOD/knowledge 装配异常：{exc}；禁止派发",
                "action_id": action_id,
                "session_dir": sdir.as_posix(),
            }
        if fanout:
            bundle["dispatch_tasks"] = fanout

    _dump_session_state(sdir, bundle)
    if execution_mode != EXECUTION_DETERMINISTIC:
        (sdir / "method.md").write_text(method_r, encoding="utf-8")
        (sdir / "prompt.md").write_text(prompt_r, encoding="utf-8")

    # Materialize Action METHOD + named refs. Never concatenate Agent SKILL.md.
    # Host-owned confirmations skip skill trees entirely.
    try:
        from ascendc_pilot.actions.method_bundle import (
            check_bundle_readable,
            materialize_method_bundle,
        )

        if execution_mode == EXECUTION_PRIMARY_INTERACTIVE:
            bundle["method_materialized"] = {
                "copied": [],
                "missing": [],
                "ok": True,
                "host_owned_confirm": True,
            }
        elif execution_mode == EXECUTION_PRIMARY_REVIEW:
            bundle["method_materialized"] = {
                "copied": [],
                "missing": [],
                "ok": True,
                "primary_review": True,
            }
        elif execution_mode == EXECUTION_SUBAGENT:
            from ascendc_pilot.actions.method_bundle import method_skill_ids_for_action
            from ascendc_pilot.agents_registry import agent_skill_ceiling

            ceiling = agent_skill_ceiling(actor_id, project_root)
            extra_refs: list[str] = []
            skill_ids = method_skill_ids_for_action(
                action,
                agent_skill_ids=ceiling,
                extra_ref_paths=extra_refs,
            )
            action_skill = str(action.get("skill_id") or action.get("action_method_id") or "").rsplit("/", 1)[-1]
            axes = list(action.get("fanout_axes") or [])
            copy_declared = not (
                bool(axes) and all(str(a.get("method_ref") or "").strip() for a in axes)
            )
            mat = materialize_method_bundle(
                sdir,
                skill_ids=[str(x) for x in skill_ids],
                existing_method=method_r,
                project_root=project_root,
                extra_ref_paths=extra_refs,
                current_skill_id=action_skill,
                copy_declared_refs=copy_declared,
                explicit_refs=[str(r).strip() for r in (action.get("refs") or []) if str(r).strip()],
            )
            bundle["method_skill_ids"] = skill_ids
            bundle["agent_skill_ceiling"] = [str(x) for x in ceiling]
            bundle["method_materialized"] = {
                "copied": mat.get("copied") or [],
                "missing": mat.get("missing") or [],
                "ok": bool(mat.get("ok")),
            }
            if not mat.get("ok"):
                return {
                    "ok": False,
                    "error": str(mat.get("error") or "METHOD_BUNDLE_MISSING"),
                    "reason_code": str(mat.get("reason_code") or "METHOD_BUNDLE_MISSING"),
                    "missing": mat.get("missing") or [],
                    "message_zh": str(
                        mat.get("message_zh")
                        or "Required METHOD missing；禁止派发"
                    ),
                    "action_id": action_id,
                    "session_dir": sdir.as_posix(),
                }
            from ascendc_pilot.actions.method_bundle import materialize_knowledge_refs

            know = materialize_knowledge_refs(
                sdir,
                list(action.get("knowledge_refs") or []),
                project_root=project_root,
            )
            bundle["knowledge_materialized"] = {
                "copied": know.get("copied") or [],
                "missing": know.get("missing") or [],
                "ok": bool(know.get("ok")),
            }
            if not know.get("ok"):
                return {
                    "ok": False,
                    "error": str(know.get("error") or "KNOWLEDGE_MISSING"),
                    "reason_code": str(know.get("reason_code") or "KNOWLEDGE_MISSING"),
                    "missing": know.get("missing") or [],
                    "message_zh": str(know.get("message_zh") or "knowledge_refs 缺失；禁止派发"),
                    "action_id": action_id,
                    "session_dir": sdir.as_posix(),
                }
        else:
            bundle["method_materialized"] = {"ok": True, "skipped": "deterministic"}
        # Session refs always readable.
        refs_glob = f"runs/{run_id}/actions/{action_id}/refs/**"
        if refs_glob not in read_paths:
            read_paths.append(refs_glob)
            lease_read_extra = True
        else:
            lease_read_extra = False
        if lease_read_extra:
            # Re-issue is heavy; append into active lease file best-effort.
            try:
                from ascendc_pilot.authorize.lease import load_lease, lease_path
                import yaml as _yaml

                cur = load_lease(project_root, run_id=run_id)
                if cur and str(cur.get("status") or "") == "active":
                    ar = list(cur.get("allowed_read_paths") or [])
                    if refs_glob not in ar:
                        ar.append(refs_glob)
                        cur["allowed_read_paths"] = ar
                        lease_path(project_root, run_id=run_id).write_text(
                            _yaml.safe_dump(cur, allow_unicode=True, sort_keys=False),
                            encoding="utf-8",
                        )
            except Exception:  # noqa: BLE001
                pass
    except Exception as _mat_exc:  # noqa: BLE001
        return {
            "ok": False,
            "error": "METHOD_BUNDLE_FAILED",
            "reason_code": "METHOD_BUNDLE_FAILED",
            "message_zh": f"METHOD/knowledge 装配异常：{_mat_exc}；禁止派发",
            "action_id": action_id,
            "session_dir": sdir.as_posix(),
        }

    # Write bundle.yaml before BUNDLE_NOT_READABLE: the check always requires
    # the session pack (prompt/method/bundle). Dumping after the check made
    # the first kb_lookup prepare fail on its own missing bundle.yaml.
    if yaml is not None:
        digest_src = yaml.safe_dump(
            {k: v for k, v in bundle.items() if k not in {"nonce", "prepare_nonce", "bundle_digest"}},
            allow_unicode=True,
            sort_keys=True,
        )
        bundle["bundle_digest"] = hashlib.sha256(digest_src.encode("utf-8")).hexdigest()[:16]
    _dump_session_state(sdir, bundle)
    _dump(
        sdir / "bundle.yaml",
        {k: v for k, v in bundle.items() if k not in {"nonce", "prepare_nonce"}},
    )
    if stub:
        (sdir / "task_prompt_stub.md").write_text(stub, encoding="utf-8")
        from ascendc_pilot.actions.method_bundle import check_bundle_readable

        try:
            br = check_bundle_readable(
                stub=stub,
                pointers=stub_pointers,
                session_dir=sdir,
                project_root=project_root,
                allowed_read_paths=read_paths,
                allowed_write_paths=write_paths,
                allowed_source_roots=list(
                    (src_scope or {}).get("allowed_source_roots") or []
                ),
            )
        except Exception as exc:  # noqa: BLE001
            return {
                "ok": False,
                "error": "BUNDLE_NOT_READABLE",
                "reason_code": "BUNDLE_NOT_READABLE",
                "message_zh": f"Action Bundle 读闭合检查异常：{exc}",
                "action_id": action_id,
                "session_dir": sdir.as_posix(),
            }
        if not br.get("ok"):
            return {
                "ok": False,
                "error": str(br.get("error") or "BUNDLE_NOT_READABLE"),
                "reason_code": str(br.get("reason_code") or "BUNDLE_NOT_READABLE"),
                "missing": br.get("missing") or [],
                "unleased": br.get("unleased") or [],
                "unwritable": br.get("unwritable") or [],
                "message_zh": br.get("message_zh")
                or "Action Bundle 读闭合失败；禁止派发",
                "action_id": action_id,
                "session_dir": sdir.as_posix(),
            }
    _write_active_action(
        project_root,
        {
            "version": 1,
            "run_id": run_id,
            "workflow_id": wid,
            "phase": phase,
            "action_id": action_id,
            "actor_id": actor_id,
            "role_id": role_id,
            "execution_mode": execution_mode,
            "action_session_id": action_sid,
            "session_dir": sdir.as_posix(),
            "prepare_nonce": prepare_nonce,
            "lease_id": lease_id,
            "status": "prepared",
            "allowed_write_paths": write_paths,
            "forbidden_write_paths": forbid_write,
            "allowed_read_paths": read_paths,
            "forbidden_read_paths": forbid_read,
        },
    )

    append_event(
        project_root,
        {
            "type": "ActionPrepared",
            "action_id": action_id,
            "actor_id": actor_id,
            "role_id": role_id,
            "execution_mode": execution_mode,
            "lease_id": lease_id,
            "prepare_nonce": prepare_nonce,
            "action_session_id": action_sid,
        },
        run_id=run_id,
    )

    if action_id == "kb_lookup" or actor_id == "uo-query":
        try:
            from ascendc_pilot.authorize.exploration_budget import init_budget

            init_budget(project_root, run_id=run_id, action_id=action_id)
        except Exception:  # noqa: BLE001
            pass

    result: dict[str, Any] = {
        "ok": True,
        "phase_runtime": "prepare",
        "action_id": action_id,
        "workflow_id": wid,
        "actor_id": actor_id,
        "role_id": role_id,
        "execution_mode": execution_mode,
        "action_session_id": action_sid,
        "run_id": run_id,
        "session_dir": sdir.as_posix(),
        "bundle_path": (sdir / "bundle.yaml").as_posix(),
        "prompt_path": (sdir / "prompt.md").as_posix(),
        "method_path": (sdir / "method.md").as_posix(),
        "primary_instructions_path": (sdir / "prompt.md").as_posix(),
        "lease_id": lease_id,
        "prepare_nonce": prepare_nonce,
        "auto_finalize": False,
        "identity": bundle["identity"],
    }
    if prepare_engine is not None:
        result["prepare_engine"] = prepare_engine

    pre_results = _run_action_gates(project_root, list(action.get("pre_gates") or []))
    pre_ok = all(g.get("ok") for g in pre_results) if pre_results else True
    if pre_results:
        result["pre_gates"] = pre_results
    if not pre_ok:
        result["ok"] = False
        result["error"] = "PRE_GATES_FAILED"
        result["reason_code"] = "PRE_GATES_FAILED"
        result["message_zh"] = "前置 gate 未通过；禁止执行 Actor"
        return result

    if execution_mode == EXECUTION_DETERMINISTIC or role_id == "deterministic_engine":
        eng = invoke_engine(project_root, wid, action_id, ctx=eng_ctx)
        result["engine"] = eng
        if isinstance(eng, dict) and eng.get("receipt_path"):
            result["receipt_path"] = eng["receipt_path"]
        if isinstance(eng, dict) and eng.get("needs_human_decision"):
            result["needs_human_decision"] = True
            if isinstance(eng.get("ask_question"), dict):
                result["ask_question"] = eng["ask_question"]
            result["ok"] = True
            result["auto_finalize"] = False
            result["message_zh"] = str(
                eng.get("message_zh")
                or (eng.get("ask_question") or {}).get("question")
                or "需要人工选择后再继续。"
            )
            return result
        if isinstance(eng, dict) and not eng.get("ok", True):
            from ascendc_pilot.actions.failure_text import preferred_failure_text, with_failure_hint

            result["error"] = str(eng.get("error") or "ENGINE_FAILED")
            result["reason_code"] = str(eng.get("reason_code") or eng.get("error") or "ENGINE_FAILED")
            result["message_zh"] = with_failure_hint(
                str(eng.get("message_zh") or preferred_failure_text(eng)),
                eng,
            )
            if eng.get("issues"):
                result["issues"] = eng.get("issues")
        fin = finalize_action(project_root, action_id, engine_result=eng)
        result["auto_finalize"] = True
        result["finalize"] = fin
        result["ok"] = bool(fin.get("ok"))
        if not result["ok"]:
            from ascendc_pilot.actions.failure_text import preferred_failure_text, with_failure_hint

            result["error"] = str(
                result.get("error") or fin.get("error") or (eng.get("error") if isinstance(eng, dict) else "") or "ENGINE_FAILED"
            )
            result["message_zh"] = with_failure_hint(
                str(result.get("message_zh") or preferred_failure_text(result)),
                result,
            )
        return result

    if execution_mode == EXECUTION_PRIMARY_INTERACTIVE:
        from ascendc_pilot.human_confirm import (
            build_ask,
            hosted_confirm_should_ask,
            interaction_kind,
            materialize_primary_decision,
            primary_interactive_steps,
        )
        from ascendc_pilot.human_interaction import (
            KIND_PRIMARY_APPROVE,
            KIND_PRIMARY_CONFIRM,
            attach_interaction_request,
        )
        from ascendc_pilot.state import load_state as _load_state_for_voice

        voice_state = dict(_load_state_for_voice(project_root) or state or {})
        if not voice_state.get("workflow_id"):
            voice_state["workflow_id"] = wid
        if action_id in {
            "human_confirm",
            "plan_approve",
            "apply_report",
            "review_report",
        }:
            if not hosted_confirm_should_ask(project_root, voice_state, action_id=action_id):
                materialized = materialize_primary_decision(project_root, action_id)
                if materialized.get("ok"):
                    fin = finalize_action(project_root, action_id, engine_result=materialized)
                    if fin.get("ok"):
                        result["auto_skip_human_gate"] = True
                        result["needs_human_decision"] = False
                        result["auto_finalize"] = True
                        result["finalize"] = fin
                        result["ok"] = True
                        result["message_zh"] = "已自动完成本步确认。"
                        return result
                # Keep the prepared session (method.md already written). Real
                # runs have init/plan products so auto-issue succeeds; unit
                # prepares without those products still return a Host session.
        ask = build_ask(
            project_root,
            voice_state,
            workflow_id=wid,
            action_id=action_id,
        )
        kind_s = interaction_kind(
            project_root, action_id, workflow_id=wid, state=voice_state
        )
        kind = KIND_PRIMARY_APPROVE if kind_s == "primary_approve" else KIND_PRIMARY_CONFIRM
        user_summary = ask.get("question") or ""
        result["needs_human_decision"] = True
        result["ask_question"] = ask
        result["action_id"] = action_id
        result["user_summary_zh"] = user_summary
        result = attach_interaction_request(
            result,
            project_root,
            kind=kind,
            action_id=action_id,
        )
        result["interactive_steps"] = primary_interactive_steps(
            action_id, project_root, result, workflow_id=wid
        )
        # Machine-facing dispatch note for Primary; Host shows ask_question / user_summary_zh.
        result["message_zh"] = (
            "已准备需要你确认的步骤。请按弹出的选项作答；"
            "作答写入后才能完成本步并进入下一阶段。"
        )
        result["dispatch_task"] = False
        return result

    if execution_mode == EXECUTION_PRIMARY_REVIEW:
        if action_id == "plan_narrate":
            return _complete_plan_narrate_prepare(
                project_root,
                run_id=run_id,
                sdir=sdir,
                result=result,
                intent=str(turn_intent or current_turn_intent() or ""),
            )
        return _complete_bind_review_prepare(
            project_root,
            run_id=run_id,
            sdir=sdir,
            result=result,
            intent=str(turn_intent or current_turn_intent() or ""),
        )

    fanout_tasks = [
        row
        for row in (bundle.get("dispatch_tasks") or [])
        if isinstance(row, dict) and str(row.get("task_prompt_stub") or "").strip()
    ]
    if len(fanout_tasks) >= 2:
        result["dispatch_tasks"] = fanout_tasks
        if action_id == "bind_init":
            from testcase_agent.bind_parts import is_bind_chunk_id

            n_bind = sum(
                1
                for t in fanout_tasks
                if is_bind_chunk_id(str(t.get("slice_id") or ""))
            )
            n_harness = sum(
                1 for t in fanout_tasks if str(t.get("slice_id") or "") == "harness"
            )
            result["message_zh"] = (
                f"已准备 {len(fanout_tasks)} 个 Task（{n_harness} 路 harness + {n_bind} 路 bind，"
                "每路 bind ≤20 列）。"
                "同一轮并行最好；每条 prompt 必须原样为 `dispatch_tasks[i].task_prompt_stub`。"
                "禁止用父 `task_prompt_stub` 再开一个。"
                "列数由引擎按表头切开，不要自己改路数。"
                "子代理写完后引擎合并 harness.yaml 与全部 bindN.yaml → bind.yaml。"
                "若磁盘已齐，下一轮 `pilot_run` 收齐，不要重派、不要 force_new。"
                "对人只说 golden/精度口径与列映射是否齐，不要套审查完成模板。"
                "禁止发明子代理没引用的事实。不要再调 workflow=auto 做 intake。"
            )
        else:
            result["message_zh"] = (
                f"已准备 {len(fanout_tasks)} 个并行 Task（agent=`{actor_id}`，同一 Action `{action_id}` / 一张 ticket）。"
                "同一轮用 OpenCode 原生 Task 全部派发；每条 prompt 必须原样为 "
                "`dispatch_tasks[i].task_prompt_stub`。"
                "禁止用父 `task_prompt_stub` 再开一个。"
                "插件用各 Task 原文 ACK 并推进 task_plan 下一格。"
                "Primary 只把两段原文用人话合并给用户（审查完成 / 做什么 / 改了什么 / 问题 / 要测变量）。"
                "禁止综合成 kb-answer-v1。禁止发明子代理没引用的事实。不要再调 workflow=auto 做 intake。"
            )
    elif len(fanout_tasks) == 1:
        result["dispatch_tasks"] = fanout_tasks
        result["task_prompt_stub"] = fanout_tasks[0]["task_prompt_stub"]
        slice_id = str(fanout_tasks[0].get("slice_id") or "")
        result["message_zh"] = (
            f"已准备 1 个 Task（agent=`{actor_id}`，切片 `{slice_id}` / Action `{action_id}`）。"
            "Task 正文必须原样为该切片的 `task_prompt_stub`。禁止用父 stub 再开一个。"
        )
    else:
        result["message_zh"] = (
            f"已准备 Action Runtime Bundle；派发 actor `{actor_id}` 时 "
            f"Task 正文只用返回的 `task_prompt_stub`（或 session 下 task_prompt_stub.md）；"
            f"禁止复述 METHOD / 禁止塞额外目标 / 禁止整包粘贴大文件。"
            f"subagent_type/agent=`{actor_id}`，action_id={action_id}。"
            f"Primary 禁止代写正式 IR。"
        )
    if str(action.get("output_mode") or "") == "return_value":
        if len(fanout_tasks) >= 2:
            result["message_zh"] += (
                " 每个子代理最终消息用完整自然语言交回（OpenCode 原生 Task，像 Cursor Explore）；"
                " 不要把证据压进 yaml。切片 Task 不会注入 return_value；Primary 综合原生返回后由 Host `pilot_run` 完成本步。"
            )
        else:
            result["message_zh"] += (
                f" 子代理最终消息用完整自然语言交回（原生 Task / Explore）；"
                f" 禁止 Write answer.yaml/scratch。"
                f" Task 结束后若 metadata 含 `ascendc_uo_query_return_value.captured=true`，"
                f" Host `pilot_run` 完成本步（插件注入全文）；"
                f" 禁止再手写 scratch yaml。"
            )
            if action_id == "plan_scope":
                result["message_zh"] += (
                    " plan_scope 像 uo-query：子代理只把要测的东西说清楚；"
                    "Primary 读回答即可，禁止写文件，不要等 targets.yaml。"
                )
        result["finalize_hint"] = "pilot_run"
        result["finalize_hint_fallback"] = ""
    else:
        result["message_zh"] += " 完成后由 Host `pilot_run` 完成本步。"
    if len(fanout_tasks) != 1:
        result["task_prompt_stub"] = stub
    result["task_prompt_stub_path"] = (sdir / "task_prompt_stub.md").as_posix()
    result["dispatch_task"] = True
    try:
        from ascendc_pilot.actions.action_dispatch import (
            load_dispatch,
            prepare_resume_fields,
            write_dispatch,
        )

        resume_fields = prepare_resume_fields(
            project_root,
            run_id=run_id,
            action_id=action_id,
            workflow_status=str(state.get("status") or ""),
        )
        result.update(resume_fields)
        prev_dispatch = load_dispatch(project_root, run_id, action_id)
        write_dispatch(
            project_root,
            run_id,
            action_id,
            {
                "workflow_id": wid,
                "actor_id": actor_id,
                "action_session_id": action_sid,
                "dispatch_attempt": int(prev_dispatch.get("dispatch_attempt") or 0) + 1,
                **resume_fields,
            },
        )
        if resume_fields.get("resume_required"):
            result["message_zh"] = (
                str(result.get("message_zh") or "")
                + f" rework 必须 Task(resume={resume_fields.get('resume_session_id')})；"
                "禁止无条件重新 propose candidates。"
            )
    except Exception:  # noqa: BLE001
        result.setdefault("resume_required", False)
        result.setdefault("resume_session_id", "")
    return result


def _iter_identity_stamp_paths(
    project_root: Path,
    *,
    session: dict[str, Any],
    action_id: str,
    contract_id: str,
) -> list[Path]:
    """YAML mappings the finalizer stamps: staging/output contract + owned UO receipts."""
    from ascendc_pilot.ownership import expand_contract_paths

    root = agent_root(project_root, _arch_for(project_root))
    run_id = str(session.get("run_id") or "")
    paths: list[Path] = []
    seen: set[str] = set()

    def _add(path: Path) -> None:
        if not path.is_file():
            return
        if path.suffix.lower() not in {".yaml", ".yml"}:
            return
        key = path.resolve().as_posix()
        if key in seen:
            return
        seen.add(key)
        paths.append(path)

    for rel in expand_contract_paths(
        list(OUTPUT_CONTRACT_PATHS.get(contract_id) or []),
        run_id=run_id,
        workflow_id=str(session.get("workflow_id") or ""),
        action_id=str(session.get("action_id") or action_id),
        actor_id=str(session.get("actor_id") or ""),
        action_session_id=str(session.get("action_session_id") or ""),
    ):
        for match in _resolve_contract_paths(root, rel):
            if match.is_file():
                _add(match)
            elif match.is_dir():
                for child in match.rglob("*"):
                    _add(child)
    owned = _finalize_owned_artifact_path(project_root, session=session, action_id=action_id)
    if owned is not None:
        _add(owned)
        if action_id in _SCOPE_GATE_ACTION_IDS:
            _add(owned.parent / "receipt.yaml")
    return paths


def _finalize_restore_bind_parts(
    project_root: Path,
    *,
    session: dict[str, Any],
    action_id: str,
) -> dict[str, Any]:
    """Restore engine-owned cells; never yaml.safe_load+stamp LLM bind parts."""
    del action_id
    from ascendc_pilot.paths import agent_root

    run_id = str(session.get("run_id") or "")
    arch = str(session.get("architecture") or "").strip() or _arch_for(project_root) or None
    parts = (
        agent_root(project_root, arch)
        / "runs"
        / run_id
        / "actions"
        / "bind_init"
        / "parts"
    )
    owned = parts / ".engine"
    if not owned.is_dir():
        return {"ok": True, "skipped": True, "reason": "no_owned_snapshot", "contract_id": "tg-bind-staging-v1"}
    try:
        from testcase_agent.bind_parts import restore_and_dump_parts

        restored = restore_and_dump_parts(parts)
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "error": "BIND_PART_YAML_INVALID",
            "message": str(exc),
            "path": parts.as_posix(),
            "contract_id": "tg-bind-staging-v1",
        }
    if not restored.get("ok"):
        return {
            "ok": False,
            "error": "BIND_PART_INVALID",
            "message": "; ".join(str(x) for x in (restored.get("errors") or [])),
            "errors": restored.get("errors") or [],
            "contract_id": "tg-bind-staging-v1",
        }
    from ascendc_pilot.ownership import artifact_identity_from_session, inject_trusted_identity
    from testcase_agent.bind_parts import dump_part

    identity = artifact_identity_from_session(session)
    for name in ("bind.yaml", "harness.yaml"):
        path = parts / name
        if not path.is_file():
            continue
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if isinstance(doc, dict):
            dump_part(path, inject_trusted_identity(doc, identity))
    return {"ok": True, "skipped": True, "reason": "bind_parts_engine_owned", "contract_id": "tg-bind-staging-v1"}


def _finalize_inject_artifact_identity(
    project_root: Path,
    *,
    session: dict[str, Any],
    action_id: str,
    contract_id: str,
) -> dict[str, Any]:
    """Overwrite LLM-declared identity with session-trusted artifact_identity."""
    from ascendc_pilot.ownership import artifact_identity_from_session, inject_trusted_identity

    if contract_id == "tg-bind-staging-v1":
        return {
            "ok": True,
            "skipped": True,
            "reason": "bind_parts_engine_owned",
            "contract_id": contract_id,
        }
    identity = artifact_identity_from_session(session)
    targets = _iter_identity_stamp_paths(
        project_root, session=session, action_id=action_id, contract_id=contract_id
    )
    if not targets:
        return {"ok": True, "skipped": True, "reason": "no_owned_artifact", "contract_id": contract_id}
    if yaml is None:
        return {
            "ok": False,
            "error": "IDENTITY_INJECTION_UNAVAILABLE",
            "message": "PyYAML is required to stamp artifact identity",
            "contract_id": contract_id,
        }

    def _stamp_scope_safe(raw: dict[str, Any], path: Path) -> dict[str, Any]:
        """Stamp nested artifact_identity; keep top-level gate action_id."""
        prior_action = str(raw.get("action_id") or "").strip()
        stamped = inject_trusted_identity(raw, identity)
        if _is_run_scoped_scope_artifact(path) or (
            action_id in _SCOPE_GATE_ACTION_IDS and path.name in {"scope_validated.yaml", "receipt.yaml"}
        ):
            if prior_action in _SCOPE_GATE_ACTION_IDS and prior_action != "prepare":
                stamped["action_id"] = prior_action
            else:
                stamped["action_id"] = "scope_validated"
        return stamped

    stamped_paths: list[str] = []
    for path in targets:
        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception as exc:  # noqa: BLE001
            return {
                "ok": False,
                "error": "IDENTITY_INJECTION_READ_FAILED",
                "path": path.as_posix(),
                "message": str(exc),
            }
        if not isinstance(doc, dict):
            continue
        try:
            _dump(path, _stamp_scope_safe(doc, path))
        except Exception as exc:  # noqa: BLE001
            return {
                "ok": False,
                "error": "IDENTITY_INJECTION_WRITE_FAILED",
                "path": path.as_posix(),
                "message": str(exc),
            }
        stamped_paths.append(path.as_posix())
    return {
        "ok": True,
        "skipped": not stamped_paths,
        "paths": stamped_paths,
        "contract_id": contract_id,
    }




def _revoke_lease_after_finalize(
    project_root: Path,
    *,
    reason: str,
    touch_active_action: bool,
    run_id: str = "",
) -> None:
    try:
        from ascendc_pilot.authorize.lease import revoke_active_lease

        revoke_active_lease(
            project_root,
            reason=reason,
            touch_active_action=touch_active_action,
            run_id=run_id,
        )
    except Exception:  # noqa: BLE001
        pass


def _finalize_bind_session_lease(
    project_root: Path,
    *,
    session: dict[str, Any],
    action_id: str,
    run_id: str,
    wid: str,
    phase: str,
    sdir: Path,
) -> dict[str, Any] | None:
    """Return an error payload if prepare session / active_action / lease binding fails."""
    from ascendc_pilot.authorize.lease import active_action_path, is_lease_revoked, load_lease

    prepare_nonce = str(session.get("prepare_nonce") or "").strip()
    if not prepare_nonce:
        if session.get("nonce"):
            return {
                "ok": False,
                "error": "PREPARE_SESSION_MIGRATION_REQUIRED",
                "message_zh": "session 缺少 prepare_nonce（旧格式）；请重新 prepare",
            }
        return {
            "ok": False,
            "error": "no_session",
            "message_zh": "缺少 prepare session；请由 Host `pilot_run` 重新准备本步",
        }

    session_lease = str(session.get("lease_id") or "").strip()
    if not session_lease:
        return {
            "ok": False,
            "error": "SESSION_LEASE_MISMATCH",
            "message_zh": "session 缺少 lease_id；请重新 prepare",
        }

    if str(session.get("run_id")) != run_id or str(session.get("action_id")) != action_id:
        return {"ok": False, "error": "session_mismatch"}
    if str(session.get("workflow_id") or "") != wid:
        return {
            "ok": False,
            "error": "session_workflow_mismatch",
            "message_zh": (
                f"session workflow `{session.get('workflow_id')}` 与当前 `{wid}` 不一致；"
                "禁止跨工作流 finalize"
            ),
        }
    if str(session.get("phase") or "") != phase:
        return {
            "ok": False,
            "error": "session_phase_mismatch",
            "message_zh": (
                f"prepare 时阶段为 `{session.get('phase')}`，当前为 `{phase}`；"
                "阶段已切换，禁止 finalize 原 Action"
            ),
            "session_phase": session.get("phase"),
            "current_phase": phase,
        }

    active = _load(active_action_path(project_root, run_id=run_id))
    if not isinstance(active, dict) or not active.get("action_id"):
        return {
            "ok": False,
            "error": "STALE_PREPARE_SESSION",
            "message_zh": "active_action 缺失；旧 prepare 已失效，请重新 prepare",
        }
    if str(active.get("action_id")) != action_id:
        return {
            "ok": False,
            "error": "not_active_action",
            "message_zh": (
                f"当前 active_action=`{active.get('action_id')}`，"
                f"不可 finalize `{action_id}`"
            ),
            "active_action": active.get("action_id"),
            "requested_action": action_id,
        }
    if str(active.get("run_id") or "") and str(active.get("run_id")) != run_id:
        return {
            "ok": False,
            "error": "active_action_run_mismatch",
            "message_zh": "active_action.run_id 与当前 run 不一致",
        }
    active_nonce = str(active.get("prepare_nonce") or "").strip()
    if not active_nonce or active_nonce != prepare_nonce:
        return {
            "ok": False,
            "error": "SESSION_NONCE_MISMATCH",
            "message_zh": "active_action.prepare_nonce 与 session 不一致（可能已被新 prepare 覆盖）",
        }
    active_lease = str(active.get("lease_id") or "").strip()
    if not active_lease or active_lease != session_lease:
        return {
            "ok": False,
            "error": "SESSION_LEASE_MISMATCH",
            "message_zh": "active_action.lease_id 与 session 不一致",
        }
    active_sdir = str(active.get("session_dir") or "").strip()
    if active_sdir and Path(active_sdir).resolve() != sdir.resolve():
        return {
            "ok": False,
            "error": "STALE_PREPARE_SESSION",
            "message_zh": "active_action.session_dir 与期望 session 不一致",
        }

    lease = load_lease(project_root, run_id=run_id)
    if not lease:
        return {
            "ok": False,
            "error": "LEASE_REVOKED",
            "message_zh": "当前无有效 lease；请重新 prepare",
        }
    if str(lease.get("status") or "").lower() == "revoked" or is_lease_revoked(
        project_root, session_lease, run_id=run_id
    ):
        return {
            "ok": False,
            "error": "LEASE_REVOKED",
            "message_zh": "lease 已撤销；禁止 finalize",
        }
    if str(lease.get("lease_id") or "") != session_lease:
        return {
            "ok": False,
            "error": "SESSION_LEASE_MISMATCH",
            "message_zh": "当前 active lease 不是本次 prepare 签发的 lease",
        }
    if str(lease.get("action_id") or "") != action_id:
        return {
            "ok": False,
            "error": "LEASE_ACTION_MISMATCH",
            "message_zh": f"lease.action_id={lease.get('action_id')!r} != {action_id!r}",
        }
    if str(lease.get("run_id") or "") != run_id:
        return {
            "ok": False,
            "error": "LEASE_RUN_MISMATCH",
            "message_zh": f"lease.run_id={lease.get('run_id')!r} != {run_id!r}",
        }
    if str(lease.get("workflow_id") or "") != wid:
        return {
            "ok": False,
            "error": "LEASE_WORKFLOW_MISMATCH",
            "message_zh": f"lease.workflow_id={lease.get('workflow_id')!r} != {wid!r}",
        }
    return None




def _engine_audit_findings(*blobs: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Lift engine audit.blocking rows into Observation findings."""
    findings: list[dict[str, Any]] = []
    seen: set[str] = set()
    for blob in blobs:
        if not isinstance(blob, dict):
            continue
        audit = blob.get("audit") if isinstance(blob.get("audit"), dict) else None
        if not isinstance(audit, dict):
            continue
        blocking = audit.get("blocking")
        if not isinstance(blocking, list):
            continue
        for item in blocking:
            if not isinstance(item, dict):
                continue
            code = str(item.get("code") or "ENGINE_AUDIT")
            detail = str(item.get("detail") or item.get("message") or code)
            key = f"{code}:{detail}"
            if key in seen:
                continue
            seen.add(key)
            extra = {k: v for k, v in item.items() if k not in {"code", "detail", "message"}}
            findings.append({"code": code, "message": detail, "evidence": extra})
    return findings


def _attach_finalize_observation(
    project_root: Path,
    payload: dict[str, Any],
    *,
    action_id: str,
    messages: list[str],
    findings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    from ascendc_pilot.observation import record_pilot_result
    from ascendc_pilot.state import load_state, save_state

    eng = payload.get("engine") if isinstance(payload.get("engine"), dict) else {}
    checker = payload.get("checker_result") if isinstance(payload.get("checker_result"), dict) else {}
    eng2 = checker.get("engine") if isinstance(checker.get("engine"), dict) else {}
    finding_rows = list(findings or [])
    if not finding_rows:
        finding_rows = _engine_audit_findings(eng, eng2)

    explicit_class = str(
        payload.get("failure_class")
        or eng.get("failure_class")
        or eng2.get("failure_class")
        or ""
    ).strip() or None
    recorded = record_pilot_result(
        project_root,
        ok=False,
        action_id=action_id,
        step_id="action_finalize",
        error_code=str(
            payload.get("reason_code")
            or payload.get("error")
            or eng.get("reason_code")
            or eng.get("error")
            or eng2.get("reason_code")
            or eng2.get("error")
            or ""
        )
        or None,
        messages=[m for m in messages if m],
        findings=finding_rows or None,
        source="finalize_action",
        explicit_class=explicit_class,
    )
    out = dict(payload)
    out["observation"] = recorded.get("observation")
    out["status"] = recorded.get("status")
    out["last_failure"] = recorded.get("last_failure")
    out["failure_card"] = recorded.get("failure_card")

    # Propagate engine recovery_actions into last_failure for rework authorize.
    from ascendc_pilot.recovery import filter_executable_recovery_actions

    wid = str((load_state(project_root) or {}).get("workflow_id") or "uo-init")
    recovery = filter_executable_recovery_actions(
        list(eng.get("recovery_actions") or eng2.get("recovery_actions") or []),
        workflow_id=wid,
    )
    recoveries = list(eng.get("recoveries") or eng2.get("recoveries") or [])
    if recovery or recoveries:
        lf = dict(out.get("last_failure") or {})
        if recovery:
            lf["recovery_actions"] = recovery
        if recoveries:
            lf["recoveries"] = recoveries
        out["last_failure"] = lf
        st = load_state(project_root)
        if st:
            st_lf = dict(st.get("last_failure") or {})
            if recovery:
                st_lf["recovery_actions"] = recovery
            if recoveries:
                st_lf["recoveries"] = recoveries
            st["last_failure"] = st_lf
            save_state(project_root, st)
    if str(out.get("status") or "") == "human_required":
        from ascendc_pilot.state import describe_next

        nxt = describe_next(project_root)
        if nxt.get("ask_question"):
            out["needs_human_decision"] = True
            out["ask_question"] = nxt["ask_question"]
            out["human_required"] = nxt.get("human_required")
            out["primary_instruction_zh"] = nxt.get("primary_instruction_zh") or (
                "先对本命令的返回做 AskQuestion；选项必须原样使用 ask_question.options。"
                "若用户已打断并在对话里回复，改为 interpret-user-turn，不要重问上一题。"
            )
    return out




def finalize_action(
    project_root: Path,
    action_id: str,
    *,
    engine_result: dict[str, Any] | None = None,
    result_file: Path | str | None = None,
    action_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state = load_state(project_root)
    if not state:
        return {"ok": False, "error": "no_active_workflow"}
    arch = str(state.get("architecture") or "").strip() or None
    ensure_control_layout(project_root, arch=arch)
    wid = str(state.get("workflow_id") or "")
    phase = str(state.get("phase") or "")
    run_id = str(state.get("run_id") or "")
    action = _action_spec(wid, action_id, phase, project_root=project_root)
    if action is None or action.get("_not_in_phase"):
        return {"ok": False, "error": "action_not_allowed", "action_id": action_id, "phase": phase}

    sdir = _session_dir(project_root, run_id, action_id)
    session = _load_action_session(sdir)
    if not session:
        return {
            "ok": False,
            "error": "no_session",
            "message_zh": "缺少 prepare session；请由 Host `pilot_run` 重新准备本步",
        }

    bind_err = _finalize_bind_session_lease(
        project_root,
        session=session,
        action_id=action_id,
        run_id=run_id,
        wid=wid,
        phase=phase,
        sdir=sdir,
    )
    if bind_err is not None:
        from ascendc_pilot.authorize.lease import load_lease

        cur = load_lease(project_root, run_id=run_id)
        session_lease = str(session.get("lease_id") or "").strip()
        if cur and session_lease and str(cur.get("lease_id") or "") == session_lease:
            _revoke_lease_after_finalize(
                project_root,
                reason="finalize_denied",
                touch_active_action=True,
                run_id=run_id,
            )
        return bind_err

    actor_id = str(session.get("actor_id") or action.get("agent_id") or "")
    role_id = str(session.get("role_id") or action.get("role_id") or "")
    output_mode = str(
        session.get("output_mode") or action.get("output_mode") or "direct"
    ).strip().lower()
    if output_mode == "staged":
        contract_id = str(
            session.get("staging_contract_id")
            or action.get("staging_contract_id")
            or session.get("output_contract_id")
            or action.get("output_contract_id")
            or ""
        )
    else:
        contract_id = str(session.get("output_contract_id") or action.get("output_contract_id") or "")
    action_sid = str(session.get("action_session_id") or "")
    lease_id = str(session.get("lease_id") or "")
    prepare_nonce = str(session.get("prepare_nonce") or "")
    captured = _capture_return_value(result_file=result_file, action_result=action_result)
    if captured:
        session["captured_result"] = captured
        try:
            _dump(sdir / "captured.yaml", captured)
        except Exception:  # noqa: BLE001
            pass

    producer_identity = _validate_producer_declared_identity(
        project_root,
        session=session,
        action_id=action_id,
    )
    producer_identity_ok = bool(producer_identity.get("ok"))

    # Stamp run-scoped YAML before the contract check. Missing LLM-copied
    # run_id must not fail the gate; Pilot identity is authoritative.
    identity_injection = {"ok": True, "skipped": True}
    if contract_id == "tg-bind-staging-v1":
        identity_injection = _finalize_restore_bind_parts(
            project_root, session=session, action_id=action_id
        )
    elif producer_identity_ok:
        identity_injection = _finalize_inject_artifact_identity(
            project_root,
            session=session,
            action_id=action_id,
            contract_id=contract_id,
        )

    if not producer_identity_ok:
        contract = {
            "ok": False,
            "skipped": False,
            "error": "PRODUCER_DECLARED_IDENTITY_MISMATCH",
            "producer_identity": producer_identity,
            "message": str(
                producer_identity.get("message")
                or "producer-declared artifact identity conflicts with prepared Action session"
            ),
        }
    elif not identity_injection.get("ok"):
        contract = {
            "ok": False,
            "skipped": False,
            "error": str(identity_injection.get("error") or "IDENTITY_INJECTION_FAILED"),
            "identity_injection": identity_injection,
            "message": str(
                identity_injection.get("message")
                or "finalizer could not stamp artifact identity"
            ),
        }
    else:
        contract = _check_output_contract(
            project_root,
            contract_id,
            run_id=run_id,
            workflow_id=wid,
            phase=phase,
            action_id=action_id,
            actor_id=actor_id,
            role_id=role_id,
            action_session_id=action_sid,
            lease_id=lease_id,
            prepare_nonce=prepare_nonce,
        )

    # apply_result was previously set by the removed semantic-parts reduce path;
    # keep a defined local so every finalize path can report it without NameError.
    apply_result: dict[str, Any] | None = (
        session.get("apply_result") if isinstance(session.get("apply_result"), dict) else None
    )
    target_violation: dict[str, Any] | None = None

    from ascendc_pilot.spec_hashes import workflow_spec_hash

    gate_results = []
    if producer_identity_ok:
        post_ids = list(session.get("post_gates") or action.get("post_gates") or [])
        gate_results = _run_action_gates(project_root, post_ids)

    checker_required = bool(session.get("checker_required", action.get("checker_required", True)))
    gates_ok = all(g.get("ok") for g in gate_results) if gate_results else True
    # Fail-closed: unknown/missing contracts never pass. checker_required=False only
    # skips path nonempty checks when the contract is registered and already validated
    # structurally (unknown still fails above).
    if contract.get("error") in {"missing_contract_id", "unknown_contract"}:
        contract_ok = False
    elif not checker_required:
        contract_ok = contract.get("error") not in {"missing_contract_id", "unknown_contract"}
    else:
        contract_ok = bool(contract.get("ok")) and not contract.get("skipped")

    engine_ok = True if engine_result is None else bool(engine_result.get("ok", True))
    targets_ok = target_violation is None
    overall_ok = bool(
        producer_identity_ok
        and identity_injection.get("ok")
        and gates_ok
        and contract_ok
        and engine_ok
        and targets_ok
    )

    checker_result = {
        "ok": overall_ok,
        "producer_identity": producer_identity,
        "identity_injection": identity_injection,
        "gates": gate_results,
        "output_contract": contract,
        "engine": engine_result or {},
        "apply": apply_result or {},
        "target_violation": target_violation or {},
        "output_mode": output_mode,
    }

    out_hashes = _collect_output_hashes(
        project_root,
        contract_id,
        run_id=run_id,
        workflow_id=wid,
        phase=phase,
        action_id=action_id,
        actor_id=actor_id,
        role_id=role_id,
        action_session_id=action_sid,
        lease_id=lease_id,
        prepare_nonce=prepare_nonce,
    )
    if not out_hashes:
        out_hashes = {"session": file_sha256(_session_overlay_path(sdir)) or "none"}

    in_hashes = {
        "prompt": file_sha256(sdir / "prompt.md") or "",
        "prepare_nonce": str(session.get("prepare_nonce") or ""),
        "lease_id": str(session.get("lease_id") or ""),
    }
    if isinstance(session.get("prepare_stamp"), dict):
        in_hashes["prepare_stamp_nonce"] = str(session["prepare_stamp"].get("nonce") or "")
        in_hashes["inventory_sha256"] = str(session["prepare_stamp"].get("inventory_sha256") or "")

    receipt_path = None
    if overall_ok:
        receipt_path = issue_receipt(
            project_root,
            actor_type=role_id or "producer",
            actor_id=actor_id,
            action_id=action_id,
            workflow_spec_hash=workflow_spec_hash(wid) if wid else workflow_spec_hash(),
            input_hashes=in_hashes,
            output_hashes=out_hashes,
            checker_result=checker_result,
            nonce=str(session.get("prepare_nonce") or session.get("nonce") or ""),
            _internal=True,
        )
        session["status"] = "finalized"
        session["receipt"] = str(receipt_path)
        _dump_session_state(sdir, session)
        _write_active_action(
            project_root,
            {
                "version": 1,
                "run_id": run_id,
                "workflow_id": wid,
                "phase": phase,
                "action_id": action_id,
                # Clear live actor so Host/authorize never remap Primary onto the
                # producer after finalize (blocks acp complete / Primary writes).
                "actor_id": "",
                "last_actor_id": actor_id,
                "role_id": session.get("role_id"),
                "prepare_nonce": str(session.get("prepare_nonce") or ""),
                "lease_id": str(session.get("lease_id") or ""),
                "status": "finalized",
                "receipt": str(receipt_path),
            },
        )
        _revoke_lease_after_finalize(
            project_root,
            reason="finalize_ok",
            touch_active_action=False,
            run_id=run_id,
        )
        append_event(
            project_root,
            {"type": "action_finalized", "action_id": action_id, "actor_id": actor_id, "ok": True},
            run_id=run_id,
        )
    else:
        session["status"] = "finalize_failed"
        session["checker_result"] = checker_result
        _dump_session_state(sdir, session)
        append_event(
            project_root,
            {"type": "action_finalize_failed", "action_id": action_id, "checker": checker_result},
            run_id=run_id,
        )

    result = {
        "ok": overall_ok,
        "phase_runtime": "finalize",
        "action_id": action_id,
        "actor_id": actor_id,
        "run_id": run_id,
        "receipt": str(receipt_path) if receipt_path else None,
        "engine": engine_result or {},
        "checker_result": checker_result,
        "message_zh": (
            "Action 已 finalize 并签发可信收据；下一步必须 `pilot_cli next`（取 recommended_next_action），"
            "禁止跳步；仅 phase 门禁齐备时才由 Host `pilot_run` 推进"
            if overall_ok
            else "Finalize 失败：Checker/Output Contract 未通过"
        ),
    }
    if overall_ok and action_id == "plan_scope":
        result["message_zh"] = (
            "plan_scope 已回答（无文件）。Primary 读回答、弄清要测什么后继续 plan_fuse；"
            "不要写 targets.yaml / plan.md。"
        )
    if not overall_ok and not engine_ok and isinstance(engine_result, dict):
        from ascendc_pilot.actions.failure_text import preferred_failure_text, with_failure_hint

        result["error"] = str(engine_result.get("error") or "ENGINE_FAILED")
        result["message_zh"] = with_failure_hint(
            preferred_failure_text(engine_result, fallback=str(result["message_zh"])),
            engine_result,
        )
    if not overall_ok and not producer_identity_ok:
        result["error"] = "PRODUCER_DECLARED_IDENTITY_MISMATCH"
    elif not overall_ok and not identity_injection.get("ok"):
        result["error"] = str(identity_injection.get("error") or "IDENTITY_INJECTION_FAILED")
    if overall_ok:
        from ascendc_pilot.observation import record_pilot_result

        recorded = record_pilot_result(
            project_root,
            ok=True,
            action_id=action_id,
            step_id="action_finalize",
            source="finalize_action",
        )
        result["observation"] = recorded.get("observation")
        if action_id == "kb_lookup" or wid == "uo-query":
            try:
                import os

                from ascendc_pilot.occupancy import (
                    WORKFLOW_ENV,
                    apply_stale_confidence,
                )
                from ascendc_pilot.state import complete_workflow

                if wid:
                    os.environ[WORKFLOW_ENV] = wid
                live = load_state(project_root, workflow_id=wid) or {}
                result = apply_stale_confidence(
                    result,
                    project_root,
                    architecture=str(live.get("architecture") or ""),
                    pinned_digest=str(live.get("pinned_digest") or ""),
                    session_id=str(live.get("session_id") or ""),
                )
                meta = get_workflow(wid) if wid else {}
                ready = set(meta.get("terminal_ready_states") or [])
                phase = str(live.get("phase") or "")
                if not ready or phase in ready:
                    completed = complete_workflow(project_root)
                    result["complete"] = {
                        "ok": bool(completed.get("ok")),
                        "status": completed.get("status"),
                        "released_execution": completed.get("released_execution"),
                    }
                    if completed.get("ok"):
                        result["message_zh"] = (
                            "查询已 finalize 并释放 ephemeral run；请将答案正文向用户陈述。"
                        )
            except Exception:  # noqa: BLE001
                pass
        return result

    msgs = ["Finalize 失败：Checker/Output Contract 未通过"]
    if not engine_ok and engine_result:
        from ascendc_pilot.actions.failure_text import preferred_failure_text

        eng_msg = preferred_failure_text(engine_result, fallback="")
        if eng_msg:
            msgs = [eng_msg]
    if not producer_identity_ok:
        msgs.append(str(producer_identity.get("error") or "PRODUCER_DECLARED_IDENTITY_MISMATCH"))
    if not identity_injection.get("ok"):
        msgs.append(str(identity_injection.get("error") or "IDENTITY_INJECTION_FAILED"))
    for g in gate_results:
        if not g.get("ok"):
            msgs.append(str(g.get("message") or g.get("gate") or "gate_failed"))
    if not contract_ok:
        msgs.append(str(contract.get("message") or "output_contract_failed"))
    findings = _engine_audit_findings(engine_result, checker_result.get("engine"))
    for row in findings:
        msgs.append(f"{row['code']}: {row['message']}")
    if not engine_ok and engine_result and not findings:
        msgs.append(str(engine_result.get("error") or engine_result.get("message") or "engine_failed"))
    return _attach_finalize_observation(
        project_root,
        result,
        action_id=action_id,
        messages=msgs,
        findings=findings,
    )



def _finalize_owned_artifact_path(
    project_root: Path,
    *,
    session: dict[str, Any],
    action_id: str,
) -> Path | None:
    from ascendc_pilot.paths import uo_root as _uo_root

    run_id = str(session.get("run_id") or "")
    scope_validated = (
        _uo_root(project_root)
        / "runs"
        / run_id
        / "scope"
        / "scope_validated.yaml"
    )
    owned: dict[str, Path] = {
        # prepare owns the machine scope receipt; gate stamp is scope_validated.
        "prepare": scope_validated,
        "scope_validated": scope_validated,
    }
    return owned.get(action_id)


def _validate_producer_declared_identity(
    project_root: Path,
    *,
    session: dict[str, Any],
    action_id: str,
) -> dict[str, Any]:
    """Reject producer-declared identity that conflicts with the prepared session."""
    del project_root, session, action_id
    return {"ok": True, "skipped": True}



def run_action(
    project_root: Path,
    action_id: str,
    *,
    finalize: bool = False,
    result_file: Path | str | None = None,
    action_result: dict[str, Any] | None = None,
    turn_intent: str = "",
) -> dict[str, Any]:
    token = bind_turn_intent(turn_intent)
    try:
        if finalize:
            return finalize_action(
                project_root,
                action_id,
                result_file=result_file,
                action_result=action_result,
            )
        return prepare_action(project_root, action_id, turn_intent=turn_intent)
    finally:
        _TURN_INTENT.reset(token)
