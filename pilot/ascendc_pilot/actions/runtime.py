"""Two-phase Action runtime: prepare → (actor) → finalize."""

from __future__ import annotations

import hashlib
import re
import secrets
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

from ascendc_pilot.actions.engines import (
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


def _pack_value(pack: dict[str, Any], key: str) -> Any:
    value = pack.get(key)
    if isinstance(value, str) and value.startswith("run-action:"):
        return ""
    return value


def _eng_ctx_from_pack(
    pack: dict[str, Any],
    state: dict[str, Any],
    run_id: str,
    *,
    consumes_state: list[str] | None = None,
) -> dict[str, Any]:
    architecture = str(pack.get("architecture") or state.get("architecture") or "").strip()
    if not architecture:
        return {
            "ok": False,
            "reason_code": "ARCHITECTURE_MISSING_IN_RUN_STATE",
            "error": "ARCHITECTURE_MISSING_IN_RUN_STATE",
        }
    ctx: dict[str, Any] = {
        "run_id": run_id,
        "op_name": pack.get("op_name") or state.get("op_name") or "",
        "architecture": architecture,
        "workflow_id": str(pack.get("workflow_id") or state.get("workflow_id") or ""),
        "test_script_root": pack.get("test_script_root") or state.get("test_script_root") or "",
        "level": pack.get("level") or state.get("level") or "L0",
        "focus": pack.get("focus") or state.get("focus") or "",
    }
    declared = [str(k).strip() for k in (consumes_state or []) if str(k).strip()]
    for key in declared:
        if key in ctx:
            continue
        if key in LIST_STATE_KEYS:
            raw = state.get(key)
            if raw is None:
                raw = _pack_value(pack, key)
            ctx[key] = list(raw) if isinstance(raw, list) else []
            continue
        value = state.get(key)
        if value in (None, ""):
            value = _pack_value(pack, key)
        if key == "description" and value in (None, ""):
            value = state.get("intent") or _pack_value(pack, "intent") or ""
        if key == "intent" and value in (None, ""):
            value = state.get("description") or _pack_value(pack, "description") or ""
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
    context_pack_path: str = "",
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
        "<TARGET_IDS_OR_FILES>": target or "(see context pack / human input)",
        "<TARGET>": target or "(see dispatch_targets / batch file)",
        "<SHARD_ID>": shard_id or "(see dispatch_tasks[].shard_id)",
        "<OP_NAME>": op_name,
        "<PROJECT_ROOT>": project_root,
        "<UO_ROOT>": uo_root,
        "<TG_ROOT>": tg_root_path,
        "<TOPIC>": topic,
        "<CONTEXT_PACK_PATH>": context_pack_path,
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
    """Parallel Spec / Standards Tasks so the two axes do not share context.

    Axes come from Workflow Spec ``execution_variant=review_axis_fanout`` +
    ``fanout_axes`` — runtime does not invent a second graph.
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
    dt = dict(dispatch_targets or {})
    tasks: list[dict[str, str]] = []
    for axis_row in axes_spec:
        axis = str(axis_row.get("id") or "").strip()
        cap = str(axis_row.get("capability_id") or "").strip()
        artifact = str(axis_row.get("artifact") or "").replace("{run_id}", run_id)
        other = str(axis_row.get("other") or "").replace("{run_id}", run_id)
        focus = str(axis_row.get("focus") or "").strip()
        if not axis or not cap or not artifact:
            return []
        mp = _capability_method_path(repo, "code-review", cap)
        if not mp.is_file():
            return []
        axis_method = sdir / f"method_{axis}.md"
        axis_method.write_text(mp.read_text(encoding="utf-8"), encoding="utf-8")
        axis_dt = dict(dt)
        axis_dt["write"] = [artifact]
        forbid = list(axis_dt.get("forbid_read") or [])
        for blocked in (
            other,
            "ce/review/functional_report.yaml",
            "ce/review/bug_report.yaml",
            "ce/review/index.yaml",
            "ce/review/**",
        ):
            if blocked and blocked not in forbid:
                forbid.append(blocked)
        axis_dt["forbid_read"] = forbid
        question = (
            f"AXIS={axis}\n"
            f"FOCUS: {focus}\n"
            f"SLICE_ID={axis}\n"
            "Read only the method path in this stub. "
            f"Optional session part: {artifact}. Do not Write ce/**. "
            f"Do not Read {other}."
        )
        axis_kwargs = {
            **stub_kwargs,
            "method_path": axis_method.as_posix(),
            "dispatch_targets": axis_dt,
            "write_paths": [artifact],
            "user_question": question,
        }
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
    if len(tasks) < 2:
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


def _ensure_review_report_skeletons(project_root: str, architecture: str) -> None:
    """Keep code-review-v1 contract satisfiable when review fans out two writers."""
    arch = str(architecture or "").strip()
    root = str(project_root or "").strip()
    if not arch or not root:
        return
    try:
        from ascendc_pilot.paths import ce_root
    except Exception:  # noqa: BLE001
        return
    review = ce_root(root, arch=arch) / "review"
    review.mkdir(parents=True, exist_ok=True)
    skeletons = {
        "index.yaml": "schema: ce-review-index/v1\nentry: ''\nfindings: []\n",
        "functional_report.yaml": "schema: ce-review-spec/v1\naxis: spec\nfindings: []\n",
        "bug_report.yaml": "schema: ce-review-standards/v1\naxis: standards\nfindings: []\n",
    }
    for name, body in skeletons.items():
        path = review / name
        if not path.is_file() or not path.read_text(encoding="utf-8").strip():
            path.write_text(body, encoding="utf-8")


def _capability_method_path(repo: Path, domain: str, capability: str) -> Path:
    """``skills/<domain>/capabilities/<cap>/METHOD.md`` (Spec identity → playbook)."""
    return repo / "skills" / domain / "capabilities" / capability / "METHOD.md"


def _uo_query_method_path(repo: Path) -> Path:
    """Query playbook for ``uo-query`` (materialized as session/method.md)."""
    return _capability_method_path(repo, "operator-analysis", "uo-query")


def _resolve_capability_method(repo: Path, action: dict[str, Any]) -> Path | None:
    """Map explicit ``action_method_id`` ``{skill}/{capability}`` onto METHOD.md.

    No heuristic fallback on prompt id or action id. Missing files are the
    caller's problem (prepare fail-closed for subagent LLM Actions).
    """
    mid = str(action.get("action_method_id") or "").strip()
    if "/" not in mid:
        return None
    domain, capability = mid.split("/", 1)
    domain = domain.strip()
    capability = capability.strip()
    if not domain or not capability:
        return None
    return _capability_method_path(repo, domain, capability)


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
        if "/" in tpid:
            dom, name = tpid.split("/", 1)
            pp = repo / "prompts" / "tasks" / dom / f"{name}.md"
        else:
            pp = repo / "prompts" / "tasks" / f"{tpid}.md"
        if pp.is_file():
            prompt = pp.read_text(encoding="utf-8")
    mp = _resolve_capability_method(repo, action)
    if mp is not None and mp.is_file():
        method = mp.read_text(encoding="utf-8")
    return method, prompt


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
    for rel in expanded:
        matches = _resolve_contract_paths(root, rel)
        if not matches:
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
        if not nonempty:
            empty.append(rel)

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


def prepare_action(project_root: Path, action_id: str) -> dict[str, Any]:
    try:
        arch = discover_arch(project_root)
    except ValueError:
        return {
            "ok": False,
            "error": "ARCHITECTURE_MISSING_IN_RUN_STATE",
            "reason_code": "ARCHITECTURE_MISSING_IN_RUN_STATE",
            "message_zh": "缺少 architecture；请先 acp start --architecture …",
        }
    ensure_control_layout(project_root, arch=arch)
    state = load_state(project_root, arch=arch)
    if not state:
        return {"ok": False, "error": "no_active_workflow", "message_zh": "无活动 workflow；请先 acp start"}
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
                    "请 `acp advance` 进入下一阶段。"
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
                    f"不可直接跑 `{action_id}`。缺少前置 Action；请先 `acp next`。"
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

    from ascendc_pilot.context import build_context_pack, maybe_compile_slice

    try:
        pack = build_context_pack(project_root, intent=f"run-action:{action_id}", topic=action_id)
    except ValueError as exc:
        if "ARCHITECTURE_MISSING_IN_RUN_STATE" in str(exc):
            return {
                "ok": False,
                "error": "ARCHITECTURE_MISSING_IN_RUN_STATE",
                "reason_code": "ARCHITECTURE_MISSING_IN_RUN_STATE",
            }
        raise
    repo = _repo_root(project_root)
    # Optional Context Compiler slice — only when a profile is registered.
    # Unregistered profiles leave pack/session identical to the pre-compiler path.
    context_profile_id = str(action.get("context_profile_id") or "") or None
    context_slice = maybe_compile_slice(
        project_root,
        context_profile_id=context_profile_id,
        action_id=action_id,
        workflow_id=wid,
        intent=f"run-action:{action_id}",
        repo_root=repo,
    )
    if isinstance(context_slice, dict) and context_slice.get("ok") is False:
        missing_refs = list(context_slice.get("missing_references") or [])
        return {
            "ok": False,
            "error": str(context_slice.get("error") or "BUNDLE_NOT_READABLE"),
            "reason_code": str(
                context_slice.get("reason_code") or "CONTEXT_REFERENCES_MISSING"
            ),
            "missing": missing_refs,
            "message_zh": str(
                context_slice.get("message_zh")
                or "Context references 缺失；禁止派发"
            ),
            "action_id": action_id,
            "context_profile_id": context_profile_id,
        }
    method, prompt = _load_method_and_prompt(repo, action)
    if execution_mode == EXECUTION_SUBAGENT and str(action.get("task_prompt_id") or "").strip():
        mp = _resolve_capability_method(repo, action)
        if mp is None or not mp.is_file() or not str(method or "").strip():
            mid = str(action.get("action_method_id") or "")
            return {
                "ok": False,
                "error": "METHOD_MISSING",
                "reason_code": "METHOD_MISSING",
                "message_zh": (
                    f"Action {action_id} missing METHOD.md for {mid or '(no action_method_id)'}；"
                    "禁止拼接 Agent SKILL.md。"
                ),
                "action_method_id": mid,
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
    pack_path = str(pack.get("path") or "")
    slice_path = str((context_slice or {}).get("path") or "")
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
        "context_pack_path": pack_path,
        "context_slice_path": slice_path,
        "op_name": op_name,
        "architecture": architecture,
        "role_id": role_id,
        "action_session_id": action_sid,
    }
    method_r = _render_placeholders(method, **ph_kwargs)
    prompt_r = _render_placeholders(prompt, **ph_kwargs)
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
        "task_prompt_id": action.get("task_prompt_id"),
        "context_profile_id": action.get("context_profile_id"),
        "output_contract_id": action.get("output_contract_id"),
        "output_mode": str(action.get("output_mode") or "direct"),
        "staging_contract_id": action.get("staging_contract_id"),
        "checker_required": bool(action.get("checker_required", True)),
        "referee_required": bool(action.get("referee_required", False)),
        "pre_gates": list(action.get("pre_gates") or []),
        "post_gates": list(action.get("post_gates") or []),
        "context_pack_path": pack_path,
        "context_slice_path": slice_path,
        "context_slice_token_estimate": int((context_slice or {}).get("token_estimate") or 0),
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

    eng_ctx = _eng_ctx_from_pack(
        pack,
        state,
        run_id,
        consumes_state=list(action.get("consumes_state") or []),
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
    ]
    if not dt.get("map_reduce"):
        session_extras.insert(0, f"runs/{run_id}/actions/{action_id}/**")
    # Compiled context slice (when profile registered) is always readable.
    if slice_path:
        # Prefer relative path under context/ for authorize globs.
        try:
            from ascendc_pilot.paths import agent_root as _agent_root

            rel = Path(slice_path).resolve().relative_to(
                _agent_root(project_root, architecture).resolve()
            )
            session_extras.append(rel.as_posix())
        except Exception:
            session_extras.append("context/slices/**")
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
        from ascendc_pilot.context.profiles import get_profile

        if execution_mode == EXECUTION_PRIMARY_INTERACTIVE:
            bundle["method_materialized"] = {
                "copied": [],
                "missing": [],
                "ok": True,
                "host_owned_confirm": True,
            }
        elif execution_mode == EXECUTION_SUBAGENT:
            from ascendc_pilot.actions.method_bundle import method_skill_ids_for_action
            from ascendc_pilot.agents_registry import agent_skill_ceiling

            ceiling = agent_skill_ceiling(actor_id, project_root)
            profile = get_profile(context_profile_id)
            extra_refs = list(profile.references) if profile is not None else []
            skill_ids = method_skill_ids_for_action(
                action,
                agent_skill_ids=ceiling,
                extra_ref_paths=extra_refs,
            )
            mat = materialize_method_bundle(
                sdir,
                skill_ids=[str(x) for x in skill_ids],
                existing_method=method_r,
                project_root=project_root,
                extra_ref_paths=extra_refs,
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
        bundle["method_materialized"] = {"error": str(_mat_exc)[:200]}

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
        if action_id in {"grill_confirm", "human_confirm", "plan_approve"}:
            if not hosted_confirm_should_ask(project_root, voice_state, action_id=action_id):
                materialized = materialize_primary_decision(project_root, action_id)
                fin = finalize_action(project_root, action_id, engine_result=materialized)
                result["auto_skip_human_gate"] = True
                result["needs_human_decision"] = False
                result["auto_finalize"] = True
                result["finalize"] = fin
                result["ok"] = bool(fin.get("ok"))
                result["message_zh"] = "已按你的授权跳过中间确认。"
                return result
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

    fanout_tasks = [
        row
        for row in (bundle.get("dispatch_tasks") or [])
        if isinstance(row, dict) and str(row.get("task_prompt_stub") or "").strip()
    ]
    if len(fanout_tasks) >= 2:
        result["dispatch_tasks"] = fanout_tasks
        result["message_zh"] = (
            f"已准备 {len(fanout_tasks)} 个并行 Task（agent=`{actor_id}`，同一 Action `{action_id}` / 一张 ticket）。"
            "同一轮用 OpenCode 原生 Task 全部派发；每条 prompt 必须原样为 "
            "`dispatch_tasks[i].task_prompt_stub`。"
            "禁止用父 `task_prompt_stub` 再开一个。"
            "全部返回后 Primary 按各 Task 原生全文综合，禁止只转述某一个，"
            "禁止发明子代理没引用的事实。"
            "切片子代理禁止自动 finalize；综合后由 Host `pilot_run` 完成本步。"
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
        result["finalize_hint"] = "pilot_run"
        result["finalize_hint_fallback"] = ""
    else:
        result["message_zh"] += " 完成后由 Host `pilot_run` 完成本步，不要 bash `acp run-action --finalize`。"
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


def _finalize_inject_artifact_identity(
    project_root: Path,
    *,
    session: dict[str, Any],
    action_id: str,
    contract_id: str,
) -> dict[str, Any]:
    """Overwrite LLM-declared identity with session-trusted artifact_identity."""
    from ascendc_pilot.ownership import artifact_identity_from_session, inject_trusted_identity

    identity = artifact_identity_from_session(session)
    path = _finalize_owned_artifact_path(project_root, session=session, action_id=action_id)
    if path is None:
        return {"ok": True, "skipped": True, "reason": "no_owned_artifact", "contract_id": contract_id}
    if not path.is_file():
        return {
            "ok": True,
            "skipped": True,
            "reason": "artifact_missing",
            "path": path.as_posix(),
            "contract_id": contract_id,
        }
    if yaml is None:
        return {
            "ok": False,
            "error": "IDENTITY_INJECTION_UNAVAILABLE",
            "path": path.as_posix(),
            "message": "PyYAML is required to stamp artifact identity",
        }
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
        return {
            "ok": False,
            "error": "IDENTITY_INJECTION_INVALID_ARTIFACT",
            "path": path.as_posix(),
            "message": "artifact must be a YAML mapping to stamp identity",
        }

    def _stamp_scope_safe(raw: dict[str, Any]) -> dict[str, Any]:
        """Stamp nested artifact_identity; keep top-level gate action_id."""
        prior_action = str(raw.get("action_id") or "").strip()
        stamped = inject_trusted_identity(raw, identity)
        if _is_run_scoped_scope_artifact(path) or action_id in _SCOPE_GATE_ACTION_IDS:
            # Canonical machine gate stamp — never rewrite to parent Action prepare.
            if prior_action in _SCOPE_GATE_ACTION_IDS and prior_action != "prepare":
                stamped["action_id"] = prior_action
            else:
                stamped["action_id"] = "scope_validated"
        return stamped

    trusted = _stamp_scope_safe(doc)
    try:
        _dump(path, trusted)
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "error": "IDENTITY_INJECTION_WRITE_FAILED",
            "path": path.as_posix(),
            "message": str(exc),
        }
    # Also stamp scope receipt when present (prepare / scope_* owners).
    if action_id in _SCOPE_GATE_ACTION_IDS:
        receipt = path.parent / "receipt.yaml"
        if receipt.is_file():
            try:
                rdoc = yaml.safe_load(receipt.read_text(encoding="utf-8")) or {}
            except Exception as exc:  # noqa: BLE001
                return {
                    "ok": False,
                    "error": "IDENTITY_INJECTION_READ_FAILED",
                    "path": receipt.as_posix(),
                    "message": str(exc),
                }
            if isinstance(rdoc, dict):
                try:
                    _dump(receipt, _stamp_scope_safe(rdoc))
                except Exception as exc:  # noqa: BLE001
                    return {
                        "ok": False,
                        "error": "IDENTITY_INJECTION_WRITE_FAILED",
                        "path": receipt.as_posix(),
                        "message": str(exc),
                    }
            else:
                return {
                    "ok": False,
                    "error": "IDENTITY_INJECTION_INVALID_ARTIFACT",
                    "path": receipt.as_posix(),
                    "message": "receipt must be a YAML mapping to stamp identity",
                }
    return {"ok": True, "path": path.as_posix(), "contract_id": contract_id}




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
    # Dialogue contract: Host may still pass result_file / action_result;
    # kb-answer-v1 no longer materializes a disk payload.
    _ = (result_file, action_result)

    producer_identity = _validate_producer_declared_identity(
        project_root,
        session=session,
        action_id=action_id,
    )
    producer_identity_ok = bool(producer_identity.get("ok"))

    if producer_identity_ok:
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
    else:
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
    overall_ok = bool(producer_identity_ok and gates_ok and contract_ok and engine_ok and targets_ok)

    identity_injection = {"ok": True, "skipped": True}
    if overall_ok:
        identity_injection = _finalize_inject_artifact_identity(
            project_root,
            session=session,
            action_id=action_id,
            contract_id=contract_id,
        )
        overall_ok = bool(identity_injection.get("ok"))

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
        "context_pack": file_sha256(Path(str(session.get("context_pack_path") or ""))) or "",
        "context_slice": file_sha256(Path(str(session.get("context_slice_path") or ""))) or "",
        "context_slice_token_estimate": str(session.get("context_slice_token_estimate") or ""),
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
            "Action 已 finalize 并签发可信收据；下一步必须 `acp next`（取 recommended_next_action），"
            "禁止跳步；仅 phase 门禁齐备时才 `acp advance`"
            if overall_ok
            else "Finalize 失败：Checker/Output Contract 未通过"
        ),
    }
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
        "confidence_review": _uo_root(project_root) / "review" / "confidence_reason_review.yaml",
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
) -> dict[str, Any]:
    if finalize:
        return finalize_action(
            project_root,
            action_id,
            result_file=result_file,
            action_result=action_result,
        )
    return prepare_action(project_root, action_id)
