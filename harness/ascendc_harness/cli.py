"""Harness CLI: doctor / migrate-legacy / validate / advance / complete / route / status."""

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

    p_ctx = sub.add_parser("context", help="Build context pack")
    p_ctx.add_argument("--project", type=Path, default=Path.cwd())
    p_ctx.add_argument("--intent", required=True)
    p_ctx.add_argument("--topic", default="")

    p_start = sub.add_parser("start", help="Start workflow state")
    p_start.add_argument("workflow_id")
    p_start.add_argument("--project", type=Path, default=Path.cwd())
    p_start.add_argument("--phase", default="prepare")

    p_adv = sub.add_parser("advance", help="Advance phase only if phase_gates pass")
    p_adv.add_argument("next_phase")
    p_adv.add_argument("--project", type=Path, default=Path.cwd())

    p_done = sub.add_parser("complete", help="Mark workflow pass only if all gates succeed")
    p_done.add_argument("--project", type=Path, default=Path.cwd())
    p_done.add_argument("--reason", default="")

    p_block = sub.add_parser("block", help="Mark workflow blocked/failed/human")
    p_block.add_argument("status", choices=["blocked", "failed", "human"])
    p_block.add_argument("--project", type=Path, default=Path.cwd())
    p_block.add_argument("--reason", default="")

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
    if args.cmd == "context":
        from ascendc_harness.context import build_context_pack

        pack = build_context_pack(args.project, intent=args.intent, topic=args.topic)
        print(json.dumps(pack, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "start":
        from ascendc_harness.state import start_workflow
        from ascendc_harness.workflows import get_workflow

        get_workflow(args.workflow_id)  # validate
        state = start_workflow(args.project, args.workflow_id, phase=args.phase)
        print(json.dumps(state, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "advance":
        from ascendc_harness.state import advance_phase

        result = advance_phase(args.project, args.next_phase)
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
