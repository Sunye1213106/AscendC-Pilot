"""Harness-wrapped UO scope confirmation steps (no direct domain CLI)."""



from __future__ import annotations



import io

from contextlib import redirect_stderr, redirect_stdout

from pathlib import Path

from typing import Any





def _resolve_op_name(project: Path, op_name: str) -> str:

    name = str(op_name or "").strip()

    if name:

        return name

    return project.name





def _active_action_id(project: Path) -> str:

    try:

        from ascendc_pilot.authorize.lease import load_lease

        from ascendc_pilot.paths import agent_root



        lease = load_lease(project)

        if lease.get("action_id") and str(lease.get("action_id")) != "_containment":

            return str(lease["action_id"])

        active = agent_root(project) / "state" / "active_action.yaml"

        if active.is_file():

            import yaml



            data = yaml.safe_load(active.read_text(encoding="utf-8")) or {}

            if isinstance(data, dict) and data.get("action_id"):

                return str(data["action_id"])

    except Exception:  # noqa: BLE001

        pass

    return ""





def _record_step_result(

    project: Path,

    payload: dict[str, Any],

    *,

    action_id: str,

    step_id: str,

    messages: list[str] | None = None,

) -> dict[str, Any]:

    """Attach Observation + atomically update run state on failure (and audit on success)."""

    from ascendc_pilot.observation import record_pilot_result



    ok = bool(payload.get("ok"))

    msgs = list(messages or [])

    if not ok and payload.get("message_zh"):

        msgs.append(str(payload["message_zh"]))

    if not ok and payload.get("error"):

        msgs.append(str(payload["error"]))



    recorded = record_pilot_result(

        project,

        ok=ok,

        action_id=action_id,

        step_id=step_id,

        messages=msgs if not ok else None,

        source="uo_scope",

        extra={"exit_code": payload.get("exit_code"), "uo_scope_step": step_id},

    )

    payload = dict(payload)

    payload["observation"] = recorded.get("observation")

    if not ok:

        payload["status"] = recorded.get("status")

        payload["last_failure"] = recorded.get("last_failure")

        payload["failure_card"] = recorded.get("failure_card")

        # Surface findings for agents without reading internals

        obs = recorded.get("observation") or {}

        if obs.get("findings") and "errors" not in payload:

            payload["errors"] = [f.get("message") for f in obs["findings"] if isinstance(f, dict)]

    return payload





