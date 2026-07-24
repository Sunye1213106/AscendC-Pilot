"""Two-phase Action runtime: prepare → (actor) → finalize."""

from __future__ import annotations

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
from ascendc_pilot.paths import agent_root, ensure_agent_layout, runs_root, tg_root
from ascendc_pilot.runs import append_event, file_sha256, issue_receipt, run_dir
from ascendc_pilot.state import load_state
from ascendc_pilot.workflows import actions_for_phase, get_workflow

# Mirrors uo.scripts.extract_plan_io.FORBIDDEN_EXTRACT_PLAN_KEYS — keep in sync.
_EXTRACT_PLAN_FORBID_FIELDS = (
    "call_edge_adjudications",
    "llm_tasks",
    "tasks",
    "edge_patches",
    "semantic_patches",
    "dispatches_to",
    "mark_missing",
    "accepted_edges",
    "entrypoint_dispatch_bind",
    "accepted_candidate_ids",
    "blocking_reasons",
)


def _write_active_action(project_root: Path, payload: dict[str, Any]) -> Path:
    """Persist current action context for OpenCode plugin / subagent writes."""
    path = agent_root(project_root) / "state" / "active_action.yaml"
    _dump(path, payload)
    return path


def _eng_ctx_from_pack(pack: dict[str, Any], state: dict[str, Any], run_id: str) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "op_name": pack.get("op_name") or state.get("op_name") or "",
        "architecture": pack.get("architecture") or state.get("architecture") or "arch35",
        "test_script_root": pack.get("test_script_root") or state.get("test_script_root") or "",
        "csv_consumer_root": pack.get("csv_consumer_root")
        or state.get("csv_consumer_root")
        or pack.get("test_script_root")
        or state.get("test_script_root")
        or "",
        "level": pack.get("level") or state.get("level") or "L0",
        "focus": pack.get("focus") or state.get("focus") or "",
    }


def _stamp_semantic_bind_prepare(
    project_root: Path,
    *,
    nonce: str,
    run_id: str,
    action_id: str,
    prepare_result: dict[str, Any],
) -> dict[str, Any]:
    """Annotate inventory with session nonce so finalize can reject stale leftovers."""
    inv_path = tg_root(project_root) / "realization" / "binding_inventory.yaml"
    inv = _load(inv_path)
    stamp = {
        "nonce": nonce,
        "prepare_nonce": nonce,
        "prepare_run_id": run_id,
        "prepare_action_id": action_id,
        "inventory_sha256": file_sha256(inv_path) or "",
        "consumer_fingerprint": inv.get("consumer_fingerprint") if isinstance(inv, dict) else "",
        "engine_ok": bool(prepare_result.get("ok")),
    }
    if isinstance(inv, dict):
        inv["pilot_prepare"] = {
            "nonce": nonce,
            "run_id": run_id,
            "action_id": action_id,
        }
        _dump(inv_path, inv)
        stamp["inventory_sha256"] = file_sha256(inv_path) or ""
    return stamp


def _apply_semantic_bind_on_finalize(
    project_root: Path,
    *,
    session: dict[str, Any],
) -> dict[str, Any]:
    """Deterministically apply producer patch; reject empty/stale progress."""
    tg = tg_root(project_root)
    realization = tg / "realization"
    patch_path = realization / "semantic_bind_patch.yaml"
    unresolved = _load(realization / "unresolved.yaml")
    gaps_doc = _load(realization / "binding_gaps.yaml")
    gaps: list[Any] = []
    status = ""
    if isinstance(unresolved, dict):
        status = str(unresolved.get("status") or "").lower()
        gaps = list(unresolved.get("binding_gaps") or [])
    if isinstance(gaps_doc, dict) and gaps_doc.get("gaps") is not None:
        gaps = list(gaps_doc.get("gaps") or gaps)
        status = str(gaps_doc.get("status") or status).lower()

    inv = _load(realization / "binding_inventory.yaml")
    prepare = session.get("prepare_stamp") or {}
    if isinstance(inv, dict):
        hp = inv.get("pilot_prepare") or {}
        if prepare.get("nonce") and hp.get("nonce") and str(hp.get("nonce")) != str(prepare.get("nonce")):
            return {
                "ok": False,
                "error": "STALE_INVENTORY",
                "message": "binding_inventory prepare nonce mismatch; re-run prepare",
            }

    # No gaps and already ready → allow finalize without patch (deterministic skip).
    if not gaps and status in {"ready", "pass", "resolved", "ok", ""}:
        receipt = {
            "version": 1,
            "status": "skipped_no_gaps",
            "ok": True,
            "prepare_nonce": prepare.get("nonce"),
            "action_id": session.get("action_id"),
            "run_id": session.get("run_id"),
            "inventory_sha256": prepare.get("inventory_sha256") or file_sha256(realization / "binding_inventory.yaml"),
        }
        _dump(realization / "semantic_bind_apply.yaml", receipt)
        return {"ok": True, "applied": False, "skipped": True, "receipt": receipt}

    if not patch_path.is_file() or patch_path.stat().st_size == 0:
        return {
            "ok": False,
            "error": "PATCH_REQUIRED",
            "message": "semantic_bind_patch.yaml missing/empty while binding gaps remain",
            "remaining_gaps": len(gaps),
        }

    patch_doc = _load(patch_path)
    expected_nonce = str(prepare.get("nonce") or session.get("nonce") or "")
    patch_nonce = str(patch_doc.get("prepare_nonce") or "") if isinstance(patch_doc, dict) else ""
    # Require prepare_nonce match when gaps remain — defeats leftover patches from prior runs.
    if expected_nonce and patch_nonce != expected_nonce:
        return {
            "ok": False,
            "error": "STALE_PATCH",
            "message": "semantic_bind_patch.yaml prepare_nonce mismatch or missing (stale leftover)",
            "expected_nonce": expected_nonce[:12],
            "patch_nonce": patch_nonce[:12] if patch_nonce else "",
        }

    # Secondary mtime guard
    session_path = _session_dir(
        project_root,
        str(session.get("run_id") or ""),
        str(session.get("action_id") or ""),
    ) / "session.yaml"
    if session_path.is_file() and patch_path.stat().st_mtime < session_path.stat().st_mtime - 0.5:
        return {
            "ok": False,
            "error": "STALE_PATCH",
            "message": "semantic_bind_patch.yaml appears older than prepare session (stale leftover)",
        }

    try:
        from testcase_agent.semantic_bind import apply_semantic_bind_patch

        applied = apply_semantic_bind_patch(tg)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": "APPLY_FAILED", "message": str(exc)[:400]}

    receipt = {
        "version": 1,
        "status": "applied",
        "ok": bool(applied.get("ok")),
        "prepare_nonce": prepare.get("nonce"),
        "action_id": session.get("action_id"),
        "run_id": session.get("run_id"),
        "inventory_sha256": prepare.get("inventory_sha256"),
        "consumer_fingerprint": prepare.get("consumer_fingerprint"),
        "apply_result": {
            "applied_count": applied.get("applied_count"),
            "rejected_count": applied.get("rejected_count"),
            "remaining_gaps": applied.get("remaining_gaps"),
            "status": applied.get("status"),
        },
        "patch_sha256": file_sha256(patch_path) or "",
    }
    _dump(realization / "semantic_bind_apply.yaml", receipt)
    return {"ok": bool(applied.get("ok")), "applied": True, "result": applied, "receipt": receipt}


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


