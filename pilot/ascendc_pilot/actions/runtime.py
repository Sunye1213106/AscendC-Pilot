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


def _render_placeholders(text: str, *, run_id: str, action_id: str, workflow_id: str, actor_id: str) -> str:
    repl = {
        "<RUN_ID>": run_id,
        "<ACTION_ID>": action_id,
        "<WORKFLOW_ID>": workflow_id,
        "<ACTOR_ID>": actor_id,
        "<TARGET_IDS_OR_FILES>": "(see context pack / human input)",
        "<OP_NAME>": "",
        "<PROJECT_ROOT>": "",
    }
    out = text
    for k, v in repl.items():
        out = out.replace(k, v)
    # Angle-bracket leftovers that look like template tokens → mark unresolved
    out = re.sub(r"<([A-Z][A-Z0-9_]{2,})>", r"[UNRESOLVED:\1]", out)
    return out


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


def _collect_output_hashes(project_root: Path, contract_id: str) -> dict[str, str]:
    root = agent_root(project_root)
    hashes: dict[str, str] = {}
    import hashlib

    for rel in OUTPUT_CONTRACT_PATHS.get(contract_id, []):
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


def _check_output_contract(project_root: Path, contract_id: str) -> dict[str, Any]:
    if not contract_id:
        return {"ok": True, "skipped": True}
    root = agent_root(project_root)
    paths = OUTPUT_CONTRACT_PATHS.get(contract_id)
    if paths is None:
        return {"ok": True, "skipped": True, "message": f"no path map for {contract_id}"}
    missing = []
    empty = []
    for rel in paths:
        matches = _resolve_contract_paths(root, rel)
        if not matches:
            missing.append(rel)
            continue
        nonempty = False
        for path in matches:
            if path.is_file() and path.stat().st_size > 0:
                nonempty = True
                break
            if path.is_dir() and any(p.is_file() and p.stat().st_size > 0 for p in path.rglob("*")):
                nonempty = True
                break
        if not nonempty:
            empty.append(rel)

    # Stronger nonempty globs for TG plan/solve contracts
    glob_miss: list[str] = []
    for pattern in OUTPUT_CONTRACT_NONEMPTY_GLOBS.get(contract_id, []):
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

    ok = not missing and not empty and not glob_miss
    parts = []
    if missing:
        parts.append(f"missing outputs: {missing}")
    if empty:
        parts.append(f"empty outputs: {empty}")
    if glob_miss:
        parts.append(f"missing nonempty artifacts: {glob_miss}")
    return {
        "ok": ok,
        "contract_id": contract_id,
        "missing": missing,
        "empty": empty,
        "missing_globs": glob_miss,
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

    actor_id = str(action.get("agent_id") or (action.get("actors") or ["unknown"])[0])
    role_id = str(action.get("role_id") or "")
    nonce = secrets.token_hex(16)
    sdir = _session_dir(project_root, run_id, action_id)
    sdir.mkdir(parents=True, exist_ok=True)

    from ascendc_pilot.context import build_context_pack

    pack = build_context_pack(project_root, intent=f"run-action:{action_id}", topic=action_id)
    repo = _repo_root(project_root)
    method, prompt = _load_method_and_prompt(repo, action)
    method_r = _render_placeholders(method, run_id=run_id, action_id=action_id, workflow_id=wid, actor_id=actor_id)
    prompt_r = _render_placeholders(prompt, run_id=run_id, action_id=action_id, workflow_id=wid, actor_id=actor_id)

    bundle = {
        "version": 1,
        "run_id": run_id,
        "workflow_id": wid,
        "phase": phase,
        "action_id": action_id,
        "actor_id": actor_id,
        "role_id": role_id,
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
        "context_pack_path": pack.get("path"),
        "status": "prepared",
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

    _dump(sdir / "session.yaml", bundle)
    (sdir / "method.md").write_text(method_r, encoding="utf-8")
    (sdir / "prompt.md").write_text(prompt_r, encoding="utf-8")
    _dump(sdir / "bundle.yaml", {k: v for k, v in bundle.items() if k != "nonce"})
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
            "session_dir": sdir.as_posix(),
            "status": "prepared",
        },
    )

    from ascendc_pilot.authorize.lease import issue_action_lease

    lease = issue_action_lease(
        project_root,
        state=state,
        action_id=action_id,
        mode="normal",
        allowed_read_roots=[sdir.as_posix()],
        allowed_write_roots=list((get_workflow(wid) or {}).get("write_roots") or []),
    )

    append_event(
        project_root,
        {
            "type": "ActionPrepared",
            "action_id": action_id,
            "actor_id": actor_id,
            "role_id": role_id,
            "lease_id": lease.get("lease_id"),
        },
        run_id=run_id,
    )

    result: dict[str, Any] = {
        "ok": True,
        "phase_runtime": "prepare",
        "action_id": action_id,
        "actor_id": actor_id,
        "role_id": role_id,
        "run_id": run_id,
        "session_dir": sdir.as_posix(),
        "bundle_path": (sdir / "bundle.yaml").as_posix(),
        "prompt_path": (sdir / "prompt.md").as_posix(),
        "method_path": (sdir / "method.md").as_posix(),
        "lease_id": lease.get("lease_id"),
        "auto_finalize": False,
    }
    if prepare_engine is not None:
        result["prepare_engine"] = prepare_engine

    if role_id == "deterministic_engine":
        eng = invoke_engine(project_root, wid, action_id, ctx=eng_ctx)
        result["engine"] = eng
        fin = finalize_action(project_root, action_id, engine_result=eng)
        result["auto_finalize"] = True
        result["finalize"] = fin
        result["ok"] = bool(fin.get("ok"))
        return result

    result["message_zh"] = (
        f"已准备 Action Runtime Bundle；请派发 actor `{actor_id}` "
        f"（写入时需携带 action_id={action_id} / ASCENDC_ACTION），"
        f"完成后执行 acp run-action {action_id} --finalize"
    )
    return result


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
    if not session or not session.get("nonce"):
        return {
            "ok": False,
            "error": "no_session",
            "message_zh": "缺少 prepare session；请先 acp run-action <action_id>",
        }
    if str(session.get("run_id")) != run_id or str(session.get("action_id")) != action_id:
        return {"ok": False, "error": "session_mismatch"}

    actor_id = str(session.get("actor_id") or action.get("agent_id") or "")
    contract_id = str(session.get("output_contract_id") or action.get("output_contract_id") or "")

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

    contract = _check_output_contract(project_root, contract_id)

    from ascendc_pilot.gates import run_named_gate
    from ascendc_pilot.spec_hashes import workflow_spec_hash

    gate_results = []
    for gid in session.get("gates") or action.get("gates") or []:
        gate_results.append(run_named_gate(project_root, str(gid)))

    checker_required = bool(session.get("checker_required", action.get("checker_required", True)))
    gates_ok = all(g.get("ok") for g in gate_results) if gate_results else True
    # Soft contract for human/primary when checker not required
    if not checker_required:
        contract_ok = True
    else:
        contract_ok = bool(contract.get("ok") or contract.get("skipped"))

    engine_ok = True if engine_result is None else bool(engine_result.get("ok", True))
    overall_ok = bool(gates_ok and contract_ok and engine_ok)

    checker_result = {
        "ok": overall_ok,
        "gates": gate_results,
        "output_contract": contract,
        "engine": engine_result or {},
        "apply": apply_result or {},
    }

    out_hashes = _collect_output_hashes(project_root, contract_id)
    if not out_hashes:
        out_hashes = {"session": file_sha256(sdir / "session.yaml") or "none"}

    in_hashes = {
        "context_pack": file_sha256(Path(str(session.get("context_pack_path") or ""))) or "",
        "prompt": file_sha256(sdir / "prompt.md") or "",
    }
    if isinstance(session.get("prepare_stamp"), dict):
        in_hashes["prepare_nonce"] = str(session["prepare_stamp"].get("nonce") or "")
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
            nonce=str(session.get("nonce")),
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
                "status": "finalized",
                "receipt": str(receipt_path),
            },
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
            "Action 已 finalize 并签发可信收据；可 acp advance"
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
    return out


def run_action(project_root: Path, action_id: str, *, finalize: bool = False) -> dict[str, Any]:
    if finalize:
        return finalize_action(project_root, action_id)
    return prepare_action(project_root, action_id)