def run_uo_scope(

    project: Path,

    step: str,

    *,

    op_name: str = "",

    architecture: str = "arch35",

    decision: str = "",

    notes: str = "",

    cbm_project: str = "",

) -> dict[str, Any]:

    """Run one deterministic scope step under Pilot control."""

    project = Path(project).expanduser().resolve()

    step_l = str(step or "").strip().lower().replace("_", "-")

    arch = str(architecture or "arch35").strip() or "arch35"

    resolved_op = _resolve_op_name(project, op_name)

    action_id = _active_action_id(project)

    if not action_id:
        return {
            "ok": False,
            "error": "no_active_action",
            "message_zh": (
                "uo-scope 需要有效的 active_action / lease；"
                "请先 `acp run-action scope_confirmation` prepare，禁止默认伪造 action_id"
            ),
            "step": step_l,
        }

    cbm_name = str(cbm_project or "").strip()



    if step_l in {"scan", "macro-scan", "macro_scope_scan"}:

        from uo.scripts.macro_scope_scan import main as scan_main



        argv = [str(project), "--architecture", arch, "--op-name", resolved_op]

        code = int(scan_main(argv) or 0)

        payload = {

            "ok": code == 0,

            "step": "scan",

            "exit_code": code,

            "architecture": arch,

            "op_name": resolved_op,

        }

        return _record_step_result(project, payload, action_id=action_id, step_id="uo_scope_scan")



    if step_l in {"checkpoint", "review", "review-checkpoint"}:

        from uo.scripts.review_checkpoint import main as review_main



        if not decision:

            payload = {

                "ok": False,

                "step": "checkpoint",

                "error": "decision_required",

                "message_zh": "需要 --decision continue|revise|stop|manual_supplement",

            }

            return _record_step_result(

                project,

                payload,

                action_id=action_id,

                step_id="uo_scope_checkpoint",

                messages=["decision_required"],

            )

        argv = [

            str(project),

            "--gate",

            "macro_scope",

            "--decision",

            decision,

            "--op-name",

            resolved_op,

        ]

        if notes:

            argv.extend(["--notes", notes])

        code = int(review_main(argv) or 0)

        payload = {

            "ok": code == 0,

            "step": "checkpoint",

            "exit_code": code,

            "decision": decision,

            "op_name": resolved_op,

        }

        return _record_step_result(

            project, payload, action_id=action_id, step_id="uo_scope_checkpoint"

        )



    if step_l in {"build-evidence", "build_evidence", "extract-build-evidence"}:

        from uo.scripts.extract_build_evidence import main as build_main



        argv = [str(project), "--op-name", resolved_op]

        code = int(build_main(argv) or 0)

        payload = {

            "ok": code == 0,

            "step": "build-evidence",

            "exit_code": code,

            "op_name": resolved_op,

        }

        return _record_step_result(

            project, payload, action_id=action_id, step_id="uo_scope_build_evidence"

        )



    if step_l in {"closure", "source-closure", "source_closure"}:

        from uo.scripts.source_closure import main as closure_main



        argv = [str(project), "--op-name", resolved_op, "--architecture", arch]

        code = int(closure_main(argv) or 0)

        payload = {"ok": code == 0, "step": "closure", "exit_code": code, "op_name": resolved_op}

        return _record_step_result(

            project, payload, action_id=action_id, step_id="uo_scope_closure"

        )



    if step_l in {"stage", "stage-cbm", "stage_cbm_scope"}:

        from uo.scripts.stage_cbm_scope import main as stage_main



        argv = [str(project), "--op-name", resolved_op]

        code = int(stage_main(argv) or 0)

        payload = {"ok": code == 0, "step": "stage", "exit_code": code, "op_name": resolved_op}

        return _record_step_result(project, payload, action_id=action_id, step_id="uo_scope_stage")



    if step_l in {"record-index", "record_index", "write-index-meta", "write_index_meta"}:

        from uo.scripts.prepare_operator import main as prepare_main



        if not cbm_name:

            payload = {

                "ok": False,

                "step": "record-index",

                "error": "cbm_project_required",

                "message_zh": (
                    "需要 --cbm-project <MCP index_repository 返回的 project 名>；"
                    "在 MCP 索引之后、uo-scope finalize 之前执行"
                ),

            }

            return _record_step_result(

                project,

                payload,

                action_id=action_id,

                step_id="uo_scope_record_index",

                messages=["cbm_project_required"],

            )

        argv = [

            str(project),

            "--op-name",

            resolved_op,

            "--write-index-meta",

            "--cbm-project",

            cbm_name,

        ]

        try:

            from ascendc_pilot.state import load_state

            bound = str((load_state(project) or {}).get("run_id") or "").strip()

            if bound:

                argv.extend(["--run-id", bound])

        except Exception:  # noqa: BLE001

            pass

        code = int(prepare_main(argv) or 0)

        meta_path = project / ".ascendc-pilot" / "uo" / "cbm" / "index_meta.json"

        payload = {

            "ok": code in {0, 3} and meta_path.is_file(),

            "step": "record-index",

            "exit_code": code,

            "op_name": resolved_op,

            "cbm_project": cbm_name,

            "index_meta": str(meta_path) if meta_path.is_file() else "",

        }

        return _record_step_result(

            project, payload, action_id=action_id, step_id="uo_scope_record_index"

        )



    if step_l in {"finalize", "finalize-scope", "finalize_scope"}:

        from uo.scripts.finalize_scope import finalize_scope



        # Call library API to capture structured messages (not only exit code).

        err_buf = io.StringIO()

        out_buf = io.StringIO()

        with redirect_stdout(out_buf), redirect_stderr(err_buf):

            code, messages = finalize_scope(project, resolved_op)

        code = int(code or 0)

        msgs = [str(m) for m in (messages or []) if str(m).strip()]

        # Include stderr warnings that look like hard findings from older builds

        for line in err_buf.getvalue().splitlines():

            s = line.strip()

            if s and "WARNING:" not in s.upper():

                if s not in msgs:

                    msgs.append(s)

        payload = {

            "ok": code == 0,

            "step": "finalize",

            "exit_code": code,

            "op_name": resolved_op,

            "errors": msgs if code != 0 else [],

        }

        return _record_step_result(

            project,

            payload,

            action_id=action_id,

            step_id="uo_scope_finalize",

            messages=msgs if code != 0 else None,

        )



    payload = {

        "ok": False,

        "error": "unknown_step",

        "message_zh": (

            "未知 step；可用: scan | checkpoint | build-evidence | closure | stage | "
            "record-index | finalize"

        ),

        "step": step,

    }

    return _record_step_result(

        project,

        payload,

        action_id=action_id,

        step_id="uo_scope_unknown",

        messages=["unknown_step", "workflow_spec_error"],

    )





def print_result(payload: dict[str, Any]) -> int:

    from ascendc_pilot.io import configure_stdio, print_json



    configure_stdio()

    print_json(payload)

    return 0 if payload.get("ok") else 1