def _repo_root(project_root: Path) -> Path:
    root = Path(project_root).resolve()
    if (root / "skills").is_dir():
        return root
    here = Path(__file__).resolve().parents[3]
    if (here / "skills").is_dir():
        return here
    return root


def _action_spec(workflow_id: str, action_id: str, phase: str) -> dict[str, Any] | None:
    allowed = actions_for_phase(workflow_id, phase)
    for row in allowed:
        if str(row.get("id") or "") == action_id:
            return row
    # Also allow lookup in full workflow for clearer error messages
    meta = get_workflow(workflow_id)
    for row in meta.get("actions") or []:
        if str(row.get("id") or "") == action_id:
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


def _key_open_ids(project_root: Path) -> list[str]:
    """Open KEY ids from gaps / escalate_keys (deterministic target set for triage)."""
    from ascendc_pilot.paths import uo_root as _uo_root

    uo = _uo_root(project_root)
    ids: list[str] = []
    gaps = _load_yaml_file(uo / "ir" / "input_derivable_gaps.yaml")
    items = gaps.get("gaps") or gaps.get("items") or gaps.get("open") or []
    if isinstance(items, list):
        for it in items:
            if isinstance(it, dict):
                kid = str(it.get("id") or it.get("key") or "")
                status = str(it.get("status") or it.get("state") or "open").lower()
                if kid and status in {"", "open", "unsolved", "escalate"}:
                    ids.append(kid)
            elif isinstance(it, str) and it.strip():
                ids.append(it.strip())
    unresolved = _load_yaml_file(uo / "ir" / "unresolved.yaml")
    raw = unresolved.get("escalate_keys") or []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, str) and item.strip():
                ids.append(item.strip())
            elif isinstance(item, dict):
                kid = str(item.get("id") or item.get("key") or "").strip()
                if kid:
                    ids.append(kid)
    # stable unique
    seen: set[str] = set()
    out: list[str] = []
    for k in ids:
        if k not in seen:
            seen.add(k)
            out.append(k)
    return out


def _key_triage_target_ids(project_root: Path) -> list[str]:
    """Targets assigned by triage for resolution (batches/keys)."""
    from ascendc_pilot.paths import uo_root as _uo_root

    triage = _load_yaml_file(_uo_root(project_root) / "ir" / "key_triage.yaml")
    if str(triage.get("status") or "").lower() in {"not_applicable", "na", "n/a"}:
        return []
    ids: list[str] = []
    keys = triage.get("keys") or triage.get("items") or []
    if isinstance(keys, list):
        for it in keys:
            if isinstance(it, dict):
                kid = str(it.get("id") or it.get("key") or "").strip()
                if kid:
                    ids.append(kid)
            elif isinstance(it, str) and it.strip():
                ids.append(it.strip())
    batches = triage.get("batches") or []
    if isinstance(batches, list):
        for batch in batches:
            if not isinstance(batch, dict):
                continue
            for kid in batch.get("key_ids") or batch.get("keys") or []:
                s = str(kid).strip() if not isinstance(kid, dict) else str(kid.get("id") or "").strip()
                if s:
                    ids.append(s)
    seen: set[str] = set()
    out: list[str] = []
    for k in ids:
        if k not in seen:
            seen.add(k)
            out.append(k)
    return out


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
) -> str:
    repl = {
        "<RUN_ID>": run_id,
        "<ACTION_ID>": action_id,
        "<WORKFLOW_ID>": workflow_id,
        "<ACTOR_ID>": actor_id,
        "<TARGET_IDS_OR_FILES>": target or "(see context pack / human input)",
        "<OP_NAME>": op_name,
        "<PROJECT_ROOT>": project_root,
        "<UO_ROOT>": uo_root,
        "<TG_ROOT>": tg_root_path,
        "<TOPIC>": topic,
        "<CONTEXT_PACK_PATH>": context_pack_path,
        "<ARCHITECTURE>": architecture or "arch35",
        "<ROLE_ID>": role_id,
        "<LEASE_ID>": lease_id,
        "<ACTION_SESSION_ID>": action_session_id,
    }
    out = text
    for k, v in repl.items():
        out = out.replace(k, v)
    # Angle-bracket leftovers that look like template tokens → mark unresolved
    out = re.sub(r"<([A-Z][A-Z0-9_]{2,})>", r"[UNRESOLVED:\1]", out)
    return out


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
) -> str:
    """Minimal Host→subagent Task body: pointers only, no METHOD paraphrase."""
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
    dt = dispatch_targets or {}
    if dt.get("read"):
        lines.append("read: " + ", ".join(str(x) for x in dt["read"]))
    if dt.get("write"):
        lines.append("write: " + ", ".join(str(x) for x in dt["write"]))
    if dt.get("forbid_read"):
        lines.append("forbid_read: " + ", ".join(str(x) for x in dt["forbid_read"]))
    lines.extend(
        [
            "Return a short summary when done.",
            "Do NOT finalize; primary runs `acp run-action "
            + action_id
            + " --finalize`.",
        ]
    )
    return "\n".join(lines) + "\n"


