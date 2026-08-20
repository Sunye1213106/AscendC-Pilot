"""Pilot CLI (acp): doctor / validate / start / next / advance / run-action / ..."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from ascendc_pilot.io import configure_stdio, print_json

_UO_REMOVED_CMDS = frozenset(
    {
        "impact",
        "search",
        "explain-host-value",
        "explain-tiling-field",
        "explain-key-dimension",
        "locate",
        "query",
    }
)


def _uo_removed_payload(sub: str) -> dict[str, Any]:
    if sub == "query":
        return {
            "ok": False,
            "error": "use_uo_query",
            "message_zh": "acp uo query 不是合法命令。请使用: acp uo-query",
        }
    return {
        "ok": False,
        "error": "use_uo_query",
        "message_zh": (
            "已删除 acp uo impact / search / explain-* / locate。"
            "请使用 uo-query 四种形态：标识符、Dim=V、--file --line、无参数索引。"
        ),
    }


def _cli_project_default() -> Path:
    """Prefer remembered operator root over AscendC-Pilot checkout cwd."""
    from ascendc_pilot.intake import default_cli_project

    return default_cli_project()


_DIAGNOSTIC_CMDS = frozenset(
    {
        "scan-architectures",
        "status",
        "next",
        "inspect",
        "inspect-failure",
        "interpret-user-turn",
        "host-context",
    }
)


def _argv_has_explicit_project(argv: list[str] | None) -> bool:
    for tok in argv or []:
        if tok == "--project" or str(tok).startswith("--project="):
            return True
    return False


def _normalize_project_arg(args: argparse.Namespace, argv: list[str] | None = None) -> None:
    """Resolve args.project through intake defaults when present."""
    if not hasattr(args, "project"):
        return
    from ascendc_pilot.intake import default_cli_project

    raw = getattr(args, "project", None)
    wf = str(getattr(args, "workflow_id", None) or getattr(args, "workflow", "") or "").strip()
    action_id = str(getattr(args, "action_id", "") or "").strip()
    allow_last = wf not in {"auto", "goal-intake"} and action_id not in {"auto", "drive"}
    cmd = str(getattr(args, "cmd", "") or "").strip()
    if cmd in _DIAGNOSTIC_CMDS and not _argv_has_explicit_project(argv):
        allow_last = False
    intent = str(getattr(args, "intent", "") or "").strip()
    if allow_last and intent:
        try:
            from ascendc_pilot.intake import extract_pr_url_from_intent

            if extract_pr_url_from_intent(intent):
                allow_last = False
        except Exception:  # noqa: BLE001
            pass
    args.project = default_cli_project(raw, allow_last_project=allow_last)


def _adopt_prep_project(args: argparse.Namespace, prep: dict[str, Any]) -> None:
    pinned = str(prep.get("project") or "").strip()
    if pinned:
        args.project = Path(pinned).expanduser()


def _active_goal_resume_payload(project: Path | str) -> dict[str, Any] | None:
    """Return skip-start payload when user_goal is active on this operator workdir."""
    from ascendc_pilot.user_goal import drive_progress_for_status

    hint = drive_progress_for_status(project)
    nxt = str(hint.get("task_plan_current_workflow_id") or "").strip()
    st = hint.get("user_goal") if isinstance(hint.get("user_goal"), dict) else {}
    if str(st.get("status") or "") != "active" or nxt in {"", "auto", "goal-intake"}:
        return None
    pin = str(st.get("project") or project)
    return {
        "ok": True,
        "resumed_goal": True,
        "skip_start": True,
        "resumed": True,
        "workflow_id": nxt,
        "project": pin,
        "architecture": str(st.get("architecture") or ""),
        "user_goal": st,
        "task_plan_current_workflow_id": nxt,
        "status": "running",
        "message_zh": f"目标进行中，继续 {nxt}",
    }


def _apply_run_action_limit_flags(args: argparse.Namespace) -> dict[str, Any]:
    """Apply --set flags (legacy extract limit knobs retired; --set is a no-op skip)."""
    sets = list(getattr(args, "set", None) or [])
    if not sets:
        return {}
    return {"ok": True, "skipped": True, "reason": "extract_limits_not_applicable"}


def main(argv: list[str] | None = None) -> int:
    configure_stdio()
    raw = list(argv if argv is not None else sys.argv[1:])
    if raw[:1] == ["uo"] and len(raw) >= 2 and not str(raw[1]).startswith("-"):
        sub = str(raw[1])
        if sub in _UO_REMOVED_CMDS:
            print_json(_uo_removed_payload(sub))
            return 2
    parser = argparse.ArgumentParser(prog="acp", description="AscendC-Pilot")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_doctor = sub.add_parser("doctor", help="Environment precheck")
    p_doctor.add_argument("--project", type=Path, default=None)
    p_doctor.add_argument(
        "--host",
        default="",
        help="Also check Host adapter contract (e.g. opencode)",
    )

    p_validate = sub.add_parser("validate", help="Run all gates for the active workflow")
    p_validate.add_argument("--project", type=Path, default=None)

    p_route = sub.add_parser("route", help="Route natural language / slash to workflow")
    p_route.add_argument("text", nargs="+")

    p_status = sub.add_parser("status", help="Show workflow state")
    p_status.add_argument("--project", type=Path, default=None)

    p_next = sub.add_parser("next", help="Show next allowed actions / obligations")
    p_next.add_argument("--project", type=Path, default=None)

    p_host = sub.add_parser(
        "host-context",
        help="Resolve arch-scoped Host adapter context (OpenCode plugin authority)",
    )
    p_host.add_argument("--project", type=Path, default=None)
    p_host.add_argument(
        "--architecture",
        default="",
        help="Optional architecture pin; omit to discover from env / sole active state",
    )

    p_scan_arch = sub.add_parser(
        "scan-architectures",
        help="Fast scan op_host/op_kernel layout + arch* options (no repo archaeology)",
    )
    p_scan_arch.add_argument(
        "--project",
        type=Path,
        default=None,
        help="Operator package root (op_host/op_kernel). Required.",
    )

    p_ctx = sub.add_parser("context", help="Build context pack")
    p_ctx.add_argument("--project", type=Path, default=None)
    p_ctx.add_argument("--intent", required=True)
    p_ctx.add_argument("--topic", default="")

    p_start = sub.add_parser("start", help="Start workflow at entry_state (idempotent if same workflow active)")
    p_start.add_argument("workflow_id")
    p_start.add_argument(
        "--project",
        type=Path,
        default=None,
        help="Operator package root (op_host/op_kernel). Required; never the AscendC-Pilot checkout.",
    )
    p_start.add_argument("--intent", default="", help="e.g. diff_only for uo-update")
    p_start.add_argument("--force-new", action="store_true", help="Wipe an existing run and start fresh; no-op on a virgin project. Do not use on first start.")
    p_start.add_argument(
        "--decision",
        default="",
        help="Human AskQuestion decision for existing run: continue | reinit",
    )
    p_start.add_argument("--op-name", default="", help="Operator name for UO/TG engines")
    p_start.add_argument(
        "--architecture",
        default="",
        help=(
            "Target architecture (required for workflows declared in Spec "
            "requires_architecture; no silent default)"
        ),
    )
    p_start.add_argument("--test-script-root", type=Path, default=None, help="Test script root")
    p_start.add_argument("--level", default="", help="TG plan/solve level (default L0)")
    p_start.add_argument("--focus", default="", help="TG plan focus")

    p_run_sum = sub.add_parser("run-summary", help="Summarize interrupted uo-init run for AskQuestion")
    p_run_sum.add_argument("--project", type=Path, default=None)
    p_run_sum.add_argument("--workflow", default="uo-init")

    p_run = sub.add_parser("run-action", help="Prepare or finalize a workflow Action (sole execution entry)")
    p_run.add_argument("action_id")
    p_run.add_argument("--project", type=Path, default=None)
    p_run.add_argument(
        "--finalize",
        action="store_true",
        help="Finalize prepared action: check contract/gates and issue signed receipt",
    )
    p_run.add_argument(
        "--result-file",
        type=Path,
        default=None,
        help="Optional Host payload path for finalize (not a kb-answer disk contract)",
    )

    p_dres = sub.add_parser(
        "dispatch-result",
        help="Host Session Driver: consume dispatch ticket, finalize, continue drive",
    )
    p_dres.add_argument("--project", type=Path, default=None)
    p_dres.add_argument("--ticket", required=True, help="dispatch_ticket id from host_step")
    p_dres.add_argument("--result-file", type=Path, default=None)
    p_dres.add_argument(
        "--result-text",
        default="",
        help="Inline kb-answer-v1 / action result YAML (or fenced) from subagent return",
    )
    p_dres.add_argument(
        "--slice-id",
        default="",
        help="Fan-out slice id (harness/bind or spec/standards). Count-complete ACK; order/parallelism do not matter.",
    )
    p_run.add_argument(
        "--intent",
        default="",
        help="This-turn PASS/REWORK intent. Does not overwrite product intent.",
    )
    p_run.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Deprecated no-op (extract-limit knobs retired; ignored).",
    )

    p_adv = sub.add_parser("advance", help="Advance phase only if phase_gates pass")
    p_adv.add_argument("next_phase")
    p_adv.add_argument("--project", type=Path, default=None)

    p_rework = sub.add_parser("rework", help="Follow an explicit rework edge")
    p_rework.add_argument("--project", type=Path, default=None)
    p_rework.add_argument("--reason", default="", help="reason_code for selecting rework edge")
    p_rework.add_argument("--to", default="", help="optional explicit destination phase")

    p_done = sub.add_parser("complete", help="Mark workflow passed only if all gates succeed")
    p_done.add_argument("--project", type=Path, default=None)
    p_done.add_argument("--reason", default="")

    p_block = sub.add_parser("block", help="Mark workflow blocked/failed/human_required")
    p_block.add_argument("status", choices=["blocked", "failed", "human_required", "human"])
    p_block.add_argument("--project", type=Path, default=None)
    p_block.add_argument("--reason", default="")

    p_inspect = sub.add_parser("inspect-failure", help="Show structured last_failure / failure card")
    p_inspect.add_argument("--project", type=Path, default=None)

    p_ir = sub.add_parser(
        "inspect",
        help="Structured IR query (tasks/yaml/duplicates/evidence-window)",
    )
    p_ir_sub = p_ir.add_subparsers(dest="inspect_cmd", required=True)
    p_ir_t = p_ir_sub.add_parser("tasks", help="Summarize llm_tasks")
    p_ir_t.add_argument("--project", type=Path, default=None)
    p_ir_t.add_argument("--severity", default="")
    p_ir_t.add_argument("--object-type", default="")
    p_ir_t.add_argument("--limit", type=int, default=50)
    p_ir_y = p_ir_sub.add_parser("yaml", help="Count top-level keys / list lengths in a YAML IR file")
    p_ir_y.add_argument("--project", type=Path, default=None)
    p_ir_y.add_argument("--rel", required=True, help="Path relative to .ascendc-pilot/")
    p_ir_d = p_ir_sub.add_parser("duplicates", help="Find duplicate llm_tasks targets")
    p_ir_d.add_argument("--project", type=Path, default=None)
    p_ir_ew = p_ir_sub.add_parser(
        "evidence-window",
        help="Compute pad=0 disk window sha256 + snippet for high-confidence evidence",
    )
    p_ir_ew.add_argument("--project", type=Path, default=None)
    p_ir_ew.add_argument(
        "--path",
        required=True,
        help="Source path relative to operator project (e.g. op_host/arch35/foo.cpp)",
    )
    p_ir_ew.add_argument(
        "--lines",
        required=True,
        help="1-based inclusive range A-B (or single line A)",
    )
    p_ir_ew.add_argument("--max-lines", type=int, default=400)

    p_ro = sub.add_parser(
        "ro-search",
        help="Readonly source search wrapper (no shell redirects)",
    )
    p_ro.add_argument("--project", type=Path, default=None)
    p_ro.add_argument("--pattern", required=True)
    p_ro.add_argument(
        "--scope",
        default="run-source-scope",
        choices=["run-source-scope"],
        help="Mandatory bounded scope (ScopeSet ∩ lease source roots)",
    )
    p_ro.add_argument("--paths", nargs="*", default=None, help="Optional extra relative paths, still intersected with --scope")
    p_ro.add_argument("--glob", default="*.{cpp,h,hpp,cc}", dest="file_glob")
    p_ro.add_argument("--limit", type=int, default=50)

    p_retry_env = sub.add_parser(
        "retry-after-environment-fix",
        help="After human_required environment fix, restore rework_required for failed action",
    )
    p_retry_env.add_argument("--project", type=Path, default=None)

    p_abort = sub.add_parser("abort", help="Abort current run (mark failed)")
    p_abort.add_argument("--project", type=Path, default=None)
    p_abort.add_argument("--architecture", default="")
    p_abort.add_argument("--reason", default="aborted_by_operator")

    p_answer = sub.add_parser(
        "answer",
        help="Record a Host question UI answer as a signed HumanDecisionReceipt",
    )
    p_answer.add_argument("--project", type=Path, default=None)
    p_answer.add_argument("--request-id", required=True, help="request_id from human_interaction_request")
    p_answer.add_argument("--value", required=True, help="Selected option value")

    p_interpret = sub.add_parser(
        "interpret-user-turn",
        help="Map the latest user message onto a pending AskQuestion, adopt a new external test-script path, or supersede",
    )
    p_interpret.add_argument("--project", type=Path, default=None)
    p_interpret.add_argument(
        "--text",
        default="",
        help="Latest user message. Empty text supersedes (user interrupted).",
    )
    p_interpret.add_argument(
        "--message",
        default="",
        dest="message_alias",
        help="Deprecated alias of --text. Do not guess this flag; use --text.",
    )
    p_interpret.add_argument(
        "--reason",
        default="user_message",
        help="Why this turn is being interpreted (user_message / ask_ui_interrupted)",
    )

    p_hashes = sub.add_parser("spec-hashes", help="Print four Spec Hash digests")
    p_hashes.add_argument("--project", type=Path, default=None)
    p_hashes.add_argument("--workflow", default="")

    p_auth = sub.add_parser("authorize", help="Authorize tool call (OpenCode plugin hook)")
    p_auth.add_argument("--project", type=Path, default=None)
    p_auth.add_argument("--tool", required=True)
    p_auth.add_argument("--command", default="")
    p_auth.add_argument("--path", default="")
    p_auth.add_argument("--agent", default="")
    p_auth.add_argument("--action", default="")
    p_auth.add_argument("--lease-id", default="", help="Optional lease id (LEASE_REVOKED if stale)")
    p_auth.add_argument("--session-id", default="", help="OpenCode child session id (identity ticket)")

    p_serve_auth = sub.add_parser(
        "serve-authorize",
        help="Long-lived authorize daemon (stdio JSON-lines; Host Session Driver)",
    )
    p_serve_auth.add_argument(
        "--project",
        type=Path,
        default=None,
        help="Optional default project (requests may override)",
    )
    p_serve_auth.add_argument(
        "--ipc-dir",
        default="",
        help="Directory for *.req.json / *.resp.json sync IPC (OpenCode plugin)",
    )

    p_scope = sub.add_parser(
        "uo-scope",
        help="Run UO scope machine steps (scan / validate)",
    )
    p_scope.add_argument(
        "step",
        choices=[
            "scan",
            "validate",
        ],
        help="Deterministic scope step",
    )
    p_scope.add_argument("--project", type=Path, default=None)
    p_scope.add_argument("--op-name", default="")
    p_scope.add_argument("--architecture", default="")
    p_scope.add_argument("--notes", default="")

    p_uq = sub.add_parser(
        "uo-query",
        help="Query the arch-scoped .uo CodeMap product (no sqlite fallback)",
    )
    p_uq.add_argument("--project", type=Path, default=None)
    p_uq.add_argument("--op-name", default="")
    p_uq.add_argument(
        "tokens",
        nargs="*",
        default=[],
        help="Identifier, or Dim=V[,Other=V]. Omit for the operator index.",
    )
    p_uq.add_argument(
        "--pattern",
        default="",
        help="Identifier or Dim=V. Alias of the positional token.",
    )
    p_uq.add_argument(
        "--query",
        default="",
        help="Alias of --pattern",
    )
    p_uq.add_argument("--target", default="", help="Alias of --pattern")
    p_uq.add_argument(
        "--mode",
        default="",
        help="Removed. Do not pass --mode; dispatch follows the argument shape.",
    )
    p_uq.add_argument("--file", default="", help="Walk the graph from this source path")
    p_uq.add_argument("--line", type=int, default=0, help="Start line for --file")
    p_uq.add_argument("--line-end", type=int, default=0, help="End line (default=--line)")
    p_uq.add_argument("--kind", default="", help="search 时限定 node kind，逗号分隔")
    p_uq.add_argument("--depth", type=int, default=1)
    p_uq.add_argument("--limit", type=int, default=8)
    p_uq.add_argument("--relation-type", default="")
    p_uq.add_argument("--status-only", action="store_true")
    p_uq.add_argument(
        "--architecture",
        default="",
        help="Architecture pin for .uo product lookup (arch35, arch22, …)",
    )

    p_uo = sub.add_parser("uo", help="UO Host dump / product-handle（查询请用 uo-query）")
    p_uo_sub = p_uo.add_subparsers(dest="uo_cmd", required=True)
    p_uo_query_alias = p_uo_sub.add_parser(
        "query",
        help="已移除；请用 acp uo-query",
    )
    p_uo_query_alias.add_argument("rest", nargs="*", help=argparse.SUPPRESS)
    p_dump = p_uo_sub.add_parser("dump", help="从 .uo 按需导出 YAML view")
    p_dump.add_argument(
        "view",
        nargs="?",
        default="",
        help="view 名/别名：manifest, quality, tilingdata, kernel, …",
    )
    p_dump.add_argument("--project", type=Path, default=None)
    p_dump.add_argument("--op-name", default="")
    p_dump.add_argument("--architecture", default="")
    p_dump.add_argument("--out", type=Path, default=None, help="输出路径（省略则打印 YAML）")
    p_dump.add_argument("--list", action="store_true", help="列出 .uo 中可用 view")
    p_handle = p_uo_sub.add_parser(
        "product-handle",
        help="Emit UO Product Handle for Task(actor=uo-query) delegation",
    )
    p_handle.add_argument("--project", type=Path, default=None)
    p_handle.add_argument("--op-name", default="")
    p_handle.add_argument("--architecture", default="")
    p_handle.add_argument("--uo-path", type=Path, default=None)

    p_dbg = sub.add_parser(
        "debug",
        help="Debug mode: capture tool failures / long thoughts; export session bundles",
    )
    p_dbg_sub = p_dbg.add_subparsers(dest="debug_cmd", required=True)
    p_dbg_on = p_dbg_sub.add_parser("enable", help="Enable debug capture")
    p_dbg_on.add_argument("--project", type=Path, default=None)
    p_dbg_on.add_argument("--global", dest="global_scope", action="store_true")
    p_dbg_on.add_argument("--thought-char-limit", type=int, default=2500)
    p_dbg_on.add_argument("--parent-session-id", default="", help="Host session id (ses_…)")
    p_dbg_off = p_dbg_sub.add_parser("disable", help="Disable debug capture")
    p_dbg_off.add_argument("--project", type=Path, default=None)
    p_dbg_off.add_argument("--global", dest="global_scope", action="store_true")
    p_dbg_st = p_dbg_sub.add_parser("status", help="Show debug config + recent anomalies")
    p_dbg_st.add_argument("--project", type=Path, default=None)
    p_dbg_st.add_argument("--limit", type=int, default=20)
    p_dbg_exp = p_dbg_sub.add_parser("export-session", help="Export run + anomalies (+ transcript if found)")
    p_dbg_exp.add_argument("--project", type=Path, default=None)
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
    p_dbg_rec.add_argument("--project", type=Path, default=None)
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
    p_dbg_th.add_argument("--project", type=Path, default=None)
    p_dbg_th.add_argument("--agent", default="")
    p_dbg_th.add_argument("--text", default="")
    p_dbg_th.add_argument("--stdin", action="store_true")

    p_dbg_reg = p_dbg_sub.add_parser("register-child", help="Register a Task child (parent-scoped debug)")
    p_dbg_reg.add_argument("--project", type=Path, default=None)
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
    p_dbg_patch.add_argument("--project", type=Path, default=None)
    p_dbg_patch.add_argument("--child-session-id", required=True)
    p_dbg_patch.add_argument("--parent-session-id", default="")
    p_dbg_patch.add_argument("--action-id", default="")
    p_dbg_patch.add_argument("--registration-id", default="")
    p_dbg_patch.add_argument("--dispatch-nonce", default="")
    p_dbg_patch.add_argument("--resumed-from", default="", help="Host-reported previous external session id")
    p_dbg_patch.add_argument("--host-reported-resumed-from", default="", dest="host_reported_resumed_from")
    p_dbg_patch.add_argument("--task-result", default="")

    p_dbg_ev = p_dbg_sub.add_parser("record-tool-event", help="Record a tool call for debug audit")
    p_dbg_ev.add_argument("--project", type=Path, default=None)
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
    p_dbg_cex.add_argument("--project", type=Path, default=None)
    p_dbg_cex.add_argument("--child-session-id", required=True)
    p_dbg_cex.add_argument("--reason", default="manual")
    p_dbg_cex.add_argument("--subagent", default="")
    p_dbg_cex.add_argument(
        "--if-enabled",
        action="store_true",
        help="No-op unless debug mode is enabled",
    )

    p_dbg_anom = p_dbg_sub.add_parser("record-anomaly", help="Append a debug anomaly (export failures etc.)")
    p_dbg_anom.add_argument("--project", type=Path, default=None)
    p_dbg_anom.add_argument("--kind", required=True)
    p_dbg_anom.add_argument("--summary", required=True)

    p_dbg_fin = p_dbg_sub.add_parser(
        "finalize-parent-index",
        help="Write parent_session_summary.yaml + children_index.yaml",
    )
    p_dbg_fin.add_argument("--project", type=Path, default=None)
    p_dbg_fin.add_argument("--parent-session-id", default="")
    p_dbg_fin.add_argument("--if-enabled", action="store_true")

    args = parser.parse_args(argv)
    _normalize_project_arg(args, raw)

    if args.cmd == "doctor":
        code = _doctor(args.project)
        host = str(getattr(args, "host", "") or "").strip()
        if host:
            from ascendc_pilot.host_doctor import doctor_host

            payload = doctor_host(host, project=args.project)
            print_json(payload)
            if not payload.get("ok"):
                return 1
        return code
    if args.cmd == "validate":
        from ascendc_pilot.gates import run_workflow_gates

        wf = run_workflow_gates(args.project)
        print_json(wf)
        return 0 if wf.get("ok") else 1
    if args.cmd == "route":
        from ascendc_pilot.router import route

        result = route(" ".join(args.text))
        print_json(result)
        return 0 if result.get("ok") else 2
    if args.cmd == "status":
        from ascendc_pilot.state import load_state
        from ascendc_pilot.todo import attach_todo

        st = load_state(args.project)
        out = attach_todo(st or {}, args.project, state=st or None)
        try:
            from ascendc_pilot.occupancy import occupancy_status_payload

            out["occupancy"] = occupancy_status_payload(args.project)
        except Exception:  # noqa: BLE001
            pass
        try:
            from ascendc_pilot.user_goal import drive_progress_for_status

            hint = drive_progress_for_status(args.project)
            if hint:
                out = dict(out)
                out.update(hint)
        except Exception:  # noqa: BLE001
            pass
        print_json(out)
        return 0
    if args.cmd == "next":
        from ascendc_pilot.state import describe_next

        result = describe_next(args.project)
        print_json(result)
        return 0 if result.get("ok") else 1
    if args.cmd == "host-context":
        from ascendc_pilot.host_context import build_host_context

        result = build_host_context(
            args.project,
            architecture=str(getattr(args, "architecture", "") or ""),
        )
        print_json(result)
        return 0 if result.get("ok") else 1
    if args.cmd == "scan-architectures":
        from ascendc_pilot.intake import scan_operator_directory

        result = scan_operator_directory(args.project)
        print_json(result)
        return 0 if result.get("ok") else 1
    if args.cmd == "answer":
        from ascendc_pilot.human_interaction import record_answer

        try:
            result = record_answer(
                args.project,
                request_id=str(args.request_id or ""),
                value=str(args.value or ""),
            )
        except Exception as exc:  # noqa: BLE001
            print_json(
                {
                    "ok": False,
                    "error": type(exc).__name__,
                    "message": str(exc)[:800],
                    "message_zh": f"acp answer 失败：{exc}"[:400],
                }
            )
            return 1
        print_json(result)
        return 0 if result.get("ok") else 1
    if args.cmd == "interpret-user-turn":
        from ascendc_pilot.human_interaction import interpret_user_turn

        try:
            result = interpret_user_turn(
                args.project,
                text=str(getattr(args, "text", "") or getattr(args, "message_alias", "") or ""),
                reason=str(getattr(args, "reason", "") or "user_message"),
            )
        except Exception as exc:  # noqa: BLE001
            print_json(
                {
                    "ok": False,
                    "error": type(exc).__name__,
                    "message": str(exc)[:800],
                    "message_zh": f"acp interpret-user-turn 失败：{exc}"[:400],
                }
            )
            return 1
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
        from ascendc_pilot.intake import (
            architecture_from_env,
            prepare_workflow_start,
            write_last_project_cache,
        )
        from ascendc_pilot.run_resume import (
            apply_resume_decision,
            existing_run_decision_payload,
            needs_resume_decision,
            normalize_decision,
        )
        from ascendc_pilot.state import start_workflow
        from ascendc_pilot.workflows import get_workflow

        get_workflow(args.workflow_id)  # validate
        if str(args.workflow_id or "").strip() == "uo-query":
            print_json(
                {
                    "ok": False,
                    "error": "UO_QUERY_NOT_HOST_DRIVEN",
                    "reason_code": "UO_QUERY_NOT_HOST_DRIVEN",
                    "message_zh": (
                        "uo-query 不是 Host Session Driver 工作流。"
                        "请用 /uo-query 或 plugin `pilot_cli` 的 `uo-query`。"
                    ),
                }
            )
            return 1
        arch_cli = str(getattr(args, "architecture", "") or "").strip()
        arch = arch_cli or architecture_from_env()
        argv_list = list(argv if argv is not None else sys.argv[1:])
        project_explicit = any(
            a == "--project" or a.startswith("--project=") for a in argv_list
        )
        start_kwargs = {
            "intent": getattr(args, "intent", "") or "",
            "op_name": getattr(args, "op_name", "") or "",
            "architecture": arch,
            "test_script_root": (
                str(args.test_script_root.resolve())
                if getattr(args, "test_script_root", None)
                else ""
            ),
            "level": getattr(args, "level", "") or "",
            "focus": getattr(args, "focus", "") or "",
        }
        decision = normalize_decision(getattr(args, "decision", "") or "")
        # --force-new ⇒ reinit only when there is something to resume/wipe.
        # Virgin project: treat as a normal start so --architecture reaches
        # start_workflow (do not enter apply_resume_decision first).
        force_new = bool(getattr(args, "force_new", False))
        if force_new and not decision:
            if needs_resume_decision(args.project, args.workflow_id):
                decision = "reinit"

        if not decision:
            from ascendc_pilot.human_interaction import load_pending

            pending = load_pending(args.project)
            if str(pending.get("status") or "") == "answered":
                kind = str(pending.get("kind") or pending.get("decision_kind") or "")
                if kind in {"resume", "KIND_RESUME", ""}:
                    adopted = normalize_decision(str(pending.get("answered_value") or ""))
                    if adopted in {"continue", "reinit", "query"}:
                        decision = adopted

        from ascendc_pilot.human_interaction import consume_intake_architecture

        consume_intake_architecture(
            args.project, architecture=arch, force_new=force_new
        )

        if decision:
            if decision == "reinit":
                prep = prepare_workflow_start(
                    project=args.project,
                    workflow_id=args.workflow_id,
                    architecture=arch,
                    project_explicit=project_explicit,
                    intent=str(start_kwargs.get("intent") or ""),
                )
                if not prep.get("ok"):
                    print_json(prep)
                    return 2
                _adopt_prep_project(args, prep)
                arch = str(prep.get("architecture") or arch)
                start_kwargs["architecture"] = arch
            try:
                result = apply_resume_decision(
                    args.project,
                    args.workflow_id,
                    decision,
                    start_kwargs=start_kwargs,
                    require_receipt=not force_new,
                )
            except Exception as exc:  # noqa: BLE001
                print_json(
                    {
                        "ok": False,
                        "error": type(exc).__name__,
                        "message": str(exc)[:800],
                        "message_zh": f"acp start --decision 失败：{exc}"[:400],
                    }
                )
                return 1
            if result.get("ok") and result.get("decision") == "reinit":
                try:
                    from ascendc_pilot.paths import context_root
                    import yaml

                    params = {
                        "op_name": result.get("op_name") or start_kwargs.get("op_name") or "",
                        "architecture": result.get("architecture")
                        or start_kwargs.get("architecture")
                        or arch,
                        "test_script_root": result.get("test_script_root") or "",
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
            if result.get("ok"):
                write_last_project_cache(args.project)
            print_json(result)
            return 0 if result.get("ok") else 1

        if (
            not force_new
            and str(args.workflow_id or "").strip() in {"auto", "goal-intake"}
        ):
            try:
                resumed = _active_goal_resume_payload(args.project)
                if resumed:
                    print_json(resumed)
                    return 0
            except Exception:  # noqa: BLE001
                pass

        if needs_resume_decision(args.project, args.workflow_id):
            payload = existing_run_decision_payload(
                args.project, args.workflow_id, architecture=arch
            )
            print_json(payload)
            return 2

        prep = prepare_workflow_start(
            project=args.project,
            workflow_id=args.workflow_id,
            architecture=arch,
            project_explicit=project_explicit,
            intent=str(start_kwargs.get("intent") or ""),
        )
        if not prep.get("ok"):
            print_json(prep)
            return 2
        _adopt_prep_project(args, prep)
        if str(args.workflow_id or "").strip() not in {"auto", "goal-intake"}:
            arch = str(prep.get("architecture") or arch)
            start_kwargs["architecture"] = arch

        if (
            not force_new
            and str(args.workflow_id or "").strip() in {"auto", "goal-intake"}
        ):
            try:
                resumed = _active_goal_resume_payload(args.project)
                if resumed:
                    write_last_project_cache(args.project)
                    print_json(resumed)
                    return 0
            except Exception:  # noqa: BLE001
                pass

        try:
            state = start_workflow(args.project, args.workflow_id, **start_kwargs)
        except Exception as exc:  # noqa: BLE001
            print_json(
                {
                    "ok": False,
                    "error": type(exc).__name__,
                    "message": str(exc)[:800],
                    "message_zh": f"acp start 失败：{exc}"[:400],
                }
            )
            return 1
        write_last_project_cache(args.project)
        try:
            from ascendc_pilot.paths import context_root
            import yaml

            params = {
                "op_name": state.get("op_name") or "",
                "architecture": state.get("architecture") or arch,
                "test_script_root": state.get("test_script_root") or "",
                "level": state.get("level") or "L0",
                "focus": state.get("focus") or "",
            }
            out = context_root(args.project) / "pilot_params.yaml"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(yaml.safe_dump(params, allow_unicode=True, sort_keys=False), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
        try:
            from ascendc_pilot.public_progress import message_zh_for_host
            from ascendc_pilot.user_goal import load_user_goal, progress_line_zh

            goal = load_user_goal(args.project)
            if goal and isinstance(state, dict):
                state = dict(state)
                state["user_goal"] = goal
                line = progress_line_zh(goal) or message_zh_for_host(args.project, state=state)
                if line:
                    state["user_summary_zh"] = line
                    state["message_zh"] = line
        except Exception:  # noqa: BLE001
            pass
        if str(prep.get("resolved_from") or "") == "intent" and isinstance(state, dict):
            state = dict(state)
            echo = str(prep.get("message_zh") or f"按 {arch} 启动。").strip()
            prev = str(state.get("message_zh") or "").strip()
            state["architecture_resolved_from"] = "intent"
            state["message_zh"] = f"{echo} {prev}".strip() if echo not in prev else prev
        if isinstance(state, dict):
            state = dict(state)
            try:
                state["project"] = str(Path(args.project).expanduser().resolve())
            except OSError:
                state["project"] = str(args.project)
        print_json(state)
        return 0
    if args.cmd == "run-action":
        from ascendc_pilot.actions import run_action
        from ascendc_pilot.intake import assert_operator_if_required, write_last_project_cache

        # goal-intake also starts on the pinned operator package (empty Host cwd is not a control root).
        bad = assert_operator_if_required(args.project, action=str(args.action_id or ""))
        if bad is not None:
            bad["action_id"] = args.action_id
            print_json(bad)
            return 2

        applied = _apply_run_action_limit_flags(args)
        result = run_action(
            args.project,
            args.action_id,
            finalize=bool(args.finalize),
            result_file=getattr(args, "result_file", None),
            turn_intent=str(getattr(args, "intent", "") or ""),
        )
        if applied:
            result = dict(result)
            result["pilot_params_updated"] = applied
        if result.get("ok"):
            write_last_project_cache(args.project)
        print_json(result, default=str)
        return 0 if result.get("ok") else 1
    if args.cmd == "dispatch-result":
        from ascendc_pilot.actions.dispatch import dispatch_result
        from ascendc_pilot.intake import assert_operator_if_required, write_last_project_cache

        bad = assert_operator_if_required(args.project, action="dispatch-result")
        if bad is not None:
            print_json(bad)
            return 2
        result = dispatch_result(
            args.project,
            ticket_id=str(args.ticket or ""),
            result_file=getattr(args, "result_file", None),
            result_text=str(getattr(args, "result_text", "") or ""),
            slice_id=str(getattr(args, "slice_id", "") or ""),
        )
        if result.get("ok"):
            write_last_project_cache(args.project)
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
        message_zh = ""
        if isinstance(lf, dict):
            message_zh = str(lf.get("message_zh") or lf.get("message") or "").strip()
        if not message_zh and card:
            message_zh = str(card).splitlines()[0].strip()[:240]
        if not message_zh:
            message_zh = "当前没有失败记录。" if not lf else "工作流失败，详见 failure_card。"
        payload = {
            "ok": True,
            "message_zh": message_zh,
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
        from ascendc_pilot.human_interaction import KIND_HUMAN_REQUIRED, require_decision_receipt
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
                    "message_zh": "仅 human_required/blocked 可在环境修复后重试；rework_required 请直接按 inspect-failure 给出的 retry_command 重试",
                }
            )
            return 1
        receipt = require_decision_receipt(
            args.project,
            expected_values=["retry_after_environment_fix"],
            expected_kind=KIND_HUMAN_REQUIRED,
            consume=True,
        )
        if not receipt.get("ok"):
            print_json(receipt)
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
        from ascendc_pilot.authorize.lease import revoke_active_lease
        from ascendc_pilot.human_interaction import KIND_HUMAN_REQUIRED, require_decision_receipt
        from ascendc_pilot.state import mark_terminal, release_live_execution

        # When aborting from human_required AskQuestion, require the receipt.
        # Direct abort (no pending interaction) remains allowed for operators.
        from ascendc_pilot.human_interaction import pending_path

        try:
            if pending_path(args.project).is_file():
                from ascendc_pilot.human_interaction import load_pending, pending_is_open

                if pending_is_open(load_pending(args.project)):
                    receipt = require_decision_receipt(
                        args.project,
                        expected_values=["abort_run", "abort"],
                        expected_kind=KIND_HUMAN_REQUIRED,
                        consume=True,
                    )
                    if not receipt.get("ok"):
                        print_json(receipt)
                        return 1
            revoke_active_lease(args.project, reason="abort")
            st = mark_terminal(args.project, "failed", reason=args.reason or "aborted_by_operator")
            released = release_live_execution(
                args.project, reason="aborted_by_operator", state=st
            )
        except ValueError as exc:
            if "ARCHITECTURE_MISSING" in str(exc):
                print_json(
                    {
                        "ok": False,
                        "error": "ARCHITECTURE_MISSING_IN_RUN_STATE",
                        "reason_code": "ARCHITECTURE_MISSING_IN_RUN_STATE",
                        "message_zh": (
                            "abort 需要 --architecture，或已有 run state 中的 architecture。"
                            "不要猜测 arch。"
                        ),
                    }
                )
                return 2
            print_json(
                {
                    "ok": False,
                    "error": type(exc).__name__,
                    "message": str(exc)[:800],
                    "message_zh": f"abort 失败：{exc}"[:400],
                }
            )
            return 1
        print_json(
            {
                "ok": True,
                "status": "failed",
                "released_execution": released,
                "state": st,
                "message_zh": "已 abort 并释放本产物族锁；可直接 acp start 开启下一工作流",
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
            session_id=getattr(args, "session_id", "") or "",
        )
        print_json(verdict)
        if verdict.get("decision") == "allow" or verdict.get("ok"):
            return 0
        if verdict.get("decision") == "ask":
            return 2
        return 1
    if args.cmd == "serve-authorize":
        from ascendc_pilot.authorize.serve import serve_forever

        return serve_forever(ipc_dir=getattr(args, "ipc_dir", "") or None)
    if args.cmd == "uo-scope":
        from ascendc_pilot.uo_scope import print_result, run_uo_scope

        payload = run_uo_scope(
            args.project,
            args.step,
            op_name=args.op_name or "",
            architecture=args.architecture or "",
            notes=args.notes or "",
        )
        return print_result(payload)
    if args.cmd == "uo-query":
        from uo_init.store.reader import find_uo_product
        from uo_init.uo_query import open_query

        project = Path(args.project).resolve()
        op_name = str(getattr(args, "op_name", "") or "")
        architecture = str(getattr(args, "architecture", "") or "")
        tokens = [str(tok).strip() for tok in (getattr(args, "tokens", None) or []) if str(tok).strip()]
        pattern = str(
            args.pattern or args.target or getattr(args, "query", "") or " ".join(tokens) or ""
        ).strip()
        mode = str(getattr(args, "mode", "") or "")
        if mode:
            print_json(
                {
                    "ok": False,
                    "error": "mode_removed",
                    "message_zh": "已取消 --mode。按参数形态调用：标识符；Dim=V；--file --line；无参数索引。",
                    "hint": (
                        "acp uo-query --project <operator-abs> [--architecture arch] "
                        "[<identifier> | Dim=V[,Other=V] | --file PATH --line N]"
                    ),
                }
            )
            return 2
        product = find_uo_product(project, op_name=op_name, architecture=architecture)
        if product is None or product.suffix != ".uo":
            from ascendc_pilot.intake import missing_uo_product_payload

            payload = missing_uo_product_payload(
                root=project,
                workflow_id="uo-query",
                architecture=architecture,
                op_name=op_name,
                persist=not bool(args.status_only),
            )
            payload["product"] = ""
            payload["engine"] = "uo_init.uo_query"
            print_json(payload)
            return 1 if args.status_only else 2
        if args.status_only:
            print_json(
                {
                    "ok": True,
                    "product": product.as_posix(),
                    "engine": "uo_init.uo_query",
                }
            )
            return 0
        try:
            q = open_query(project, op_name=op_name, architecture=architecture)
            limit = int(args.limit or 8)
            payload = q.agent_query(
                pattern=pattern,
                file=str(getattr(args, "file", "") or ""),
                line=int(getattr(args, "line", 0) or 0),
                line_end=int(getattr(args, "line_end", 0) or 0),
                limit=limit,
            )
            payload["engine"] = "uo_init.uo_query"
            try:
                from ascendc_pilot.occupancy import (
                    apply_stale_confidence,
                    bind_session,
                    current_session_id,
                    get_session_binding,
                    pin_digest_from_product,
                )

                sid = current_session_id()
                pin = pin_digest_from_product(
                    project, architecture=architecture, op_name=op_name
                )
                if sid and not get_session_binding(project, sid):
                    bind_session(
                        project,
                        session_id=sid,
                        architecture=str(pin.get("architecture") or architecture),
                        uo_path=str(pin.get("path") or ""),
                        digest=str(pin.get("digest") or ""),
                        workflow_id="uo-query",
                        run_id="",
                        stale=False,
                    )
                payload = apply_stale_confidence(
                    payload,
                    project,
                    architecture=str(pin.get("architecture") or architecture),
                    session_id=sid,
                )
            except Exception:  # noqa: BLE001
                pass
            try:
                from ascendc_pilot.authorize.citations import record_from_payload

                record_from_payload(
                    project,
                    payload,
                    file=str(getattr(args, "file", "") or ""),
                    line=int(getattr(args, "line", 0) or 0),
                    arch=architecture or None,
                )
            except Exception:  # noqa: BLE001
                pass
            print_json(payload, default=str, compact=True)
            return 0 if payload.get("ok") else 1
        except Exception as exc:  # noqa: BLE001
            print_json({"ok": False, "error": str(exc)[:300]})
            return 1
    if args.cmd == "uo":
        if getattr(args, "uo_cmd", "") == "query":
            print_json(_uo_removed_payload("query"))
            return 2
        from uo_init.store.reader import find_uo_product, list_views

        project = Path(args.project).resolve()
        op_name = str(getattr(args, "op_name", "") or "")
        architecture = str(getattr(args, "architecture", "") or "")
        product = find_uo_product(project, op_name=op_name, architecture=architecture)
        if args.uo_cmd == "dump":
            from uo_init.dump import dump_view

            if getattr(args, "list", False):
                ok = product is not None and product.suffix == ".uo"
                print_json(
                    {
                        "ok": ok,
                        "product": product.as_posix() if ok else "",
                        "views": list_views(product) if ok else [],
                    }
                )
                return 0 if ok else 1
            if not str(getattr(args, "view", "") or "").strip():
                print_json({"ok": False, "error": "view_required"})
                return 2
            if product is None or product.suffix != ".uo":
                print_json(
                    {
                        "ok": False,
                        "error": "missing_uo_product",
                        "message_zh": "未找到 .ascendc-pilot/<arch>/uo/<op>.<arch>.uo，请先 /uo-init",
                    }
                )
                return 1
            try:
                result = dump_view(product, str(args.view), out=getattr(args, "out", None))
                if getattr(args, "out", None):
                    print_json({k: v for k, v in result.items() if k != "payload"})
                else:
                    import yaml

                    print(
                        yaml.safe_dump(
                            result.get("payload"),
                            allow_unicode=True,
                            sort_keys=True,
                            default_flow_style=False,
                        ),
                        end="",
                    )
                return 0
            except Exception as exc:  # noqa: BLE001
                print_json({"ok": False, "error": str(exc)[:300]})
                return 1
        if args.uo_cmd == "product-handle":
            from ascendc_pilot.uo_product_handle import (
                build_uo_product_handle,
                format_handle_for_task,
            )

            handle = build_uo_product_handle(
                project,
                op_name=str(getattr(args, "op_name", "") or ""),
                architecture=str(getattr(args, "architecture", "") or ""),
                uo_path=getattr(args, "uo_path", None),
            )
            handle["task_block"] = format_handle_for_task(handle)
            print_json(handle)
            return 0 if handle.get("ok") else 1

        print_json(_uo_removed_payload(str(args.uo_cmd or "")))
        return 2
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
    if sub == "evidence-window":
        from ascendc_pilot.evidence_window import disk_window_proof
        from ascendc_pilot.paths import resolve_operator_root

        try:
            project = resolve_operator_root(getattr(args, "project", None))
        except ValueError as exc:
            print_json({"ok": False, "error": "project_unresolved", "message": str(exc)})
            return 2
        out = disk_window_proof(
            project,
            path=str(getattr(args, "path", "") or ""),
            lines=str(getattr(args, "lines", "") or ""),
            max_lines=int(getattr(args, "max_lines", 400) or 400),
        )
        print_json(out, default=str)
        return 0 if out.get("ok") else 1
    print_json({"ok": False, "error": "unknown_inspect_cmd", "inspect_cmd": sub})
    return 2


def _cmd_ro_search(args: Any) -> int:
    """Readonly ripgrep-like search; forbids write redirects by never invoking a shell."""
    import re
    from pathlib import Path as P

    from ascendc_pilot.environment_capabilities import run_source_scope_roots

    project = P(args.project).resolve()
    pattern = str(args.pattern or "")
    try:
        cre = re.compile(pattern)
    except re.error as exc:
        print_json({"ok": False, "error": "bad_pattern", "detail": str(exc)})
        return 2
    scope_roots = run_source_scope_roots(project)
    extra = [str(p).replace("\\", "/").strip() for p in (args.paths or []) if str(p).strip()]
    if any(p in {".", "./", ""} for p in extra):
        print_json(
            {
                "ok": False,
                "error": "SCOPE_REQUIRED",
                "detail": "acp ro-search refuses repo-root paths; use --scope run-source-scope",
            }
        )
        return 2
    roots = list(scope_roots)
    for rel in extra:
        cand = (project / rel).resolve()
        if any(cand == sr or sr in cand.parents or cand in sr.parents or cand == sr for sr in scope_roots):
            roots.append(cand)
    if not roots:
        print_json(
            {
                "ok": False,
                "error": "EMPTY_RUN_SOURCE_SCOPE",
                "hits": [],
                "evidence_tier": "none",
            }
        )
        return 2
    hits: list[dict[str, Any]] = []
    limit = min(int(getattr(args, "limit", 50) or 50), 80)
    suffixes = {".cpp", ".h", ".hpp", ".cc", ".c", ".py", ".yaml", ".yml"}
    for root in roots:
        if not root.exists():
            continue
        files = [root] if root.is_file() else list(root.rglob("*"))
        for fp in files:
            if not fp.is_file() or fp.suffix.casefold() not in suffixes:
                continue
            try:
                rel = fp.relative_to(project).as_posix()
            except ValueError:
                continue
            try:
                text = fp.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for i, line in enumerate(text.splitlines(), 1):
                if cre.search(line):
                    hits.append(
                        {
                            "file": rel,
                            "line": i,
                            "symbol": "",
                            "text": line[:240],
                            "evidence_tier": "C",
                        }
                    )
                    if len(hits) >= limit:
                        print_json(
                            {
                                "ok": True,
                                "hits": hits,
                                "truncated": True,
                                "scope": "run-source-scope",
                            },
                            default=str,
                        )
                        return 0
    print_json(
        {"ok": True, "hits": hits, "truncated": False, "scope": "run-source-scope"},
        default=str,
    )
    return 0


def _doctor(project: Path | None) -> int:
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

    from ascendc_pilot.paths import AGENT_DIR, try_discover_arch

    # Environment precheck must not require an active architecture tree.
    # Creating .ascendc-pilot/<arch>/ is acp start's job, not doctor's.
    if project is None:
        print("project=<unset>")
        print(f"canonical={AGENT_DIR}")
        print("agent_layout=skipped")
    else:
        print(f"project={project}")
        print(f"canonical={AGENT_DIR}")
        arch = try_discover_arch(project)
        agent_dir = Path(project).expanduser().resolve() / AGENT_DIR
        if arch:
            try:
                from ascendc_pilot.paths import agent_root

                print(f"architecture={arch}")
                print(f"agent_root={agent_root(project, arch=arch)}")
            except ValueError as exc:
                warnings.append(f"agent_layout: {exc}")
        elif agent_dir.is_dir():
            print("agent_layout=present (no active architecture)")
        else:
            print("agent_layout=not_created")

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

    # TG consumer root hint
    import os

    if not os.environ.get("ASCENDC_TEST_SCRIPT_ROOT"):
        warnings.append(
            "ASCENDC_TEST_SCRIPT_ROOT unset — generated cases use default input; "
            "pass --test-script-root to bind an existing runner (scripts + CSV)"
        )

    # Same CANN gate as prepare / scripts/dev/check_cann.py (not a warning).
    try:
        from uo_init import paths as uo_paths

        cann_root, cann_issues = uo_paths.require_cann_ready()
        if cann_root is not None:
            print(f"cann_root={cann_root}")
        if cann_issues:
            for item in cann_issues:
                issues.append(f"cann: {item}")
            default_pkg = uo_paths.repo_root() / "_cann" / "pkg"
            issues.append(
                "CANN not ready for prepare. Set UO_CANN_ROOT / "
                "ASCEND_CANN_PACKAGE_PATH / ASCEND_HOME_PATH to a cann-* extract "
                f"or official install (default dest {default_pkg}), or extract with "
                f"python scripts/cann_extract.py <toolkit.run> --dest {default_pkg}. "
                "Persist User-level UO_CANN_ROOT; session-only $env:UO_CANN_ROOT "
                "is lost when the terminal closes. "
                f"OpenCode cache: {uo_paths.opencode_cann_root_cache_path()}"
            )
        else:
            print("cann_layout=ok")
            if cann_root is not None:
                try:
                    from ascendc_pilot.paths import write_opencode_cann_root

                    write_opencode_cann_root(cann_root)
                except Exception:  # noqa: BLE001
                    pass
    except Exception as exc:  # noqa: BLE001
        issues.append(f"cann precheck failed: {exc}")

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
