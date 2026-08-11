#!/usr/bin/env python3
"""L2 harness E2E (no LLM): authorize deny scenarios on a synthetic op root."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def main() -> int:
    pilot = REPO / "pilot"
    if str(pilot) not in sys.path:
        sys.path.insert(0, str(pilot))

    from ascendc_pilot.authorize import authorize
    from ascendc_pilot.authorize.lease import issue_action_lease, lease_path
    from ascendc_pilot.paths import agent_root, ensure_agent_layout, tg_root
    from ascendc_pilot.state import start_workflow
    import yaml

    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="harness_e2e_") as td:
        op = Path(td) / "DemoOp"
        op.mkdir()
        ensure_agent_layout(op)
        intent = tg_root(op) / "init" / "init_intent.yaml"
        intent.parent.mkdir(parents=True, exist_ok=True)
        intent.write_text(
            yaml.safe_dump({"schema": "tg-init-intent/v1", "mode": "csv_consumer"}),
            encoding="utf-8",
        )
        start_workflow(op, "tg-init", phase="bind", force_phase=True)

        # Unknown tool
        v = authorize(op, tool="filesystem_write_v2", path=str(agent_root(op) / "x"), agent="tg-semantic-bind")
        if v.get("reason_code") != "TOOL_UNKNOWN":
            failures.append(f"unknown tool: {v}")

        # Producer outside lease
        issue_action_lease(
            op,
            action_id="semantic_bind",
            actor_id="tg-semantic-bind",
            allowed_write_paths=["tg/realization/semantic_bind_patch.yaml"],
        )
        outside = agent_root(op) / "runs" / "x" / "actions" / "semantic_bind" / "scratch" / "n.yaml"
        outside.parent.mkdir(parents=True, exist_ok=True)
        v = authorize(
            op,
            tool="write",
            path=str(outside),
            agent="tg-semantic-bind",
            action="semantic_bind",
        )
        if v.get("reason_code") != "ACTION_WRITE_SCOPE_DENIED":
            failures.append(f"outside lease: {v}")

        # Stale lease
        lp = lease_path(op)
        lease = yaml.safe_load(lp.read_text(encoding="utf-8"))
        lease["run_id"] = "STALE"
        lp.write_text(yaml.safe_dump(lease), encoding="utf-8")
        target = agent_root(op) / "tg" / "realization" / "semantic_bind_patch.yaml"
        target.parent.mkdir(parents=True, exist_ok=True)
        v = authorize(
            op,
            tool="write",
            path=str(target),
            agent="tg-semantic-bind",
            action="semantic_bind",
        )
        if v.get("reason_code") != "ACTION_RUN_MISMATCH":
            failures.append(f"stale lease: {v}")

        # Referee cannot write producer path
        start_workflow(op, "tg-solve", phase="audit", force_phase=True)
        v = authorize(
            op,
            tool="write",
            path=str(target),
            agent="tg-closure-referee",
            action="closure_audit",
        )
        if v.get("decision") != "deny":
            failures.append(f"referee producer write: {v}")

    ok = not failures
    print(json.dumps({"ok": ok, "failures": failures}, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