def _load_method_and_prompt(repo: Path, action: dict[str, Any]) -> tuple[str, str]:
    method = ""
    prompt = ""
    mid = str(action.get("action_method_id") or "")
    if mid and "/" in mid:
        wf, name = mid.split("/", 1)
        mp = repo / "skills" / "actions" / wf / name / "METHOD.md"
        if mp.is_file():
            method = mp.read_text(encoding="utf-8")
    tpid = str(action.get("task_prompt_id") or "")
    if tpid:
        if "/" in tpid:
            dom, name = tpid.split("/", 1)
            pp = repo / "prompts" / "tasks" / dom / f"{name}.md"
        else:
            pp = repo / "prompts" / "tasks" / f"{tpid}.md"
        if pp.is_file():
            prompt = pp.read_text(encoding="utf-8")
    return method, prompt


def _resolve_contract_paths(root: Path, rel: str) -> list[Path]:
    """Resolve exact or glob contract paths under agent root."""
    if any(ch in rel for ch in "*?["):
        return sorted(p for p in root.glob(rel) if p.exists())
    path = root / rel
    return [path] if path.exists() else []


def _contract_identity_ok(
    path: Path,
    *,
    run_id: str,
    workflow_id: str,
    action_id: str,
    actor_id: str,
) -> dict[str, Any]:
    """Validate optional artifact identity against the current Action session."""
    if yaml is None or not path.is_file() or path.suffix.lower() not in {".yaml", ".yml"}:
        return {"ok": True, "skipped": True}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        return {"ok": True, "skipped": True}
    if not isinstance(data, dict):
        return {"ok": True, "skipped": True}
    identity = data.get("artifact_identity") if isinstance(data.get("artifact_identity"), dict) else {}
    # Prefer nested identity; fall back to top-level mirrors.
    checks = {
        "run_id": str(identity.get("run_id") or data.get("run_id") or "").strip(),
        "workflow_id": str(identity.get("workflow_id") or data.get("workflow_id") or "").strip(),
        "action_id": str(identity.get("action_id") or data.get("action_id") or "").strip(),
        "actor_id": str(identity.get("actor_id") or data.get("actor_id") or "").strip(),
    }
    # Missing identity on older artifacts is a migration error for run-scoped contracts.
    if any(ch in path.as_posix() for ch in ("/runs/", "scope_confirmed", "receipt.yaml")):
        if not checks["run_id"]:
            return {
                "ok": False,
                "error": "ARTIFACT_IDENTITY_MISSING",
                "path": path.as_posix(),
                "message": "run-scoped artifact missing identity; re-prepare / re-finalize",
            }
        if run_id and checks["run_id"] != run_id:
            return {
                "ok": False,
                "error": "ACTION_RUN_MISMATCH",
                "path": path.as_posix(),
                "expected": run_id,
                "actual": checks["run_id"],
            }
    if run_id and checks["run_id"] and checks["run_id"] != run_id:
        return {
            "ok": False,
            "error": "ACTION_RUN_MISMATCH",
            "path": path.as_posix(),
            "expected": run_id,
            "actual": checks["run_id"],
        }
    if workflow_id and checks["workflow_id"] and checks["workflow_id"] != workflow_id:
        return {
            "ok": False,
            "error": "ACTION_OWNER_MISMATCH",
            "field": "workflow_id",
            "path": path.as_posix(),
            "expected": workflow_id,
            "actual": checks["workflow_id"],
        }
    if action_id and checks["action_id"] and checks["action_id"] != action_id:
        # Canonical IR may be shared across actions; only enforce when present and conflicting
        # for action-owned producer artifacts.
        owned = any(
            name in path.name
            for name in (
                "extract_plan.yaml",
                "semantic_patches.yaml",
                "key_triage.yaml",
                "input_derivable_patch.yaml",
                "scope_confirmed.yaml",
                "receipt.yaml",
            )
        )
        if owned:
            return {
                "ok": False,
                "error": "ACTION_OWNER_MISMATCH",
                "field": "action_id",
                "path": path.as_posix(),
                "expected": action_id,
                "actual": checks["action_id"],
            }
    if actor_id and checks["actor_id"] and checks["actor_id"] != actor_id:
        owned = any(
            name in path.name
            for name in (
                "extract_plan.yaml",
                "semantic_patches.yaml",
                "key_triage.yaml",
                "input_derivable_patch.yaml",
            )
        )
        if owned:
            return {
                "ok": False,
                "error": "ACTION_OWNER_MISMATCH",
                "field": "actor_id",
                "path": path.as_posix(),
                "expected": actor_id,
                "actual": checks["actor_id"],
            }
    return {"ok": True}


def _collect_output_hashes(
    project_root: Path,
    contract_id: str,
    *,
    run_id: str = "",
    workflow_id: str = "",
    action_id: str = "",
    actor_id: str = "",
    action_session_id: str = "",
) -> dict[str, str]:
    from ascendc_pilot.ownership import expand_contract_paths

    root = agent_root(project_root)
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


