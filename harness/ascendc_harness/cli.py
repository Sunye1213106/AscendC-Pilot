"""Harness CLI: doctor / validate / start / next / advance / run-action / ..."""

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
    p_start.add_argument("--op-name", default="", help="Operator name for UO/TG engines")
    p_start.add_argument("--architecture", default="", help="Target architecture (default arch35)")
    p_start.add_argument("--test-script-root", type=Path, default=None, help="CSV consumer / test script root")
    p_start.add_argument("--csv-consumer-root", type=Path, default=None, help="Alias of --test-script-root")
    p_start.add_argument("--level", default="", help="TG plan/solve level (default L0)")
    p_start.add_argument("--focus", default="", help="TG plan focus")

    p_run = sub.add_parser("run-action", help="Prepare or finalize a workflow Action (sole execution entry)")
    p_run.add_argument("action_id")
    p_run.add_argument("--project", type=Path, default=Path.cwd())
    p_run.add_argument(
        "--finalize",
        action="store_true",
        help="Finalize prepared action: check contract/gates and issue signed receipt",
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

    p_scope = sub.add_parser(
        "uo-scope",
        help="Run UO scope_confirmation deterministic steps (scan/checkpoint/stage/…)",
    )
    p_scope.add_argument(
        "step",
        choices=["scan", "checkpoint", "build-evidence", "closure", "stage", "finalize"],
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
    p_uq.add_argument("--depth", type=int, default=1)
    p_uq.add_argument("--limit", type=int, default=50)
    p_uq.add_argument("--relation-type", default="")
    p_uq.add_argument("--status-only", action="store_true")

    args = parser.parse_args(argv)

    if args.cmd == "doctor":
        return _doctor(args.project)
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
        from ascendc_harness.state import load_state, start_workflow
        from ascendc_harness.workflows import get_workflow

        get_workflow(args.workflow_id)  # validate
        if not args.force_new:
            existing = load_state(args.project)
            if (
                existing
                and str(existing.get("workflow_id") or "") == args.workflow_id
                and str(existing.get("status") or "")
                in {"running", "rework_required", "human_required"}
            ):
                print(
                    json.dumps(
                        {**existing, "resumed": True, "message_zh": "复用同 workflow 活动 run"},
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                return 0
        state = start_workflow(
            args.project,
            args.workflow_id,
            intent=getattr(args, "intent", "") or "",
            op_name=getattr(args, "op_name", "") or "",
            architecture=getattr(args, "architecture", "") or "",
            test_script_root=(
                str(args.test_script_root.resolve())
                if getattr(args, "test_script_root", None)
                else ""
            ),
            csv_consumer_root=(
                str(args.csv_consumer_root.resolve())
                if getattr(args, "csv_consumer_root", None)
                else ""
            ),
            level=getattr(args, "level", "") or "",
            focus=getattr(args, "focus", "") or "",
        )
        # Persist harness params for subsequent context packs / engines.
        try:
            from ascendc_harness.paths import context_root
            import yaml

            params = {
                "op_name": state.get("op_name") or "",
                "architecture": state.get("architecture") or "arch35",
                "test_script_root": state.get("test_script_root") or "",
                "csv_consumer_root": state.get("csv_consumer_root") or "",
                "level": state.get("level") or "L0",
                "focus": state.get("focus") or "",
            }
            out = context_root(args.project) / "harness_params.yaml"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(yaml.safe_dump(params, allow_unicode=True, sort_keys=False), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
        print(json.dumps(state, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "run-action":
        from ascendc_harness.actions import run_action

        result = run_action(args.project, args.action_id, finalize=bool(args.finalize))
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0 if result.get("ok") else 1
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

        uo = uo_root(args.project, args.op_name or None)
        from uo.scripts.check_final_confidence import check_final_confidence

        payload = check_final_confidence(
            uo,
            write_report=not (args.no_write_report or args.no_skeleton),
            write_skeleton=False,
        )
        # Receipts are issued only via `harness run-action … --finalize`.
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
    if args.cmd == "uo-scope":
        from ascendc_harness.uo_scope import print_result, run_uo_scope

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
        from uo.scripts.uo_kb_query import main as query_main

        project = Path(args.project).resolve()
        op = str(args.op_name or "").strip() or project.name
        argv = [str(project), "--op-name", op]
        if args.status_only:
            argv.append("--status-only")
        else:
            if not args.pattern:
                print(
                    json.dumps(
                        {"ok": False, "error": "pattern_required", "message_zh": "非 --status-only 时需要 --pattern"},
                        ensure_ascii=False,
                    )
                )
                return 2
            argv.extend(["--pattern", args.pattern])
            if args.target:
                argv.extend(["--target", args.target])
            argv.extend(["--depth", str(args.depth), "--limit", str(args.limit)])
            if args.relation_type:
                argv.extend(["--relation-type", args.relation_type])
        return int(query_main(argv) or 0)
    return 2


def _doctor(project: Path) -> int:
    issues: list[str] = []
    warnings: list[str] = []
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
    print(f"canonical={AGENT_DIR}")

    # Composer / agent wiring (same success bar as install)
    try:
        import sys
        from pathlib import Path as _P

        repo = _P(__file__).resolve().parents[2]
        scripts = repo / "scripts"
        if scripts.is_dir() and str(scripts) not in sys.path:
            sys.path.insert(0, str(scripts))
        from compose_runtime import validate, validate_generated

        src_errors = validate(repo)
        for err in src_errors:
            issues.append(f"compose: {err}")
        gen_errors = validate_generated(repo, host="opencode")
        for err in gen_errors:
            issues.append(f"generated: {err}")
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"compose validation skipped: {exc}")

    # Z3 solver (tg-solve)
    try:
        import z3  # noqa: F401
    except ImportError:
        warnings.append("z3 not installed (pip install -e ./engines/tg[solver]) — /tg-solve will fail")

    # CBM MCP: plugin install ≠ MCP configured
    try:
        import json
        from pathlib import Path as _P

        oc = _P.home() / ".config" / "opencode" / "opencode.json"
        if oc.is_file():
            cfg = json.loads(oc.read_text(encoding="utf-8"))
            mcp = cfg.get("mcp") or cfg.get("mcpServers") or {}
            names = {str(k).lower() for k in (mcp.keys() if isinstance(mcp, dict) else [])}
            if not any("codebase-memory" in n or n == "cbm" for n in names):
                warnings.append(
                    "OpenCode opencode.json has no codebase-memory-mcp — "
                    "see docs/cbm-mcp-setup.md (UO source lookup degraded)"
                )
        else:
            warnings.append("OpenCode opencode.json missing — CBM MCP not configured")
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"CBM MCP check skipped: {exc}")

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
