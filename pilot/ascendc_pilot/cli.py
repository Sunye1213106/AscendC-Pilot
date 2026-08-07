"""Pilot CLI (acp): doctor / validate / start / next / advance / run-action / ..."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from ascendc_pilot.io import configure_stdio, print_json


def _apply_run_action_limit_flags(args: argparse.Namespace) -> dict[str, Any]:
    """Apply --set / --raise-extract-limits into pilot_params + process env (ses_0662)."""
    project = Path(args.project).resolve()
    sets = list(getattr(args, "set", None) or [])
    raise_limits = bool(getattr(args, "raise_extract_limits", False))
    if not sets and not raise_limits:
        return {}

    # Old extract-plan limit knobs removed with understand-operator-old.
    return {"ok": True, "skipped": True, "reason": "extract_limits_not_applicable"}

    env_to_key = {env: key for key, (env, _default) in EXTRACT_LIMIT_SPECS.items()}
    raised: dict[str, int] = {}

    for item in sets:
        text = str(item or "").strip()
        if not text or "=" not in text:
            continue
        key, _, raw = text.partition("=")
        key = key.strip()
        short = env_to_key.get(key, key)
        if short not in EXTRACT_LIMIT_SPECS:
            continue
        try:
            raised[short] = int(raw.strip())
        except ValueError:
            continue

    if raise_limits:
        cand = (
            project
            / ".ascendc-pilot"
            / "uo"
            / "ir"
            / "extract_plan_candidates.yaml"
        )
        raw_counts: dict[str, int] = {}
        if cand.is_file():
            try:
                import yaml

                doc = yaml.safe_load(cand.read_text(encoding="utf-8")) or {}
                if isinstance(doc, dict) and isinstance(doc.get("raw_counts"), dict):
                    raw_counts = {
                        str(k): int(v)
                        for k, v in doc["raw_counts"].items()
                        if str(k) in EXTRACT_LIMIT_SPECS
                    }
            except Exception:  # noqa: BLE001
                raw_counts = {}
        for key, (_env, default) in EXTRACT_LIMIT_SPECS.items():
            if key not in ("writers", "receivers", "aliases", "non_sink_roots", "extra_entries"):
                continue
            needed = int(raw_counts.get(key) or 0)
            if needed > 0:
                raised[key] = max(raised.get(key, 0), needed)
            elif key not in raised:
                # ensure at least a generous bump when no prior candidates
                if key == "non_sink_roots":
                    raised[key] = max(default * 2, 1024)

    if not raised:
        return {"ok": False, "error": "no_valid_extract_limits"}

    path = persist_extract_limits(project, raised)
    apply_extract_limits_to_environ(raised)
    return {
        "ok": True,
        "extract_limits": {
            EXTRACT_LIMIT_SPECS[k][0]: v for k, v in raised.items() if k in EXTRACT_LIMIT_SPECS
        },
        "persisted": path.as_posix() if path else "",
    }


def main(argv: list[str] | None = None) -> int:
    configure_stdio()
    parser = argparse.ArgumentParser(prog="acp", description="AscendC-Pilot")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_doctor = sub.add_parser("doctor", help="Environment precheck")
    p_doctor.add_argument("--project", type=Path, default=Path.cwd())

    p_gates = sub.add_parser("validate-key-gates", help="Run KEY hard gates (ses_076d)")
    p_gates.add_argument("project", type=Path)
    p_gates.add_argument("--op-name", default="")

    p_validate = sub.add_parser("validate", help="Run all gates for the active workflow")
    p_validate.add_argument("--project", type=Path, default=Path.cwd())

    p_route = sub.add_parser("route", help="Route natural language / slash to workflow")
    p_route.add_argument("text", nargs="+")

    p_status = sub.add_parser("status", help="Show workflow state")
    p_status.add_argument("--project", type=Path, default=Path.cwd())

    p_next = sub.add_parser("next", help="Show next allowed actions / obligations")
    p_next.add_argument("--project", type=Path, default=Path.cwd())

    p_ctx = sub.add_parser("context", help="Build context pack")
    p_ctx.add_argument("--project", type=Path, default=Path.cwd())
    p_ctx.add_argument("--intent", required=True)
    p_ctx.add_argument("--topic", default="")

    p_start = sub.add_parser("start", help="Start workflow at entry_state (idempotent if same workflow active)")
    p_start.add_argument("workflow_id")
    p_start.add_argument("--project", type=Path, default=Path.cwd())
    p_start.add_argument("--intent", default="", help="e.g. diff_only for uo-update")
    p_start.add_argument("--force-new", action="store_true", help="Force a new run even if same workflow is active")
    p_start.add_argument(
        "--decision",
        default="",
        help="Human AskQuestion decision for existing run: continue | reinit",
    )
    p_start.add_argument("--op-name", default="", help="Operator name for UO/TG engines")
    p_start.add_argument("--architecture", default="", help="Target architecture (default arch35)")
    p_start.add_argument("--test-script-root", type=Path, default=None, help="CSV consumer / test script root")
    p_start.add_argument("--csv-consumer-root", type=Path, default=None, help="Alias of --test-script-root")
    p_start.add_argument("--level", default="", help="TG plan/solve level (default L0)")
    p_start.add_argument("--focus", default="", help="TG plan focus")

    p_run_sum = sub.add_parser("run-summary", help="Summarize interrupted uo-init run for AskQuestion")
    p_run_sum.add_argument("--project", type=Path, default=Path.cwd())
    p_run_sum.add_argument("--workflow", default="uo-init")

    p_run = sub.add_parser("run-action", help="Prepare or finalize a workflow Action (sole execution entry)")
    p_run.add_argument("action_id")
    p_run.add_argument("--project", type=Path, default=Path.cwd())
    p_run.add_argument(
        "--finalize",
        action="store_true",
        help="Finalize prepared action: check contract/gates and issue signed receipt",
    )
    p_run.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help=(
            "Persist extract limit / pilot param for this project then run "
            "(e.g. --set UO_EXTRACT_MAX_NON_SINK=1024). Prefer this over shell $env."
        ),
    )
    p_run.add_argument(
        "--raise-extract-limits",
        action="store_true",
        help=(
            "For extract_plan: raise candidate budgets from last candidates raw_counts "
            "(or defaults) into context/pilot_params.yaml, then prepare"
        ),
    )

    p_adv = sub.add_parser("advance", help="Advance phase only if phase_gates pass")
    p_adv.add_argument("next_phase")
    p_adv.add_argument("--project", type=Path, default=Path.cwd())

    p_rework = sub.add_parser("rework", help="Follow an explicit rework edge")
    p_rework.add_argument("--project", type=Path, default=Path.cwd())
    p_rework.add_argument("--reason", default="", help="reason_code for selecting rework edge")
    p_rework.add_argument("--to", default="", help="optional explicit destination phase")

    p_done = sub.add_parser("complete", help="Mark workflow passed only if all gates succeed")
    p_done.add_argument("--project", type=Path, default=Path.cwd())
    p_done.add_argument("--reason", default="")

    p_block = sub.add_parser("block", help="Mark workflow blocked/failed/human_required")
    p_block.add_argument("status", choices=["blocked", "failed", "human_required", "human"])
    p_block.add_argument("--project", type=Path, default=Path.cwd())
    p_block.add_argument("--reason", default="")

    p_inspect = sub.add_parser("inspect-failure", help="Show structured last_failure / failure card")
    p_inspect.add_argument("--project", type=Path, default=Path.cwd())

    p_ir = sub.add_parser(
        "inspect",
        help="Structured IR query (candidates/tasks/yaml counts) for producers",
    )
    p_ir_sub = p_ir.add_subparsers(dest="inspect_cmd", required=True)
    p_ir_c = p_ir_sub.add_parser("candidates", help="Summarize extract_plan_candidates")
    p_ir_c.add_argument("--project", type=Path, default=Path.cwd())
    p_ir_c.add_argument("--kind", default="alias", help="writer|receiver|alias|receiver_binding")
    p_ir_c.add_argument("--min-score", type=float, default=0.0)
    p_ir_c.add_argument("--limit", type=int, default=50)
    p_ir_t = p_ir_sub.add_parser("tasks", help="Summarize llm_tasks")
    p_ir_t.add_argument("--project", type=Path, default=Path.cwd())
    p_ir_t.add_argument("--severity", default="")
    p_ir_t.add_argument("--object-type", default="")
    p_ir_t.add_argument("--limit", type=int, default=50)
    p_ir_y = p_ir_sub.add_parser("yaml", help="Count top-level keys / list lengths in a YAML IR file")
    p_ir_y.add_argument("--project", type=Path, default=Path.cwd())
    p_ir_y.add_argument("--rel", required=True, help="Path relative to .ascendc-pilot/")
    p_ir_d = p_ir_sub.add_parser("duplicates", help="Find duplicate llm_tasks targets")
    p_ir_d.add_argument("--project", type=Path, default=Path.cwd())
    p_ir_v = p_ir_sub.add_parser("validate", help="Validate producer staging / tri-state coverage")
    p_ir_v.add_argument("--project", type=Path, default=Path.cwd())
    p_ir_v.add_argument(
        "--what",
        default="extract_plan",
        choices=["extract_plan", "extract-plan-staging", "parts"],
    )
    p_ir_v.add_argument("--run-id", default="", help="Run id for staging paths")
    p_ir_wl = p_ir_sub.add_parser(
        "extract-plan-obligations",
        help="汇总 extract_plan semantic_obligations / snapshot",
    )
    p_ir_wl.add_argument("--project", type=Path, default=Path.cwd())
    p_ir_wl.add_argument("--run-id", default="")
    p_ir_cov = p_ir_sub.add_parser(
        "extract-plan-relations",
        help="汇总 semantic_relations / unresolved 计数",
    )
    p_ir_cov.add_argument("--project", type=Path, default=Path.cwd())
    p_ir_cov.add_argument("--run-id", default="")

    p_ro = sub.add_parser(
        "ro-search",
        help="Readonly source search wrapper (no shell redirects)",
    )
    p_ro.add_argument("--project", type=Path, default=Path.cwd())
    p_ro.add_argument("--pattern", required=True)
    p_ro.add_argument("--paths", nargs="*", default=["."], help="Relative paths under project")
    p_ro.add_argument("--glob", default="*.{cpp,h,hpp,cc}", dest="file_glob")
    p_ro.add_argument("--limit", type=int, default=50)

    p_retry_env = sub.add_parser(
        "retry-after-environment-fix",
        help="After human_required environment fix, restore rework_required for failed action",
    )
    p_retry_env.add_argument("--project", type=Path, default=Path.cwd())

    p_abort = sub.add_parser("abort", help="Abort current run (mark failed)")
    p_abort.add_argument("--project", type=Path, default=Path.cwd())
    p_abort.add_argument("--reason", default="aborted_by_operator")

    p_hashes = sub.add_parser("spec-hashes", help="Print four Spec Hash digests")
    p_hashes.add_argument("--project", type=Path, default=Path.cwd())
    p_hashes.add_argument("--workflow", default="")

    p_conf = sub.add_parser(
        "emit-confidence-report",
        help="Deterministic engine: assemble confidence_report + confidence_gate from KB",
    )
    p_conf.add_argument("--project", type=Path, default=Path.cwd())
    p_conf.add_argument("--op-name", default="")
    p_conf.add_argument("--no-write-report", action="store_true", help="do not rewrite confidence_report.md")
    p_conf.add_argument("--no-skeleton", action="store_true", help="deprecated alias for --no-write-report")

    p_auth = sub.add_parser("authorize", help="Authorize tool call (OpenCode plugin hook)")
    p_auth.add_argument("--project", type=Path, default=Path.cwd())
    p_auth.add_argument("--tool", required=True)
    p_auth.add_argument("--command", default="")
    p_auth.add_argument("--path", default="")
    p_auth.add_argument("--agent", default="")
    p_auth.add_argument("--action", default="")
    p_auth.add_argument("--lease-id", default="", help="Optional lease id (LEASE_REVOKED if stale)")

    p_scope = sub.add_parser(
        "uo-scope",
        help="Run UO scope_confirmation deterministic steps (scan/checkpoint/finalize)",
    )
    p_scope.add_argument(
        "step",
        choices=[
            "scan",
            "checkpoint",
            "finalize",
        ],
        help="Deterministic scope step",
    )
    p_scope.add_argument("--project", type=Path, default=Path.cwd())
    p_scope.add_argument("--op-name", default="")
    p_scope.add_argument("--architecture", default="arch35")
    p_scope.add_argument(
        "--decision",
        default="",
        help="For checkpoint: continue|revise|stop|manual_supplement",
    )
    p_scope.add_argument("--notes", default="")

    p_uq = sub.add_parser("uo-query", help="Query UO KB graph (wraps uo_kb_query; no direct .py)")
    p_uq.add_argument("--project", type=Path, default=Path.cwd())
    p_uq.add_argument("--op-name", default="")
    p_uq.add_argument("--pattern", default="")
    p_uq.add_argument("--target", default="")
    p_uq.add_argument(
        "--mode",
        default="search",
        choices=(
            "search",
            "constraints",
            "neighbors",
            "impact",
            "field",
            "branches",
            "templates",
        ),
        help="search|constraints|neighbors|impact|field|branches|templates",
    )
    p_uq.add_argument("--file", default="", help="impact 模式：源码相对路径")
    p_uq.add_argument("--line", type=int, default=0, help="impact 模式：起始行")
    p_uq.add_argument("--line-end", type=int, default=0, help="impact 模式：结束行（默认=--line）")
    p_uq.add_argument("--kind", default="", help="search 时限定 node kind，逗号分隔")
    p_uq.add_argument("--depth", type=int, default=1)
    p_uq.add_argument("--limit", type=int, default=50)
    p_uq.add_argument("--relation-type", default="")
    p_uq.add_argument("--status-only", action="store_true")

    p_uo = sub.add_parser("uo", help="UO Host contract 查询与解释")
    p_uo_sub = p_uo.add_subparsers(dest="uo_cmd", required=True)
    for explain_name, help_zh in (
        ("explain-host-value", "解释 HostValue 推导路径"),
        ("explain-tiling-field", "解释 TilingField 写入/读点与影响范围"),
        ("explain-key-dimension", "解释 KeyDimension 组成"),
        ("impact", "按源码位置查影响子图"),
        ("search", "KB 全文/子串检索"),
    ):
        p_ex = p_uo_sub.add_parser(explain_name, help=help_zh)
        p_ex.add_argument("entity_id", nargs="?", default="", help="实体 id / 字段名 / 检索词")
        p_ex.add_argument("--project", type=Path, default=Path.cwd())
        p_ex.add_argument("--op-name", default="")
        p_ex.add_argument("--file", default="")
        p_ex.add_argument("--line", type=int, default=0)
        p_ex.add_argument("--line-end", type=int, default=0)
        p_ex.add_argument("--limit", type=int, default=50)

    p_dbg = sub.add_parser(
        "debug",
        help="Debug mode: capture tool failures / long thoughts; export session bundles",
    )
    p_dbg_sub = p_dbg.add_subparsers(dest="debug_cmd", required=True)
    p_dbg_on = p_dbg_sub.add_parser("enable", help="Enable debug capture")
    p_dbg_on.add_argument("--project", type=Path, default=Path.cwd())
    p_dbg_on.add_argument("--global", dest="global_scope", action="store_true")
    p_dbg_on.add_argument("--thought-char-limit", type=int, default=2500)
    p_dbg_on.add_argument("--parent-session-id", default="", help="Host session id (ses_…)")
    p_dbg_off = p_dbg_sub.add_parser("disable", help="Disable debug capture")
    p_dbg_off.add_argument("--project", type=Path, default=Path.cwd())
    p_dbg_off.add_argument("--global", dest="global_scope", action="store_true")
    p_dbg_st = p_dbg_sub.add_parser("status", help="Show debug config + recent anomalies")
    p_dbg_st.add_argument("--project", type=Path, default=Path.cwd())
    p_dbg_st.add_argument("--limit", type=int, default=20)
    p_dbg_exp = p_dbg_sub.add_parser("export-session", help="Export run + anomalies (+ transcript if found)")
    p_dbg_exp.add_argument("--project", type=Path, default=Path.cwd())
    p_dbg_exp.add_argument("--reason", default="manual")
    p_dbg_exp.add_argument("--subagent", default="")
    p_dbg_exp.add_argument("--session-id", default="", help="Child/task session id (ses_…)")
    p_dbg_exp.add_argument(
        "--parent-session-id",
        default="",
        help="Host/parent session id (ses_…) for this conversation",
    )
    p_dbg_exp.add_argument("--transcript", default="")
    p_dbg_exp.add_argument(
        "--if-enabled",
        action="store_true",
        help="No-op unless debug mode is enabled (used by OpenCode plugin hooks)",
    )
    p_dbg_hook = p_dbg_sub.add_parser("hook", help="Hook stdin JSON handler (Cursor/OpenCode)")
    p_dbg_hook.add_argument("event", help="postToolUseFailure | afterAgentThought | subagentStop | …")
    p_dbg_rec = p_dbg_sub.add_parser("record-tool-failure", help="Manually record a tool failure")
    p_dbg_rec.add_argument("--project", type=Path, default=Path.cwd())
    p_dbg_rec.add_argument("--tool", required=True)
    p_dbg_rec.add_argument("--error", required=True)
    p_dbg_rec.add_argument("--agent", default="")
    p_dbg_rec.add_argument("--action", default="")
    p_dbg_rec.add_argument("--exit-code", type=int, default=None)
    p_dbg_rec.add_argument(
        "--force",
        action="store_true",
        help="Record even if classifier says this is not a real failure",
    )
    p_dbg_th = p_dbg_sub.add_parser("record-thought", help="Analyze/record a thought blob")
    p_dbg_th.add_argument("--project", type=Path, default=Path.cwd())
    p_dbg_th.add_argument("--agent", default="")
    p_dbg_th.add_argument("--text", default="")
    p_dbg_th.add_argument("--stdin", action="store_true")

    p_dbg_reg = p_dbg_sub.add_parser("register-child", help="Register a Task child (parent-scoped debug)")
    p_dbg_reg.add_argument("--project", type=Path, default=Path.cwd())
    p_dbg_reg.add_argument("--parent-session-id", required=True)
    p_dbg_reg.add_argument("--child-session-id", default="")
    p_dbg_reg.add_argument("--workflow-id", default="")
    p_dbg_reg.add_argument("--run-id", default="")
    p_dbg_reg.add_argument("--phase", default="")
    p_dbg_reg.add_argument("--action-id", default="")
    p_dbg_reg.add_argument("--actor-id", default="")
    p_dbg_reg.add_argument("--started-at", default="")
    p_dbg_reg.add_argument("--task-prompt-path", default="")
    p_dbg_reg.add_argument("--task-prompt", default="")
    p_dbg_reg.add_argument("--dispatch-nonce", default="")
    p_dbg_reg.add_argument("--if-enabled", action="store_true")
    p_dbg_reg.add_argument("--resumed-from", default="", help="Host-reported previous external session id (resume lineage)")
    p_dbg_reg.add_argument("--host-reported-resumed-from", default="", dest="host_reported_resumed_from")

    p_dbg_patch = p_dbg_sub.add_parser("patch-child-session", help="Set child session id from Task output")
    p_dbg_patch.add_argument("--project", type=Path, default=Path.cwd())
    p_dbg_patch.add_argument("--child-session-id", required=True)
    p_dbg_patch.add_argument("--parent-session-id", default="")
    p_dbg_patch.add_argument("--action-id", default="")
    p_dbg_patch.add_argument("--registration-id", default="")
    p_dbg_patch.add_argument("--dispatch-nonce", default="")
    p_dbg_patch.add_argument("--resumed-from", default="", help="Host-reported previous external session id")
    p_dbg_patch.add_argument("--host-reported-resumed-from", default="", dest="host_reported_resumed_from")
    p_dbg_patch.add_argument("--task-result", default="")

    p_dbg_ev = p_dbg_sub.add_parser("record-tool-event", help="Record a tool call for debug audit")
    p_dbg_ev.add_argument("--project", type=Path, default=Path.cwd())
    p_dbg_ev.add_argument("--tool", required=True)
    p_dbg_ev.add_argument("--parent-session-id", default="")
    p_dbg_ev.add_argument("--child-session-id", default="")
    p_dbg_ev.add_argument(
        "--event-session-id",
        default="",
        help="Executing session id from the hook (used for ownership + backfill)",
    )
    p_dbg_ev.add_argument("--action-id", default="")
    p_dbg_ev.add_argument("--actor-id", default="")
    p_dbg_ev.add_argument("--path", default="")
    p_dbg_ev.add_argument("--pattern", default="")
    p_dbg_ev.add_argument("--failed", action="store_true")
    p_dbg_ev.add_argument("--if-enabled", action="store_true")

    p_dbg_cex = p_dbg_sub.add_parser("export-child-session", help="Export registered child debug bundle")
    p_dbg_cex.add_argument("--project", type=Path, default=Path.cwd())
    p_dbg_cex.add_argument("--child-session-id", required=True)
    p_dbg_cex.add_argument("--reason", default="manual")
    p_dbg_cex.add_argument("--subagent", default="")
    p_dbg_cex.add_argument(
        "--if-enabled",
        action="store_true",
        help="No-op unless debug mode is enabled",
    )

    p_dbg_anom = p_dbg_sub.add_parser("record-anomaly", help="Append a debug anomaly (export failures etc.)")
    p_dbg_anom.add_argument("--project", type=Path, default=Path.cwd())
    p_dbg_anom.add_argument("--kind", required=True)
    p_dbg_anom.add_argument("--summary", required=True)

    p_dbg_fin = p_dbg_sub.add_parser(
        "finalize-parent-index",
        help="Write parent_session_summary.yaml + children_index.yaml",
    )
    p_dbg_fin.add_argument("--project", type=Path, default=Path.cwd())
    p_dbg_fin.add_argument("--parent-session-id", default="")
    p_dbg_fin.add_argument("--if-enabled", action="store_true")

    args = parser.parse_args(argv)

    if args.cmd == "doctor":
        return _doctor(args.project)
    if args.cmd == "validate-key-gates":
        from ascendc_pilot.gates import run_key_gates

        payload = run_key_gates(args.project, op_name=args.op_name or None)
        print_json(payload)
        return 0 if payload.get("ok") else 1
    if args.cmd == "validate":
        from ascendc_pilot.gates import run_key_gates, run_workflow_gates

        key_payload = run_key_gates(args.project)
        wf = run_workflow_gates(args.project)
        out = {"key_gates": key_payload, "workflow_gates": wf, "ok": bool(key_payload.get("ok") and wf.get("ok"))}
        print_json(out)
        return 0 if out["ok"] else 1
    if args.cmd == "route":
        from ascendc_pilot.router import route

        result = route(" ".join(args.text))
        print_json(result)
        return 0 if result.get("ok") else 2
    if args.cmd == "status":
        from ascendc_pilot.state import load_state
        from ascendc_pilot.todo import attach_todo

        st = load_state(args.project)
        print_json(attach_todo(st or {}, args.project, state=st or None))
        return 0
    if args.cmd == "next":
        from ascendc_pilot.state import describe_next

        result = describe_next(args.project)
        print_json(result)
        return 0 if result.get("ok") else 1
    if args.cmd == "context":
        from ascendc_pilot.context import build_context_pack

        pack = build_context_pack(args.project, intent=args.intent, topic=args.topic)
        print_json(pack)
        return 0
    if args.cmd == "run-summary":
        from ascendc_pilot.run_resume import existing_run_decision_payload, needs_resume_decision

        if not needs_resume_decision(args.project, args.workflow):
            print_json(
                {
                    "ok": True,
                    "needs_human_decision": False,
                    "message_zh": "无未完成 run / UO 残留；可直接 acp start",
                }
            )
            return 0
        payload = existing_run_decision_payload(args.project, args.workflow)
        print_json(payload)
        return 2
    if args.cmd == "start":
        from ascendc_pilot.run_resume import (
            apply_resume_decision,
            existing_run_decision_payload,
            needs_resume_decision,
            normalize_decision,
        )
        from ascendc_pilot.state import start_workflow
        from ascendc_pilot.workflows import get_workflow

        get_workflow(args.workflow_id)  # validate
        start_kwargs = {
            "intent": getattr(args, "intent", "") or "",
            "op_name": getattr(args, "op_name", "") or "",
            "architecture": getattr(args, "architecture", "") or "",
            "test_script_root": (
                str(args.test_script_root.resolve())
                if getattr(args, "test_script_root", None)
                else ""
            ),
            "csv_consumer_root": (
                str(args.csv_consumer_root.resolve())
                if getattr(args, "csv_consumer_root", None)
                else ""
            ),
            "level": getattr(args, "level", "") or "",
            "focus": getattr(args, "focus", "") or "",
        }
        decision = normalize_decision(getattr(args, "decision", "") or "")
        # --force-new alone ⇒ reinit (script escape). Skill path must AskQuestion first.
        if args.force_new and not decision:
            decision = "reinit"

        if decision:
            result = apply_resume_decision(
                args.project,
                args.workflow_id,
                decision,
                start_kwargs=start_kwargs,
            )
            if result.get("ok") and result.get("decision") == "reinit":
                try:
                    from ascendc_pilot.paths import context_root
                    import yaml

                    params = {
                        "op_name": result.get("op_name") or start_kwargs.get("op_name") or "",
                        "architecture": result.get("architecture")
                        or start_kwargs.get("architecture")
                        or "arch35",
                        "test_script_root": result.get("test_script_root") or "",
                        "csv_consumer_root": result.get("csv_consumer_root") or "",
                        "level": result.get("level") or "L0",
                        "focus": result.get("focus") or "",
                    }
                    out = context_root(args.project) / "pilot_params.yaml"
                    out.parent.mkdir(parents=True, exist_ok=True)
                    out.write_text(
                        yaml.safe_dump(params, allow_unicode=True, sort_keys=False),
                        encoding="utf-8",
                    )
                except Exception:  # noqa: BLE001
                    pass
            print_json(result)
            return 0 if result.get("ok") else 1

        if needs_resume_decision(args.project, args.workflow_id):
            payload = existing_run_decision_payload(args.project, args.workflow_id)
            print_json(payload)
            return 2

        state = start_workflow(args.project, args.workflow_id, **start_kwargs)
        # Persist acp params for subsequent context packs / engines.
        try:
            from ascendc_pilot.paths import context_root
            import yaml

            params = {
                "op_name": state.get("op_name") or "",
                "architecture": state.get("architecture") or "arch35",
                "test_script_root": state.get("test_script_root") or "",
                "csv_consumer_root": state.get("csv_consumer_root") or "",
                "level": state.get("level") or "L0",
                "focus": state.get("focus") or "",
            }
            out = context_root(args.project) / "pilot_params.yaml"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(yaml.safe_dump(params, allow_unicode=True, sort_keys=False), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
        print_json(state)
        return 0
    if args.cmd == "run-action":
        from ascendc_pilot.actions import run_action

        applied = _apply_run_action_limit_flags(args)
        result = run_action(args.project, args.action_id, finalize=bool(args.finalize))
        if applied:
            result = dict(result)
            result["pilot_params_updated"] = applied
        print_json(result, default=str)
        return 0 if result.get("ok") else 1
    if args.cmd == "advance":
        from ascendc_pilot.state import advance_phase

        result = advance_phase(args.project, args.next_phase)
        print_json(result)
        return 0 if result.get("ok") else 1
    if args.cmd == "rework":
        from ascendc_pilot.state import rework_phase

        result = rework_phase(args.project, to=args.to or None, reason_code=args.reason)
        print_json(result)
        return 0 if result.get("ok") else 1
    if args.cmd == "complete":
        from ascendc_pilot.state import complete_workflow

        result = complete_workflow(args.project, reason=args.reason)
        print_json(result)
        return 0 if result.get("ok") else 1
    if args.cmd == "block":
        from ascendc_pilot.state import mark_terminal

        state = mark_terminal(args.project, args.status, reason=args.reason)
        print_json(state)
        return 0
    if args.cmd == "inspect-failure":
        from ascendc_pilot.observation import render_failure_card
        from ascendc_pilot.state import load_state

        st = load_state(args.project) or {}
        lf = st.get("last_failure")
        card = st.get("failure_card") or (render_failure_card(st) if lf else "")
        payload = {
            "ok": True,
            "status": st.get("status"),
            "phase": st.get("phase"),
            "last_failure": lf,
            "last_observation_id": st.get("last_observation_id"),
            "failure_card": card,
            "legal_actions": (lf or {}).get("legal_recovery_actions")
            if isinstance(lf, dict)
            else [],
        }
        print_json(payload)
        return 0
    if args.cmd == "inspect":
        return _cmd_inspect(args)
    if args.cmd == "ro-search":
        return _cmd_ro_search(args)
    if args.cmd == "retry-after-environment-fix":
        from ascendc_pilot.authorize.lease import issue_lease_for_status
        from ascendc_pilot.runs import append_event
        from ascendc_pilot.state import load_state, save_state

        st = load_state(args.project)
        if not st:
            print_json({"ok": False, "error": "no_active_workflow"})
            return 1
        if st.get("status") not in {"human_required", "blocked"}:
            print_json(
                {
                    "ok": False,
                    "error": "not_human_required",
                    "status": st.get("status"),
                    "message_zh": "仅 human_required/blocked 可在环境修复后重试；rework_required 请直接按 acp next 的 retry_command 重试",
                }
            )
            return 1
        lf = dict(st.get("last_failure") or {})
        action_id = str(lf.get("action_id") or "")
        st["status"] = "rework_required"
        st["retry_budget"] = max(1, int(st.get("retry_budget") or 0))
        save_state(args.project, st)
        issue_lease_for_status(args.project, state=st, action_id=action_id)
        append_event(
            args.project,
            {
                "type": "StateTransitioned",
                "from_status": "human_required",
                "to_status": "rework_required",
                "reason": "retry_after_environment_fix",
            },
        )
        print_json(
            {
                "ok": True,
                "status": "rework_required",
                "action_id": action_id,
                "message_zh": "已恢复为 rework_required；请按 acp next 的 rework_targets 重试",
            }
        )
        return 0
    if args.cmd == "abort":
        from ascendc_pilot.authorize.lease import issue_lease_for_status, revoke_active_lease
        from ascendc_pilot.state import load_state, mark_terminal

        revoke_active_lease(args.project, reason="abort")
        st = mark_terminal(args.project, "failed", reason=args.reason or "aborted_by_operator")
        issue_lease_for_status(args.project, state=st, action_id=str((st.get("last_failure") or {}).get("action_id") or ""))
        print_json(
            {
                "ok": True,
                "status": st.get("status"),
                "state": st,
                "message_zh": "已 abort；可用 acp start --force-new 开启新 run",
            }
        )
        return 0
    if args.cmd == "spec-hashes":
        from ascendc_pilot.spec_hashes import all_spec_hashes

        # Resolve repo root: prefer cwd containing engines/, else parents of acp package
        repo = args.project
        if not (repo / "engines" / "understand-operator").is_dir():
            here = Path(__file__).resolve().parents[2]
            if (here / "engines" / "understand-operator").is_dir():
                repo = here
        print_json(all_spec_hashes(repo, workflow_id=args.workflow or None))
        return 0
    if args.cmd == "emit-confidence-report":
        from ascendc_pilot.paths import uo_root

        uo = uo_root(args.project, args.op_name or None)
        return print_json({"ok": False, "error": "legacy_command_removed"}) or 2

        payload = check_final_confidence(
            uo,
            write_report=not (args.no_write_report or args.no_skeleton),
            write_skeleton=False,
        )
        # Receipts are issued only via `acp run-action … --finalize`.
        print_json(payload, default=str)
        return 0 if payload.get("ok") or str(payload.get("status") or "") in {"pass", "reported"} else 1
    if args.cmd == "authorize":
        from ascendc_pilot.authorize import authorize

        verdict = authorize(
            args.project,
            tool=args.tool,
            command=args.command,
            path=args.path,
            agent=args.agent,
            action=args.action,
            lease_id=getattr(args, "lease_id", "") or "",
        )
        print_json(verdict)
        if verdict.get("decision") == "allow" or verdict.get("ok"):
            return 0
        if verdict.get("decision") == "ask":
            return 2
        return 1
    if args.cmd == "uo-scope":
        from ascendc_pilot.uo_scope import print_result, run_uo_scope

        payload = run_uo_scope(
            args.project,
            args.step,
            op_name=args.op_name or "",
            architecture=args.architecture or "arch35",
            decision=args.decision or "",
            notes=args.notes or "",
        )
        return print_result(payload)
    if args.cmd == "uo-query":
        from ascendc_pilot.paths import uo_root
        from uo_init.uo_query import open_query

        project = Path(args.project).resolve()
        uo = uo_root(project)
        if args.status_only:
            db = uo / "indexes" / "kb_graph.sqlite"
            print_json(
                {
                    "ok": db.is_file(),
                    "uo_root": uo.as_posix(),
                    "sqlite": db.as_posix() if db.is_file() else "",
                    "engine": "uo_init.uo_query",
                }
            )
            return 0 if db.is_file() else 1
        pattern = str(args.pattern or args.target or "").strip()
        mode = str(getattr(args, "mode", "search") or "search")
        if mode != "impact" and not pattern:
            print_json(
                {
                    "ok": False,
                    "error": "pattern_required",
                    "message_zh": "非 --status-only 时需要 --pattern（impact 模式用 --file/--line）",
                }
            )
            return 2
        try:
            q = open_query(uo)
            limit = int(args.limit or 50)
            if mode == "constraints":
                rows = q.constraints_for(pattern)
                payload = {"ok": True, "mode": mode, "pattern": pattern, "count": len(rows), "rows": rows[:limit]}
            elif mode == "neighbors":
                rows = q.neighbors(pattern, depth=int(args.depth or 1), limit=limit)
                payload = {"ok": True, "mode": mode, "pattern": pattern, "count": len(rows), "rows": rows}
            elif mode == "impact":
                f = str(getattr(args, "file", "") or pattern)
                line = int(getattr(args, "line", 0) or 0)
                line_end = int(getattr(args, "line_end", 0) or line or 0)
                if not f or not line:
                    print_json({"ok": False, "error": "impact_needs_file_line"})
                    return 2
                rows = q.impact_of(f, (line, line_end or line))
                payload = {
                    "ok": True,
                    "mode": mode,
                    "file": f,
                    "line": line,
                    "line_end": line_end or line,
                    "count": len(rows),
                    "rows": rows[:limit],
                }
            elif mode == "field":
                payload = q.field_impact(pattern)
                payload["mode"] = mode
            elif mode == "branches":
                rows = q.branches_for_key(pattern)
                payload = {"ok": True, "mode": mode, "pattern": pattern, "count": len(rows), "rows": rows[:limit]}
            elif mode == "templates":
                rows = q.templates_for_key(pattern)
                payload = {"ok": True, "mode": mode, "pattern": pattern, "count": len(rows), "rows": rows[:limit]}
            else:
                kinds = [k for k in str(getattr(args, "kind", "") or "").split(",") if k.strip()]
                rows = q.search(pattern, kinds=kinds, limit=limit)
                payload = {
                    "ok": True,
                    "mode": "search",
                    "pattern": pattern,
                    "kinds": kinds,
                    "count": len(rows),
                    "rows": rows,
                }
            payload["engine"] = "uo_init.uo_query"
            print_json(payload, default=str)
            return 0 if payload.get("ok") else 1
        except Exception as exc:  # noqa: BLE001
            print_json({"ok": False, "error": str(exc)[:300]})
            return 1
    if args.cmd == "uo":
        from ascendc_pilot.paths import uo_root
        from uo_init.uo_query import open_query

        project = Path(args.project).resolve()
        uo = uo_root(project)
        eid = str(args.entity_id or "")
        try:
            q = open_query(uo)
            if args.uo_cmd == "explain-host-value":
                result = {"ok": True, "entity_id": eid, "constraints": q.constraints_for(eid)}
            elif args.uo_cmd == "explain-tiling-field":
                result = q.field_impact(eid)
                result["entity_id"] = eid
            elif args.uo_cmd == "explain-key-dimension":
                result = {
                    "ok": True,
                    "entity_id": eid,
                    "branches": q.branches_for_key(eid) if hasattr(q, "branches_for_key") else [],
                    "templates": q.templates_for_key(eid) if hasattr(q, "templates_for_key") else [],
                }
            elif args.uo_cmd == "impact":
                f = str(getattr(args, "file", "") or "")
                line = int(getattr(args, "line", 0) or 0)
                line_end = int(getattr(args, "line_end", 0) or line or 0)
                if not f or not line:
                    result = {"ok": False, "error": "impact_needs_file_line"}
                else:
                    rows = q.impact_of(f, (line, line_end or line))
                    result = {
                        "ok": True,
                        "file": f,
                        "line": line,
                        "count": len(rows),
                        "rows": rows[: int(getattr(args, "limit", 50) or 50)],
                    }
            elif args.uo_cmd == "search":
                rows = q.search(eid, limit=int(getattr(args, "limit", 50) or 50))
                result = {"ok": True, "pattern": eid, "count": len(rows), "rows": rows}
            else:
                print_json({"ok": False, "error": f"未知 uo 子命令: {args.uo_cmd}"})
                return 2
        except Exception as exc:  # noqa: BLE001
            result = {"ok": False, "error": str(exc)[:300]}
        print_json(result, default=str)
        return 0 if result.get("ok") else 1
    if args.cmd == "debug":
        return _cmd_debug(args)
    return 2


def _cmd_debug(args: Any) -> int:
    from ascendc_pilot import debug as dbg

    sub = str(getattr(args, "debug_cmd", "") or "")
    if sub == "enable":
        payload = dbg.set_enabled(
            args.project,
            True,
            scope="global" if getattr(args, "global_scope", False) else "project",
            thought_char_limit=int(getattr(args, "thought_char_limit", 2500) or 2500),
            parent_session_id=str(getattr(args, "parent_session_id", "") or ""),
        )
        print_json(payload)
        return 0
    if sub == "disable":
        payload = dbg.set_enabled(
            args.project,
            False,
            scope="global" if getattr(args, "global_scope", False) else "project",
        )
        print_json(payload)
        return 0
    if sub == "status":
        cfg = dbg.load_config(args.project)
        anomalies = dbg.list_anomalies(args.project, limit=int(args.limit or 20))
        print_json({"ok": True, "config": cfg, "anomalies": anomalies, "count": len(anomalies)})
        return 0
    if sub == "export-session":
        if getattr(args, "if_enabled", False) and not dbg.is_enabled(args.project):
            print_json({"ok": True, "skipped": True, "reason": "debug_disabled"})
            return 0
        payload = dbg.export_session_bundle(
            args.project,
            reason=str(args.reason or "manual"),
            subagent=str(args.subagent or ""),
            session_id=str(args.session_id or ""),
            parent_session_id=str(getattr(args, "parent_session_id", "") or ""),
            transcript_hint=str(args.transcript or ""),
        )
        print_json(payload)
        return 0 if payload.get("ok") else 1
    if sub == "hook":
        raw = sys.stdin.read()
        try:
            payload = json.loads(raw) if raw.strip() else {}
        except Exception:  # noqa: BLE001
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        if "project_root" not in payload and getattr(args, "project", None):
            payload.setdefault("cwd", str(Path.cwd()))
        out = dbg.hook_handle(str(args.event), payload)
        print_json(out)
        return 0
    if sub == "record-tool-failure":
        payload = dbg.record_tool_failure(
            args.project,
            tool=str(args.tool),
            error=str(args.error),
            agent=str(args.agent or ""),
            action_id=str(args.action or ""),
            exit_code=getattr(args, "exit_code", None),
            require_real_failure=not bool(getattr(args, "force", False)),
        )
        print_json(payload)
        return 0 if payload.get("ok") or payload.get("skipped") else 1
    if sub == "register-child":
        # Control-plane identity always registers; --if-enabled is ignored for skip
        # (kept for CLI compat). Debug transcript mirror is best-effort inside register_child.
        payload = dbg.register_child(
            args.project,
            parent_session_id=str(args.parent_session_id),
            child_session_id=str(getattr(args, "child_session_id", "") or ""),
            workflow_id=str(getattr(args, "workflow_id", "") or ""),
            run_id=str(getattr(args, "run_id", "") or ""),
            phase=str(getattr(args, "phase", "") or ""),
            action_id=str(getattr(args, "action_id", "") or ""),
            actor_id=str(getattr(args, "actor_id", "") or ""),
            started_at=str(getattr(args, "started_at", "") or ""),
            task_prompt_path=str(getattr(args, "task_prompt_path", "") or ""),
            task_prompt_text=str(getattr(args, "task_prompt", "") or ""),
            dispatch_nonce=str(getattr(args, "dispatch_nonce", "") or ""),
            host_reported_resumed_from=str(getattr(args, "host_reported_resumed_from", "") or getattr(args, "resumed_from", "") or ""),
        )
        print_json(payload)
        return 0 if payload.get("ok") else 1
    if sub == "patch-child-session":
        payload = dbg.patch_child_session_id(
            args.project,
            child_session_id=str(args.child_session_id),
            parent_session_id=str(getattr(args, "parent_session_id", "") or ""),
            action_id=str(getattr(args, "action_id", "") or ""),
            registration_id=str(getattr(args, "registration_id", "") or ""),
            dispatch_nonce=str(getattr(args, "dispatch_nonce", "") or ""),
            task_result_text=str(getattr(args, "task_result", "") or ""),
            host_reported_resumed_from=str(getattr(args, "host_reported_resumed_from", "") or getattr(args, "resumed_from", "") or ""),
        )
        print_json(payload)
        return 0 if payload.get("ok") else 1
    if sub == "record-tool-event":
        if getattr(args, "if_enabled", False) and not dbg.is_enabled(args.project):
            print_json({"ok": True, "skipped": True, "reason": "debug_disabled"})
            return 0
        payload = dbg.record_tool_event(
            args.project,
            tool=str(args.tool),
            parent_session_id=str(getattr(args, "parent_session_id", "") or ""),
            child_session_id=str(getattr(args, "child_session_id", "") or ""),
            event_session_id=str(getattr(args, "event_session_id", "") or ""),
            action_id=str(getattr(args, "action_id", "") or ""),
            actor_id=str(getattr(args, "actor_id", "") or ""),
            path=str(getattr(args, "path", "") or ""),
            pattern=str(getattr(args, "pattern", "") or ""),
            failed=bool(getattr(args, "failed", False)),
            outcome="failure" if getattr(args, "failed", False) else "success",
        )
        print_json(payload)
        return 0 if payload.get("ok") or payload.get("skipped") else 1
    if sub == "export-child-session":
        if getattr(args, "if_enabled", False) and not dbg.is_enabled(args.project):
            print_json({"ok": True, "skipped": True, "reason": "debug_disabled"})
            return 0
        payload = dbg.export_child_session(
            args.project,
            child_session_id=str(args.child_session_id),
            reason=str(args.reason or "manual"),
            subagent=str(getattr(args, "subagent", "") or ""),
        )
        if not payload.get("ok") and not payload.get("skipped"):
            dbg.record_export_failure_anomaly(
                args.project,
                summary=str(payload.get("error") or payload.get("reason") or "export_failed"),
                detail=payload if isinstance(payload, dict) else {},
            )
        print_json(payload)
        return 0 if payload.get("ok") or payload.get("skipped") else 1
    if sub == "record-anomaly":
        payload = dbg.append_anomaly(
            args.project,
            kind=str(args.kind),
            summary=str(args.summary),
        )
        print_json(payload)
        return 0 if payload.get("ok") or payload.get("skipped") else 1
    if sub == "finalize-parent-index":
        if getattr(args, "if_enabled", False) and not dbg.is_enabled(args.project):
            print_json({"ok": True, "skipped": True, "reason": "debug_disabled"})
            return 0
        payload = dbg.finalize_parent_index(
            args.project,
            parent_session_id=str(getattr(args, "parent_session_id", "") or ""),
        )
        print_json(payload)
        return 0 if payload.get("ok") else 1
    if sub == "record-thought":
        text = str(args.text or "")
        if getattr(args, "stdin", False):
            text = sys.stdin.read()
        payload = dbg.record_long_thought(args.project, text, agent=str(args.agent or ""))
        print_json(payload)
        return 0
    print_json({"ok": False, "error": "unknown_debug_cmd", "debug_cmd": sub})
    return 2


def _cmd_inspect(args: Any) -> int:
    from collections import Counter

    from ascendc_pilot.uo_artifacts import read_yaml

    project = Path(args.project).resolve()
    uo = project / ".ascendc-pilot" / "uo"
    sub = str(getattr(args, "inspect_cmd", "") or "")
    if sub == "candidates":
        doc = read_yaml(uo / "ir" / "extract_plan_candidates.yaml") or {}
        kind = str(args.kind or "alias")
        key = {
            "writer": "writer_candidates",
            "receiver": "receiver_candidates",
            "alias": "alias_candidates",
            "receiver_binding": "receiver_binding_candidates",
        }.get(kind, "alias_candidates")
        rows = [r for r in (doc.get(key) or []) if isinstance(r, dict)]
        min_score = float(getattr(args, "min_score", 0.0) or 0.0)
        rows = [r for r in rows if float(r.get("score") or 0) >= min_score]
        limit = int(getattr(args, "limit", 50) or 50)
        print_json(
            {
                "ok": True,
                "kind": kind,
                "count": len(rows),
                "items": rows[:limit],
            },
            default=str,
        )
        return 0
    if sub == "tasks":
        doc = read_yaml(uo / "ir" / "llm_tasks.yaml") or {}
        rows = [t for t in (doc.get("tasks") or []) if isinstance(t, dict)]
        sev = str(getattr(args, "severity", "") or "").casefold()
        ot = str(getattr(args, "object_type", "") or "").casefold()
        if sev:
            rows = [t for t in rows if str(t.get("severity") or "").casefold() == sev]
        if ot:
            rows = [
                t
                for t in rows
                if str(t.get("object_type") or t.get("task_type") or "").casefold() == ot
            ]
        limit = int(getattr(args, "limit", 50) or 50)
        print_json(
            {
                "ok": True,
                "count": len(rows),
                "object_types": dict(
                    Counter(
                        str(t.get("object_type") or t.get("task_type") or "?") for t in rows
                    )
                ),
                "task_ids": [str(t.get("task_id")) for t in rows[:limit]],
            },
            default=str,
        )
        return 0
    if sub == "yaml":
        rel = str(getattr(args, "rel", "") or "").replace("\\", "/").lstrip("/")
        path = project / ".ascendc-pilot" / rel
        if not path.is_file():
            print_json({"ok": False, "error": "missing", "path": str(path)})
            return 1
        doc = read_yaml(path) or {}
        counts = {
            k: (len(v) if isinstance(v, list) else type(v).__name__)
            for k, v in (doc.items() if isinstance(doc, dict) else [])
        }
        print_json({"ok": True, "path": rel, "counts": counts}, default=str)
        return 0
    if sub == "duplicates":
        doc = read_yaml(uo / "ir" / "llm_tasks.yaml") or {}
        targets = [
            str(t.get("target") or t.get("target_id") or "")
            for t in (doc.get("tasks") or [])
            if isinstance(t, dict)
        ]
        c = Counter(targets)
        dups = {k: v for k, v in c.items() if k and v > 1}
        print_json({"ok": True, "duplicate_targets": dups, "count": len(dups)}, default=str)
        return 0
    if sub == "extract-plan-obligations":
        run_id = str(getattr(args, "run_id", "") or "").strip()
        obl = None
        snap = None
        if run_id:
            base = (
                project
                / ".ascendc-pilot"
                / "runs"
                / run_id
                / "actions"
                / "extract_plan"
                / "inputs"
            )
            if (base / "semantic_obligations.yaml").is_file():
                obl = read_yaml(base / "semantic_obligations.yaml")
            if (base / "extract_plan_snapshot.yaml").is_file():
                snap = read_yaml(base / "extract_plan_snapshot.yaml")
        print_json(
            {
                "ok": True,
                "snapshot": snap if isinstance(snap, dict) else {},
                "deterministic_count": (obl or {}).get("deterministic_count") if isinstance(obl, dict) else 0,
                "llm_required_count": (obl or {}).get("llm_required_count") if isinstance(obl, dict) else 0,
            },
            default=str,
        )
        return 0
    if sub == "extract-plan-relations":
        run_id = str(getattr(args, "run_id", "") or "").strip()
        graph = read_yaml(uo / "ir" / "semantic_relations.yaml")
        if not isinstance(graph, dict) and run_id:
            p = (
                project
                / ".ascendc-pilot"
                / "runs"
                / run_id
                / "actions"
                / "extract_plan"
                / "staging"
                / "semantic_relations.yaml"
            )
            if p.is_file():
                graph = read_yaml(p)
        graph = graph if isinstance(graph, dict) else {}
        print_json(
            {
                "ok": True,
                "relation_count": len(graph.get("relations") or []),
                "entity_count": len(graph.get("entities") or []),
                "unresolved_count": len(graph.get("unresolved") or []),
                "input_root_count": len(graph.get("input_roots") or []),
            },
            default=str,
        )
        return 0
    if sub == "validate":
        what = str(getattr(args, "what", "extract_plan") or "extract_plan")
        if what in {"extract_plan", "extract-plan-staging", "parts"}:
            return print_json({"ok": False, "error": "legacy_command_removed"}) or 2

            plan = read_yaml(uo / "ir" / "extract_plan.yaml") or {}
            errs = assert_canonical_plan_slim(plan if isinstance(plan, dict) else {})
            rel = read_yaml(uo / "ir" / "semantic_relations.yaml")
            if what != "parts" and not isinstance(rel, dict):
                errs.append("缺少 semantic_relations.yaml")
            run_id = str(getattr(args, "run_id", "") or "").strip()
            if what == "parts" and run_id:
                part_dir = (
                    project
                    / ".ascendc-pilot"
                    / "runs"
                    / run_id
                    / "actions"
                    / "extract_plan"
                    / "staging"
                    / "relation_parts"
                )
                if not part_dir.is_dir():
                    errs.append("缺少 staging/relation_parts")
            print_json({"ok": not errs, "errors": errs}, default=str)
            return 0 if not errs else 1
        print_json({"ok": False, "error": "unsupported_validate", "what": what})
        return 2
    print_json({"ok": False, "error": "unknown_inspect_cmd", "inspect_cmd": sub})
    return 2


def _cmd_ro_search(args: Any) -> int:
    """Readonly ripgrep-like search; forbids write redirects by never invoking a shell."""
    import re
    from pathlib import Path as P

    project = P(args.project).resolve()
    pattern = str(args.pattern or "")
    try:
        cre = re.compile(pattern)
    except re.error as exc:
        print_json({"ok": False, "error": "bad_pattern", "detail": str(exc)})
        return 2
    roots = [project / p for p in (args.paths or ["."])]
    hits: list[dict[str, Any]] = []
    limit = int(getattr(args, "limit", 50) or 50)
    suffixes = {".cpp", ".h", ".hpp", ".cc", ".c", ".py", ".yaml", ".yml"}
    for root in roots:
        if not root.exists():
            continue
        files = [root] if root.is_file() else list(root.rglob("*"))
        for fp in files:
            if not fp.is_file() or fp.suffix.casefold() not in suffixes:
                continue
            try:
                text = fp.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for i, line in enumerate(text.splitlines(), 1):
                if cre.search(line):
                    hits.append(
                        {
                            "file": str(fp.relative_to(project)).replace("\\", "/"),
                            "line": i,
                            "text": line[:240],
                        }
                    )
                    if len(hits) >= limit:
                        print_json({"ok": True, "hits": hits, "truncated": True}, default=str)
                        return 0
    print_json({"ok": True, "hits": hits, "truncated": False}, default=str)
    return 0


def _doctor(project: Path) -> int:
    issues: list[str] = []
    warnings: list[str] = []
    try:
        import yaml  # noqa: F401
    except ImportError:
        issues.append("PyYAML missing")
    try:
        import ascendc_pilot  # noqa: F401
    except ImportError:
        issues.append("ascendc_pilot not installed (pip install -e ./pilot)")
    try:
        import uo_init  # noqa: F401
    except ImportError:
        issues.append("uo_init engine not installed (pip install -e ./engines/understand-operator)")
    try:
        import testcase_agent  # noqa: F401
    except ImportError:
        issues.append("testcase_agent not installed (pip install -e ./engines/testcase-generation)")
    try:
        import code_engineering  # noqa: F401
    except ImportError:
        warnings.append(
            "code_engineering not installed (pip install -e ./engines/code-engineering)"
        )

    from ascendc_pilot.paths import AGENT_DIR, ensure_agent_layout

    root = ensure_agent_layout(project)
    print(f"agent_root={root}")
    print(f"canonical={AGENT_DIR}")

    # Composer / agent wiring (same success bar as install)
    try:
        import sys
        from pathlib import Path as _P

        repo = _P(__file__).resolve().parents[2]
        scripts = repo / "scripts"
        if scripts.is_dir() and str(scripts) not in sys.path:
            sys.path.insert(0, str(scripts))
        from compose_runtime import (
            check_generated_drift,
            validate,
            validate_generated,
        )

        src_errors = validate(repo)
        for err in src_errors:
            issues.append(f"compose: {err}")
        for host in ("opencode", "cursor", "codex"):
            gen_dir = repo / "generated" / host
            if not gen_dir.is_dir():
                warnings.append(
                    f"generated/{host} missing — run: "
                    f"python scripts/compose_runtime.py --repo . --host {host}"
                )
                continue
            gen_errors = validate_generated(repo, host=host)
            for err in gen_errors:
                issues.append(f"generated/{host}: {err}")
        drift = check_generated_drift(repo, hosts=["opencode", "cursor", "codex"])
        for err in drift:
            # Drift is a soft fail until install regenerates; still surface loudly.
            warnings.append(err)
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"compose validation skipped: {exc}")

    # Z3 solver (tg-solve)
    try:
        import z3  # noqa: F401
    except ImportError:
        warnings.append("z3 not installed; only explicit legacy-solver comparison is unavailable")

    # TG consumer root hint
    import os

    if not (
        os.environ.get("ASCENDC_TEST_SCRIPT_ROOT")
        or os.environ.get("ASCENDC_CSV_CONSUMER_ROOT")
    ):
        warnings.append(
            "ASCENDC_TEST_SCRIPT_ROOT / ASCENDC_CSV_CONSUMER_ROOT unset — "
            "/tg-init contract_build requires --test-script-root"
        )

    if warnings:
        print("WARNINGS:")
        for item in warnings:
            print(f"  - {item}")
    if issues:
        print("ISSUES:")
        for item in issues:
            print(f"  - {item}")
        return 1
    print("doctor_ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
