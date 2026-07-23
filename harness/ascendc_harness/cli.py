"""Harness CLI: doctor / migrate-legacy / validate / start / next / advance / rework / complete / route / status."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="harness", description="AscendC Agent Harness")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_doctor = sub.add_parser("doctor", help="Environment precheck")
    p_doctor.add_argument("--project", type=Path, default=Path.cwd())

    p_mig = sub.add_parser("migrate-legacy", help="Copy legacy KB/TG trees into .ascendc-agent")
    p_mig.add_argument("project", type=Path)
    p_mig.add_argument("--op-name", default="")
    p_mig.add_argument("--dry-run", action="store_true")

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

    p_start = sub.add_parser("start", help="Start workflow at entry_state")
    p_start.add_argument("workflow_id")
    p_start.add_argument("--project", type=Path, default=Path.cwd())

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

    p_hashes = sub.add_parser("spec-hashes", help="Print four Spec Hash digests")
    p_hashes.add_argument("--project", type=Path, default=Path.cwd())
    p_hashes.add_argument("--workflow", default="")

    p_conf = sub.add_parser(
        "emit-confidence-report",
        help="Deterministic engine: assemble confidence_report + confidence_gate from KB",
    )
    p_conf.add_argument("--project", type=Path, default=Path.cwd())
    p_conf.add_argument("--op-name", default="")
    p_conf.add_argument("--no-skeleton", action="store_true")

    p_auth = sub.add_parser("authorize", help="Authorize tool call (OpenCode plugin hook)")
    p_auth.add_argument("--project", type=Path, default=Path.cwd())
    p_auth.add_argument("--tool", required=True)
    p_auth.add_argument("--command", default="")
    p_auth.add_argument("--path", default="")
    p_auth.add_argument("--agent", default="")
    p_auth.add_argument("--action", default="")

    args = parser.parse_args(argv)

    if args.cmd == "doctor":
        return _doctor(args.project)
    if args.cmd == "migrate-legacy":
        from ascendc_harness.migrate import migrate_legacy

        result = migrate_legacy(args.project, op_name=args.op_name or None, dry_run=args.dry_run)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("ok") else 2
    if args.cmd == "validate-key-gates":
        from ascendc_harness.gates import run_key_gates

        payload = run_key_gates(args.project, op_name=args.op_name or None)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if payload.get("ok") else 1
    if args.cmd == "validate":
        from ascendc_harness.gates import run_key_gates, run_workflow_gates

        key_payload = run_key_gates(args.project)
        wf = run_workflow_gates(args.project)
        out = {"key_gates": key_payload, "workflow_gates": wf, "ok": bool(key_payload.get("ok") and wf.get("ok"))}
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0 if out["ok"] else 1
    if args.cmd == "route":
        from ascendc_harness.router import route

        result = route(" ".join(args.text))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("ok") else 2
    if args.cmd == "status":
        from ascendc_harness.state import load_state

        print(json.dumps(load_state(args.project), ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "next":
        from ascendc_harness.state import describe_next

        result = describe_next(args.project)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("ok") else 1
    if args.cmd == "context":
        from ascendc_harness.context import build_context_pack

        pack = build_context_pack(args.project, intent=args.intent, topic=args.topic)
        print(json.dumps(pack, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "start":
        from ascendc_harness.state import start_workflow
        from ascendc_harness.workflows import get_workflow

        get_workflow(args.workflow_id)  # validate
        state = start_workflow(args.project, args.workflow_id)
        print(json.dumps(state, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "advance":
        from ascendc_harness.state import advance_phase

        result = advance_phase(args.project, args.next_phase)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("ok") else 1
    if args.cmd == "rework":
        from ascendc_harness.state import rework_phase

        result = rework_phase(args.project, to=args.to or None, reason_code=args.reason)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("ok") else 1
    if args.cmd == "complete":
        from ascendc_harness.state import complete_workflow

        result = complete_workflow(args.project, reason=args.reason)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("ok") else 1
    if args.cmd == "block":
        from ascendc_harness.state import mark_terminal

        state = mark_terminal(args.project, args.status, reason=args.reason)
        print(json.dumps(state, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "spec-hashes":
        from ascendc_harness.spec_hashes import all_spec_hashes

        # Resolve repo root: prefer cwd containing engines/, else parents of harness package
        repo = args.project
        if not (repo / "engines" / "uo").is_dir():
            here = Path(__file__).resolve().parents[2]
            if (here / "engines" / "uo").is_dir():
                repo = here
        print(
            json.dumps(
                all_spec_hashes(repo, workflow_id=args.workflow or None),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if args.cmd == "emit-confidence-report":
        from ascendc_harness.paths import uo_root
        from ascendc_harness.runs import issue_receipt
        from ascendc_harness.spec_hashes import workflow_spec_hash

        uo = uo_root(args.project, args.op_name or None)
        from uo.scripts.check_final_confidence import check_final_confidence

        payload = check_final_confidence(uo, write_skeleton=not args.no_skeleton)
        try:
            issue_receipt(
                args.project,
                actor_type="deterministic_engine",
                actor_id="deterministic-uo-engine",
                action_id="emit_confidence_report",
                workflow_spec_hash=workflow_spec_hash("uo-init"),
                output_hashes={
                    "confidence_gate": str((uo / "checks" / "confidence_gate.yaml")),
                    "confidence_report": str((uo / "summary" / "confidence_report.md")),
                },
                checker_result={"status": payload.get("status"), "ok": payload.get("ok")},
            )
        except Exception:
            pass
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        return 0 if payload.get("ok") or str(payload.get("status") or "") in {"pass", "reported"} else 1
    if args.cmd == "authorize":
        from ascendc_harness.authorize import authorize

        verdict = authorize(
            args.project,
            tool=args.tool,
            command=args.command,
            path=args.path,
            agent=args.agent,
            action=args.action,
        )
        print(json.dumps(verdict, ensure_ascii=False, indent=2))
        if verdict.get("decision") == "allow" or verdict.get("ok"):
            return 0
        if verdict.get("decision") == "ask":
            return 2
        return 1
    return 2


def _doctor(project: Path) -> int:
    issues: list[str] = []
    try:
        import yaml  # noqa: F401
    except ImportError:
        issues.append("PyYAML missing")
    try:
        import ascendc_harness  # noqa: F401
    except ImportError:
        issues.append("ascendc_harness not installed (pip install -e ./harness)")
    try:
        import uo  # noqa: F401
    except ImportError:
        issues.append("uo engine not installed (pip install -e ./engines/uo)")
    try:
        import testcase_agent  # noqa: F401
    except ImportError:
        issues.append("testcase_agent not installed (pip install -e ./engines/tg)")

    from ascendc_harness.paths import AGENT_DIR, ensure_agent_layout

    root = ensure_agent_layout(project)
    print(f"agent_root={root}")
    print(f"legacy_dirs_ignored_for_writes=yes; canonical={AGENT_DIR}")
    if issues:
        print("ISSUES:")
        for item in issues:
            print(f"  - {item}")
        return 1
    print("doctor_ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
