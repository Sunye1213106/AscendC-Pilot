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

from ascendc_harness.actions.engines import OUTPUT_CONTRACT_PATHS, invoke_engine
from ascendc_harness.paths import agent_root, ensure_agent_layout, runs_root
from ascendc_harness.runs import append_event, file_sha256, issue_receipt, run_dir
from ascendc_harness.state import load_state
from ascendc_harness.workflows import actions_for_phase, get_workflow


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
    if (root / "skills-src").is_dir():
        return root
    here = Path(__file__).resolve().parents[3]
    if (here / "skills-src").is_dir():
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
        mp = repo / "skills-src" / "actions" / wf / name / "METHOD.md"
        if mp.is_file():
            method = mp.read_text(encoding="utf-8")
    tpid = str(action.get("task_prompt_id") or "")
    if tpid:
        if "/" in tpid:
            dom, name = tpid.split("/", 1)
            pp = repo / "prompts-src" / "tasks" / dom / f"{name}.md"
        else:
            pp = repo / "prompts-src" / "tasks" / f"{tpid}.md"
        if pp.is_file():
            prompt = pp.read_text(encoding="utf-8")
    return method, prompt


def _collect_output_hashes(project_root: Path, contract_id: str) -> dict[str, str]:
    root = agent_root(project_root)
    hashes: dict[str, str] = {}
    for rel in OUTPUT_CONTRACT_PATHS.get(contract_id, []):
        path = root / rel
        if path.is_file():
            hashes[rel] = file_sha256(path)
        elif path.is_dir():
            # Hash a stable listing fingerprint
            files = sorted(p for p in path.rglob("*") if p.is_file())[:20]
            blob = "\n".join(f"{p.relative_to(root).as_posix()}:{file_sha256(p)}" for p in files)
            import hashlib

            hashes[rel] = hashlib.sha256(blob.encode("utf-8")).hexdigest() if files else "empty_dir"
    return hashes


def _check_output_contract(project_root: Path, contract_id: str) -> dict[str, Any]:
    if not contract_id:
        return {"ok": True, "skipped": True}
    root = agent_root(project_root)
    paths = OUTPUT_CONTRACT_PATHS.get(contract_id)
    if paths is None:
        return {"ok": True, "skipped": True, "message": f"no path map for {contract_id}"}
    missing = []
    for rel in paths:
        path = root / rel
        if not path.exists():
            missing.append(rel)
    return {
        "ok": not missing,
        "contract_id": contract_id,
        "missing": missing,
        "message": "ok" if not missing else f"missing outputs: {missing}",
    }


def prepare_action(project_root: Path, action_id: str) -> dict[str, Any]:
    ensure_agent_layout(project_root)
    state = load_state(project_root)
    if not state:
        return {"ok": False, "error": "no_active_workflow", "message_zh": "无活动 workflow；请先 harness start"}
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

    from ascendc_harness.context import build_context_pack

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
    _dump(sdir / "session.yaml", bundle)
    (sdir / "method.md").write_text(method_r, encoding="utf-8")
    (sdir / "prompt.md").write_text(prompt_r, encoding="utf-8")
    _dump(sdir / "bundle.yaml", {k: v for k, v in bundle.items() if k != "nonce"})

    append_event(
        project_root,
        {"type": "action_prepared", "action_id": action_id, "actor_id": actor_id, "role_id": role_id},
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
        "auto_finalize": False,
    }

    if role_id == "deterministic_engine":
        eng = invoke_engine(project_root, wid, action_id, ctx={"run_id": run_id})
        result["engine"] = eng
        fin = finalize_action(project_root, action_id, engine_result=eng)
        result["auto_finalize"] = True
        result["finalize"] = fin
        result["ok"] = bool(fin.get("ok"))
        return result

    result["message_zh"] = (
        f"已准备 Action Runtime Bundle；请派发 actor `{actor_id}`，"
        f"完成后执行 harness run-action {action_id} --finalize"
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
            "message_zh": "缺少 prepare session；请先 harness run-action <action_id>",
        }
    if str(session.get("run_id")) != run_id or str(session.get("action_id")) != action_id:
        return {"ok": False, "error": "session_mismatch"}

    actor_id = str(session.get("actor_id") or action.get("agent_id") or "")
    contract_id = str(session.get("output_contract_id") or action.get("output_contract_id") or "")
    contract = _check_output_contract(project_root, contract_id)

    from ascendc_harness.gates import run_named_gate
    from ascendc_harness.spec_hashes import workflow_spec_hash

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
    }

    out_hashes = _collect_output_hashes(project_root, contract_id)
    if not out_hashes:
        out_hashes = {"session": file_sha256(sdir / "session.yaml") or "none"}

    in_hashes = {
        "context_pack": file_sha256(Path(str(session.get("context_pack_path") or ""))) or "",
        "prompt": file_sha256(sdir / "prompt.md") or "",
    }

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

    return {
        "ok": overall_ok,
        "phase_runtime": "finalize",
        "action_id": action_id,
        "actor_id": actor_id,
        "run_id": run_id,
        "receipt": str(receipt_path) if receipt_path else None,
        "checker_result": checker_result,
        "message_zh": (
            "Action 已 finalize 并签发可信收据；可 harness advance"
            if overall_ok
            else "Finalize 失败：Checker/Output Contract 未通过"
        ),
    }


def run_action(project_root: Path, action_id: str, *, finalize: bool = False) -> dict[str, Any]:
    if finalize:
        return finalize_action(project_root, action_id)
    return prepare_action(project_root, action_id)