def _check_output_contract(
    project_root: Path,
    contract_id: str,
    *,
    run_id: str = "",
    workflow_id: str = "",
    action_id: str = "",
    actor_id: str = "",
    action_session_id: str = "",
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
    root = agent_root(project_root)
    paths = OUTPUT_CONTRACT_PATHS.get(contract_id)
    if paths is None:
        return {
            "ok": False,
            "skipped": False,
            "error": "unknown_contract",
            "message": f"unregistered output contract {contract_id!r}; finalize denied",
        }
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
                    action_id=action_id,
                    actor_id=actor_id,
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
    ensure_agent_layout(project_root)
    state = load_state(project_root)
    if not state:
        return {"ok": False, "error": "no_active_workflow", "message_zh": "无活动 workflow；请先 acp start"}
    wid = str(state.get("workflow_id") or "")
    phase = str(state.get("phase") or "")
    run_id = str(state.get("run_id") or "")
    action = _action_spec(wid, action_id, phase)
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
            "allowed": [a.get("id") for a in actions_for_phase(wid, phase)],
        }

    # Prefer pipeline order: block Host skip (e.g. apply before detect_score_post / adjudicate).
    status = str(state.get("status") or "running")
    if status == "running":
        from ascendc_pilot.workflows.pipeline import recommend_next_action

        recommended = recommend_next_action(
            project_root,
            workflow_id=wid,
            phase=phase,
            allowed_actions=actions_for_phase(wid, phase),
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
        # Default recovery: producer that feeds apply_semantic_patch
        if failed == "apply_semantic_patch" and "adjudicate_llm_tasks" not in recovery:
            recovery = ["adjudicate_llm_tasks", "apply_semantic_patch"]
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
    prepare_nonce = secrets.token_hex(16)
    nonce = prepare_nonce  # mirror for legacy readers; finalize requires prepare_nonce
    action_sid = make_action_session_id(run_id, action_id, prepare_nonce)
    sdir = _session_dir(project_root, run_id, action_id)
    sdir.mkdir(parents=True, exist_ok=True)
    staging_dir(sdir).mkdir(parents=True, exist_ok=True)

    from ascendc_pilot.context import build_context_pack
    from ascendc_pilot.paths import tg_root, uo_root

    pack = build_context_pack(project_root, intent=f"run-action:{action_id}", topic=action_id)
    repo = _repo_root(project_root)
    method, prompt = _load_method_and_prompt(repo, action)
    if execution_mode in {EXECUTION_SUBAGENT, EXECUTION_PRIMARY_INTERACTIVE}:
        mid = str(action.get("action_method_id") or "")
        tpid = str(action.get("task_prompt_id") or "")
        if mid and not str(method or "").strip():
            return {
                "ok": False,
                "error": "ACTION_METHOD_MISSING",
                "message_zh": f"Action {action_id} missing METHOD.md for {mid}",
                "action_method_id": mid,
            }
        if tpid and not str(prompt or "").strip():
            return {
                "ok": False,
                "error": "TASK_PROMPT_MISSING",
                "message_zh": f"Action {action_id} missing task prompt {tpid}",
                "task_prompt_id": tpid,
            }
    root_s = Path(project_root).expanduser().resolve().as_posix()
    uo_s = uo_root(project_root).as_posix()
    tg_s = tg_root(project_root).as_posix()
    pack_path = str(pack.get("path") or "")
    op_name = str(state.get("op_name") or Path(project_root).name or "")
    architecture = str(state.get("architecture") or "arch35")
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
        "op_name": op_name,
        "architecture": architecture,
        "role_id": role_id,
        "action_session_id": action_sid,
    }
    method_r = _render_placeholders(method, **ph_kwargs)
    prompt_r = _render_placeholders(prompt, **ph_kwargs)

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
        "checker_required": bool(action.get("checker_required", True)),
        "referee_required": bool(action.get("referee_required", False)),
        "gates": list(action.get("gates") or []),
        "context_pack_path": pack_path,
        "project_root": root_s,
        "uo_root": uo_s,
        "tg_root": tg_s,
        "op_name": op_name,
        "architecture": architecture,
        "status": "prepared",
        "identity_note": (
            "Bundle identity is authoritative. "
            "Do not replace, infer, normalize, or copy identity from old artifacts."
        ),
    }

    eng_ctx = _eng_ctx_from_pack(pack, state, run_id)
    prepare_engine: dict[str, Any] | None = None
    # Producer semantic_bind: deterministic materials must exist before LLM dispatch.
    if wid == "tg-init" and action_id == "semantic_bind" and role_id == "producer":
        prepare_engine = invoke_engine(project_root, wid, action_id, ctx=eng_ctx)
        if not prepare_engine.get("ok"):
            return {
                "ok": False,
                "error": "SEMANTIC_BIND_PREPARE_FAILED",
                "engine": prepare_engine,
                "message_zh": str(prepare_engine.get("error") or "semantic_bind prepare failed"),
            }
        stamp = _stamp_semantic_bind_prepare(
            project_root,
            nonce=nonce,
            run_id=run_id,
            action_id=action_id,
            prepare_result=prepare_engine,
        )
        bundle["prepare_stamp"] = stamp
        bundle["prepare_engine"] = {
            "ok": True,
            "inventory_path": prepare_engine.get("inventory_path"),
            "csv_consumer_root": prepare_engine.get("csv_consumer_root"),
        }
    # extract_plan: propose candidates before LLM confirms the plan.
    if wid == "uo-init" and action_id == "extract_plan" and role_id == "producer":
        prep_ctx = dict(eng_ctx)
        prep_ctx["extract_plan_mode"] = "propose"
        prepare_engine = invoke_engine(project_root, wid, action_id, ctx=prep_ctx)
        if not prepare_engine.get("ok"):
            return {
                "ok": False,
                "error": "EXTRACT_PLAN_PREPARE_FAILED",
                "engine": prepare_engine,
                "message_zh": str(prepare_engine.get("error") or "extract_plan propose failed"),
            }
        bundle["prepare_engine"] = {
            "ok": True,
            "phase": prepare_engine.get("phase"),
            "candidates_path": prepare_engine.get("candidates_path"),
        }
        cand_path = str(prepare_engine.get("candidates_path") or "uo/ir/extract_plan_candidates.yaml")
        target_line = (
            f"{cand_path} → confirm writers/receivers/aliases only; "
            "DO NOT read or adjudicate ir/llm_tasks.yaml"
        )
        prompt_r = _render_placeholders(prompt, **{**ph_kwargs, "target": target_line})
        bundle["dispatch_targets"] = {
            "read": ["uo/ir/extract_plan_candidates.yaml"],
            "write": ["uo/ir/extract_plan.yaml"],
            "forbid_read": ["uo/ir/llm_tasks.yaml"],
            "forbid_write_fields": list(_EXTRACT_PLAN_FORBID_FIELDS),
        }

    # adjudicate_llm_tasks: producer writes patches for deterministic apply.
    if wid == "uo-init" and action_id == "adjudicate_llm_tasks" and role_id == "producer":
        target_line = (
            "uo/ir/llm_tasks.yaml (open+blocking only) → write uo/ir/semantic_patches.yaml; "
            "DO NOT write ledger or derived graphs"
        )
        prompt_r = _render_placeholders(prompt, **{**ph_kwargs, "target": target_line})
        bundle["dispatch_targets"] = {
            "read": ["uo/ir/llm_tasks.yaml", "uo/ir/score_report_post.yaml", "uo/ir/score_report_pre.yaml"],
            "write": ["uo/ir/semantic_patches.yaml"],
            "forbid_write": [
                "uo/ir/semantic_resolution_ledger.yaml",
                "uo/ir/extract_plan.yaml",
                "uo/ir/entrypoint_graph.yaml",
                "uo/ir/host_subgraph.yaml",
                "uo/ir/kernel_subgraph.yaml",
            ],
        }

    # KEY triage: explicit finite target set from gaps / escalate_keys.
    if action_id == "key_triage" and role_id == "producer":
        key_ids = _key_open_ids(project_root)
        if not key_ids:
            target_line = (
                "NO open KEY targets — write uo/ir/key_triage.yaml with status=not_applicable; "
                "DO NOT write input_derivable_patch.yaml"
            )
            bundle["dispatch_targets"] = {
                "target_ids": [],
                "not_applicable": True,
                "write": ["uo/ir/key_triage.yaml"],
                "forbid_write": ["uo/ir/input_derivable_patch.yaml", "uo/ir/key_shape_resolve/**"],
            }
            # Explicit N/A proof for resume/pipeline.
            na_path = sdir / "not_applicable.yaml"
            _dump(
                na_path,
                {
                    "status": "not_applicable",
                    "action_id": "key_triage",
                    "run_id": run_id,
                    "reason": "no_open_key_targets",
                },
            )
        else:
            target_line = (
                "KEY ids (triage only): " + ", ".join(key_ids) + " → write uo/ir/key_triage.yaml only; "
                "DO NOT write input_derivable_patch.yaml or close gaps"
            )
            bundle["dispatch_targets"] = {
                "target_ids": key_ids,
                "write": ["uo/ir/key_triage.yaml"],
                "forbid_write": ["uo/ir/input_derivable_patch.yaml", "uo/ir/key_shape_resolve/**"],
            }
        prompt_r = _render_placeholders(prompt, **{**ph_kwargs, "target": target_line})

    # KEY resolution: only triage-assigned targets.
    if action_id == "key_resolution" and role_id == "producer":
        assigned = _key_triage_target_ids(project_root)
        open_ids = _key_open_ids(project_root)
        if not open_ids and not assigned:
            target_line = (
                "NO KEY resolution targets — write input_derivable_patch.yaml with status=not_applicable "
                "OR empty patches list; DO NOT invent keys"
            )
            bundle["dispatch_targets"] = {
                "target_ids": [],
                "not_applicable": True,
                "write": ["uo/ir/input_derivable_patch.yaml"],
                "forbid_write": ["uo/ir/key_triage.yaml"],
            }
            _dump(
                sdir / "not_applicable.yaml",
                {
                    "status": "not_applicable",
                    "action_id": "key_resolution",
                    "run_id": run_id,
                    "reason": "no_key_resolution_targets",
                },
            )
        else:
            # Prefer triage assignment; never expand beyond open set.
            allowed = assigned if assigned else open_ids
            if open_ids:
                allowed = [k for k in allowed if k in set(open_ids)] or allowed
            target_line = (
                "KEY ids (resolution only; do not expand): "
                + ", ".join(allowed)
                + " → write uo/ir/input_derivable_patch.yaml; DO NOT rewrite key_triage.yaml"
            )
            bundle["dispatch_targets"] = {
                "target_ids": allowed,
                "write": ["uo/ir/input_derivable_patch.yaml", "uo/ir/key_shape_resolve/**"],
                "forbid_write": ["uo/ir/key_triage.yaml"],
            }
        prompt_r = _render_placeholders(prompt, **{**ph_kwargs, "target": target_line})

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
    stub = ""
    if execution_mode == EXECUTION_SUBAGENT:
        stub = _build_task_prompt_stub(
            actor_id=actor_id,
            action_id=action_id,
            run_id=run_id,
            session_dir=sdir.as_posix(),
            prompt_path=prompt_path,
            method_path=method_path,
            bundle_path=bundle_path,
            dispatch_targets=bundle.get("dispatch_targets")
            if isinstance(bundle.get("dispatch_targets"), dict)
            else None,
        )
        bundle["task_prompt_stub"] = stub

    from ascendc_pilot.authorize.lease import issue_action_lease
    from datetime import datetime, timezone

    write_paths = list(action.get("allowed_write_paths") or [])
    if not write_paths:
        write_paths = action_write_paths(wid, action_id, run_id=run_id)
    else:
        write_paths = [expand_path_template(p, run_id=run_id) for p in write_paths]
    forbid_write = [
        expand_path_template(p, run_id=run_id)
        for p in list(action.get("forbidden_write_paths") or [])
    ]
    # Dispatch targets may further narrow write paths for producers.
    dt = bundle.get("dispatch_targets") if isinstance(bundle.get("dispatch_targets"), dict) else {}
    if dt.get("write"):
        write_paths = [expand_path_template(str(p), run_id=run_id) for p in dt["write"]]
    if dt.get("forbid_write"):
        forbid_write = [
            expand_path_template(str(p), run_id=run_id) for p in dt["forbid_write"]
        ] + forbid_write
    allowed_targets = [str(x) for x in (dt.get("target_ids") or []) if str(x).strip()]
    # Outer containment: workflow write_roots; precise paths are Action lease.
    wf_roots = list((get_workflow(wid) or {}).get("write_roots") or [])
    lease = issue_action_lease(
        project_root,
        state=state,
        action_id=action_id,
        actor_id=actor_id,
        mode="normal",
        allowed_read_roots=[sdir.as_posix()],
        allowed_write_roots=wf_roots,
        allowed_write_paths=write_paths,
        allowed_read_paths=list(action.get("allowed_read_paths") or []),
        forbidden_write_paths=forbid_write,
        allowed_target_ids=allowed_targets,
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
    bundle["allowed_target_ids"] = allowed_targets
    bundle["staging_dir"] = staging_dir(sdir).as_posix()

    _dump(sdir / "session.yaml", bundle)
    (sdir / "method.md").write_text(method_r, encoding="utf-8")
    (sdir / "prompt.md").write_text(prompt_r, encoding="utf-8")
    if stub:
        (sdir / "task_prompt_stub.md").write_text(stub, encoding="utf-8")
    _dump(
        sdir / "bundle.yaml",
        {k: v for k, v in bundle.items() if k not in {"nonce", "prepare_nonce"}},
    )
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

    result: dict[str, Any] = {
        "ok": True,
        "phase_runtime": "prepare",
        "action_id": action_id,
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

    if execution_mode == EXECUTION_DETERMINISTIC or role_id == "deterministic_engine":
        eng = invoke_engine(project_root, wid, action_id, ctx=eng_ctx)
        result["engine"] = eng
        fin = finalize_action(project_root, action_id, engine_result=eng)
        result["auto_finalize"] = True
        result["finalize"] = fin
        result["ok"] = bool(fin.get("ok"))
        return result

    if execution_mode == EXECUTION_PRIMARY_INTERACTIVE:
        interactive_steps = [
            f"acp uo-scope scan --project <PROJECT_ROOT> --architecture {architecture}",
            "AskQuestion: continue | revise | stop | manual_supplement",
            "acp uo-scope checkpoint --project <PROJECT_ROOT> --decision <decision>",
            "acp uo-scope build-evidence --project <PROJECT_ROOT>",
            "acp uo-scope closure --project <PROJECT_ROOT>",
            "acp uo-scope stage --project <PROJECT_ROOT>",
            "MCP index_repository → uo/cbm/index_stage",
            "acp uo-scope record-index --project <PROJECT_ROOT> --cbm-project <MCP_PROJECT>",
            "acp uo-scope finalize --project <PROJECT_ROOT>",
            f"acp run-action {action_id} --finalize --project <PROJECT_ROOT>",
        ]
        # Render project root into the interactive step list for the primary.
        interactive_steps = [s.replace("<PROJECT_ROOT>", root_s) for s in interactive_steps]
        result["interactive_steps"] = interactive_steps
        result["message_zh"] = (
            f"已准备 primary_interactive Action `{action_id}`。"
            f"请在当前 primary 会话按 `primary_instructions_path` / interactive_steps 执行；"
            f"禁止 Task 派发自身或再次 `acp run-action {action_id}`（prepare）。"
            f"完成后 `acp run-action {action_id} --finalize`。"
        )
        result["dispatch_task"] = False
        return result

    result["message_zh"] = (
        f"已准备 Action Runtime Bundle；派发 actor `{actor_id}` 时 "
        f"Task 正文只用返回的 `task_prompt_stub`（或 session 下 task_prompt_stub.md）；"
        f"禁止复述 METHOD / 禁止塞额外目标 / 禁止整包粘贴大文件。"
        f"subagent_type/agent=`{actor_id}`，action_id={action_id}。"
        f"Primary 禁止代写正式 IR。完成后 "
        f"acp run-action {action_id} --finalize"
    )
    result["task_prompt_stub"] = stub
    result["task_prompt_stub_path"] = (sdir / "task_prompt_stub.md").as_posix()
    result["dispatch_task"] = True
    if wid == "uo-init" and action_id == "extract_plan":
        result["message_zh"] = (
            f"已准备 extract_plan；派发 `{actor_id}` 时原样使用 `task_prompt_stub`："
            f"只确认 candidates→extract_plan.yaml。"
            f"禁止塞 llm_tasks/mark_missing。完成后 "
            f"acp run-action extract_plan --finalize，然后必须 `acp next`。"
        )
        if prepare_engine is not None:
            result["dispatch_targets"] = bundle.get("dispatch_targets")
    if wid == "uo-init" and action_id == "adjudicate_llm_tasks":
        result["message_zh"] = (
            f"已准备 adjudicate_llm_tasks；派发 `{actor_id}` 时原样使用 `task_prompt_stub`："
            f"只裁决 open blocking llm_tasks→semantic_patches.yaml。"
            f"禁止写 ledger/派生图。完成后 "
            f"acp run-action adjudicate_llm_tasks --finalize，然后必须 `acp next` → apply_semantic_patch。"
        )
        result["dispatch_targets"] = bundle.get("dispatch_targets")
    return result


def _finalize_inject_artifact_identity(
    project_root: Path,
    *,
    session: dict[str, Any],
    action_id: str,
    contract_id: str,
) -> None:
    """Overwrite LLM-declared identity with session-trusted artifact_identity."""
    from ascendc_pilot.ownership import artifact_identity_from_session, inject_trusted_identity
    from ascendc_pilot.paths import uo_root as _uo_root

    identity = artifact_identity_from_session(session)
    owned: dict[str, Path] = {
        "extract_plan": _uo_root(project_root) / "ir" / "extract_plan.yaml",
        "adjudicate_llm_tasks": _uo_root(project_root) / "ir" / "semantic_patches.yaml",
        "key_triage": _uo_root(project_root) / "ir" / "key_triage.yaml",
        "key_resolution": _uo_root(project_root) / "ir" / "input_derivable_patch.yaml",
        "confidence_review": _uo_root(project_root) / "review" / "confidence_reason_review.yaml",
        "kb_review": _uo_root(project_root) / "review" / "kb_product_review.yaml",
        "scope_confirmation": _uo_root(project_root)
        / "runs"
        / str(session.get("run_id") or "")
        / "scope"
        / "scope_confirmed.yaml",
    }
    path = owned.get(action_id)
    if path is None or not path.is_file() or yaml is None:
        return
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        return
    if not isinstance(doc, dict):
        return
    trusted = inject_trusted_identity(doc, identity)
    # Reject missing identity on producer artifacts prior to overwrite (migration).
    if action_id in {"extract_plan", "adjudicate_llm_tasks", "key_triage", "key_resolution"}:
        # Always overwrite; LLM values are not trusted.
        pass
    _dump(path, trusted)
    # Also stamp scope receipt when present.
    if action_id == "scope_confirmation":
        receipt = path.parent / "receipt.yaml"
        if receipt.is_file():
            try:
                rdoc = yaml.safe_load(receipt.read_text(encoding="utf-8")) or {}
            except Exception:  # noqa: BLE001
                rdoc = {}
            if isinstance(rdoc, dict):
                _dump(receipt, inject_trusted_identity(rdoc, identity))


def _revoke_lease_after_finalize(
    project_root: Path,
    *,
    reason: str,
    touch_active_action: bool,
) -> None:
    try:
        from ascendc_pilot.authorize.lease import revoke_active_lease

        revoke_active_lease(
            project_root,
            reason=reason,
            touch_active_action=touch_active_action,
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
    from ascendc_pilot.authorize.lease import is_lease_revoked, load_lease

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
            "message_zh": "缺少 prepare session；请先 acp run-action <action_id>",
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

    active = _load(agent_root(project_root) / "state" / "active_action.yaml")
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

    lease = load_lease(project_root)
    if not lease:
        return {
            "ok": False,
            "error": "LEASE_REVOKED",
            "message_zh": "当前无有效 lease；请重新 prepare",
        }
    if str(lease.get("status") or "").lower() == "revoked" or is_lease_revoked(
        project_root, session_lease
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


def finalize_action(
    project_root: Path,
    action_id: str,
    *,
    engine_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ensure_agent_layout(project_root)
    state = load_state(project_root)
    if not state:
        return {"ok": False, "error": "no_active_workflow"}
    wid = str(state.get("workflow_id") or "")
    phase = str(state.get("phase") or "")
    run_id = str(state.get("run_id") or "")
    action = _action_spec(wid, action_id, phase)
    if action is None or action.get("_not_in_phase"):
        return {"ok": False, "error": "action_not_allowed", "action_id": action_id, "phase": phase}

    sdir = _session_dir(project_root, run_id, action_id)
    session = _load(sdir / "session.yaml")
    if not session:
        return {
            "ok": False,
            "error": "no_session",
            "message_zh": "缺少 prepare session；请先 acp run-action <action_id>",
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

        cur = load_lease(project_root)
        session_lease = str(session.get("lease_id") or "").strip()
        if cur and session_lease and str(cur.get("lease_id") or "") == session_lease:
            _revoke_lease_after_finalize(
                project_root,
                reason="finalize_denied",
                touch_active_action=True,
            )
        return bind_err

    actor_id = str(session.get("actor_id") or action.get("agent_id") or "")
    contract_id = str(session.get("output_contract_id") or action.get("output_contract_id") or "")
    action_sid = str(session.get("action_session_id") or "")

    # Inject trusted identity into producer/canonical artifacts before contract checks.
    _finalize_inject_artifact_identity(
        project_root,
        session=session,
        action_id=action_id,
        contract_id=contract_id,
    )

    apply_result: dict[str, Any] | None = None
    if wid == "tg-init" and action_id == "semantic_bind" and engine_result is None:
        apply_result = _apply_semantic_bind_on_finalize(project_root, session=session)
        if not apply_result.get("ok"):
            session["status"] = "finalize_failed"
            session["apply_result"] = apply_result
            _dump(sdir / "session.yaml", session)
            fail_payload = {
                "ok": False,
                "phase_runtime": "finalize",
                "action_id": action_id,
                "error": apply_result.get("error") or "APPLY_FAILED",
                "apply_result": apply_result,
                "message_zh": str(apply_result.get("message") or "semantic_bind 补丁应用失败"),
            }
            return _attach_finalize_observation(
                project_root,
                fail_payload,
                action_id=action_id,
                messages=[
                    str(apply_result.get("error") or "APPLY_FAILED"),
                    str(apply_result.get("message") or ""),
                ],
            )

    # extract_plan finalize: validate plan + build host/kernel/tilingkey/bridge layers.
    if wid == "uo-init" and action_id == "extract_plan" and engine_result is None:
        fin_ctx = {
            "op_name": state.get("op_name") or "",
            "architecture": state.get("architecture") or "arch35",
            "run_id": run_id,
            "extract_plan_mode": "finalize",
        }
        apply_result = invoke_engine(project_root, wid, action_id, ctx=fin_ctx)
        if not apply_result.get("ok"):
            session["status"] = "finalize_failed"
            session["apply_result"] = apply_result
            _dump(sdir / "session.yaml", session)
            fail_payload = {
                "ok": False,
                "phase_runtime": "finalize",
                "action_id": action_id,
                "error": apply_result.get("error") or "EXTRACT_PLAN_BUILD_FAILED",
                "apply_result": apply_result,
                "message_zh": str(apply_result.get("error") or "extract_plan 分层构建失败"),
            }
            return _attach_finalize_observation(
                project_root,
                fail_payload,
                action_id=action_id,
                messages=[
                    str(apply_result.get("error") or "EXTRACT_PLAN_BUILD_FAILED"),
                    str((apply_result.get("apply") or {}).get("rejected") or ""),
                ],
            )

    contract = _check_output_contract(
        project_root,
        contract_id,
        run_id=run_id,
        workflow_id=wid,
        action_id=action_id,
        actor_id=actor_id,
        action_session_id=action_sid,
    )

    # KEY resolution: reject patches that expand beyond prepare target_ids.
    target_violation: dict[str, Any] | None = None
    if action_id == "key_resolution":
        allowed = []
        dt = session.get("dispatch_targets") if isinstance(session.get("dispatch_targets"), dict) else {}
        allowed = [str(x) for x in (dt.get("target_ids") or []) if str(x).strip()]
        if allowed:
            from ascendc_pilot.paths import uo_root as _uo_root

            patch_doc = _load_yaml_file(_uo_root(project_root) / "ir" / "input_derivable_patch.yaml")
            found: list[str] = []
            items = patch_doc.get("items") or patch_doc.get("patches") or patch_doc.get("keys") or []
            if isinstance(items, list):
                for it in items:
                    if isinstance(it, dict):
                        kid = str(it.get("id") or it.get("key") or it.get("key_id") or "").strip()
                        if kid:
                            found.append(kid)
            elif isinstance(patch_doc.get("keys"), dict):
                found.extend(str(k) for k in patch_doc["keys"])
            extra = [k for k in found if k not in set(allowed)]
            if extra:
                target_violation = {
                    "ok": False,
                    "error": "KEY_TARGET_SCOPE_VIOLATION",
                    "extra_keys": extra,
                    "allowed_target_ids": allowed,
                    "message": f"key_resolution wrote keys outside prepare targets: {extra}",
                }

    from ascendc_pilot.gates import run_named_gate
    from ascendc_pilot.spec_hashes import workflow_spec_hash

    gate_results = []
    for gid in session.get("gates") or action.get("gates") or []:
        gate_results.append(run_named_gate(project_root, str(gid)))

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
    overall_ok = bool(gates_ok and contract_ok and engine_ok and targets_ok)

    checker_result = {
        "ok": overall_ok,
        "gates": gate_results,
        "output_contract": contract,
        "engine": engine_result or {},
        "apply": apply_result or {},
        "target_violation": target_violation or {},
    }

    out_hashes = _collect_output_hashes(
        project_root,
        contract_id,
        run_id=run_id,
        workflow_id=wid,
        action_id=action_id,
        actor_id=actor_id,
        action_session_id=action_sid,
    )
    if not out_hashes:
        out_hashes = {"session": file_sha256(sdir / "session.yaml") or "none"}

    in_hashes = {
        "context_pack": file_sha256(Path(str(session.get("context_pack_path") or ""))) or "",
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
            actor_type=str(session.get("role_id") or action.get("role_id") or "producer"),
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
        _dump(sdir / "session.yaml", session)
        _write_active_action(
            project_root,
            {
                "version": 1,
                "run_id": run_id,
                "workflow_id": wid,
                "phase": phase,
                "action_id": action_id,
                "actor_id": actor_id,
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
        )
        append_event(
            project_root,
            {"type": "action_finalized", "action_id": action_id, "actor_id": actor_id, "ok": True},
            run_id=run_id,
        )
    else:
        session["status"] = "finalize_failed"
        session["checker_result"] = checker_result
        _dump(sdir / "session.yaml", session)
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
        "checker_result": checker_result,
        "message_zh": (
            "Action 已 finalize 并签发可信收据；下一步必须 `acp next`（取 recommended_next_action），"
            "禁止跳步；仅 phase 门禁齐备时才 `acp advance`"
            if overall_ok
            else "Finalize 失败：Checker/Output Contract 未通过"
        ),
    }
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
        return result

    msgs = ["Finalize 失败：Checker/Output Contract 未通过"]
    for g in gate_results:
        if not g.get("ok"):
            msgs.append(str(g.get("message") or g.get("gate") or "gate_failed"))
    if not contract_ok:
        msgs.append(str(contract.get("message") or "output_contract_failed"))
    if not engine_ok and engine_result:
        msgs.append(str(engine_result.get("error") or engine_result.get("message") or "engine_failed"))
    return _attach_finalize_observation(project_root, result, action_id=action_id, messages=msgs)


def _attach_finalize_observation(
    project_root: Path,
    payload: dict[str, Any],
    *,
    action_id: str,
    messages: list[str],
) -> dict[str, Any]:
    from ascendc_pilot.observation import record_pilot_result
    from ascendc_pilot.state import load_state, save_state

    recorded = record_pilot_result(
        project_root,
        ok=False,
        action_id=action_id,
        step_id="action_finalize",
        messages=[m for m in messages if m],
        source="finalize_action",
    )
    out = dict(payload)
    out["observation"] = recorded.get("observation")
    out["status"] = recorded.get("status")
    out["last_failure"] = recorded.get("last_failure")
    out["failure_card"] = recorded.get("failure_card")

    # Propagate engine recovery_actions into last_failure for rework authorize.
    eng = payload.get("engine") if isinstance(payload.get("engine"), dict) else {}
    checker = payload.get("checker_result") if isinstance(payload.get("checker_result"), dict) else {}
    eng2 = checker.get("engine") if isinstance(checker.get("engine"), dict) else {}
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
    return out


def run_action(project_root: Path, action_id: str, *, finalize: bool = False) -> dict[str, Any]:
    if finalize:
        return finalize_action(project_root, action_id)
    return prepare_action(project_root, action_id)
