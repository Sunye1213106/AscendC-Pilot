#!/usr/bin/env python3
"""CI: Host Session Driver + Bundle closure contract checks."""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo / "pilot"))
    errors: list[str] = []

    # Modules importable
    try:
        from ascendc_pilot.authorize.serve import handle_request
        from ascendc_pilot.authorize.cache import build_cache_key, get, put
        from ascendc_pilot.actions.dispatch import (
            attach_host_step,
            build_host_step,
            issue_dispatch_ticket,
        )
        from ascendc_pilot.actions.method_bundle import (
            check_bundle_readable,
            materialize_method_bundle,
        )
        from ascendc_pilot.agents_registry import scope_allows_path, split_scope_ns
        from ascendc_pilot.host_doctor import doctor_host
        from ascendc_pilot.context.compiler import missing_reference_paths
    except Exception as exc:  # noqa: BLE001
        print(f"IMPORT_FAIL: {exc}")
        return 1

    # Scope namespace split
    ns, pat = split_scope_ns("method:skills/operator-analysis/**")
    if ns != "method" or not pat.startswith("skills/"):
        errors.append(f"split_scope_ns method failed: {(ns, pat)}")
    ns2, pat2 = split_scope_ns("uo/**")
    if ns2 != "pilot" or pat2 != "uo/**":
        errors.append(f"split_scope_ns pilot failed: {(ns2, pat2)}")
    ns3, pat3 = split_scope_ns("pilot:uo/**")
    if ns3 != "pilot" or pat3 != "uo/**":
        errors.append(f"split_scope_ns pilot: prefix failed: {(ns3, pat3)}")

    # Ping serve handler
    ping = handle_request({"method": "ping"})
    if not ping.get("ok"):
        errors.append(f"serve ping failed: {ping}")

    # Cache roundtrip
    key = build_cache_key(
        None,
        tool="read",
        command="",
        path="x",
        agent="a",
        action="b",
        lease_id="",
    )
    put(key, {"ok": True, "decision": "allow"})
    _ = get(key)

    # host_step shape
    step = build_host_step(kind="done", message_zh="ok")
    if step.get("kind") != "done":
        errors.append("build_host_step kind")

    # Plugin files present in repo
    plug = repo / "opencode-plugin"
    for name in ("ascendc-pilot.ts", "pilot-driver.ts", "zz-uo-query-return-value.ts"):
        if not (plug / name).is_file():
            errors.append(f"missing opencode-plugin/{name}")

    # Driver must own Todo/AskQuestion helpers (string markers)
    driver_src = (plug / "pilot-driver.ts").read_text(encoding="utf-8")
    for marker in (
        "syncTodos",
        "invokeAskHuman",
        "pendingStep",
        "host_owned_ask",
        "parseAcpStdoutJson",
        "continue_goal",
        "--intent",
    ):
        if marker not in driver_src:
            errors.append(f"pilot-driver.ts missing {marker}")
    # Must not concat stderr into JSON parse buffer
    if 'stdout || ""}\n${result.stderr' in driver_src or "stdout + stderr" in driver_src:
        errors.append("pilot-driver.ts still concatenates stderr into JSON parse")

    # control invariants slimmed
    inv = (repo / "pilot" / "policies" / "invariants" / "control-invariants.md").read_text(
        encoding="utf-8"
    )
    if "Host Session Driver" not in inv:
        errors.append("control-invariants.md missing Host Session Driver note")
    numbered = [
        ln
        for ln in inv.splitlines()
        if ln[:2].rstrip(".").isdigit() or (len(ln) > 2 and ln[0].isdigit() and ln[1] == ".")
    ]
    if len(numbered) > 6:
        errors.append(f"control-invariants still too long ({len(numbered)} numbered items)")

    # Agents migrated to scope namespaces
    agents_dir = repo / "agents"
    for name in ("uo-query.yaml", "tg-init-audit.yaml", "ce-reviewer.yaml"):
        text = (agents_dir / name).read_text(encoding="utf-8")
        if "method:skills/" not in text and "pilot:" not in text:
            errors.append(f"{name} missing pilot:/method: namespaces")
        if "skills/testcase-generation/SKILL.md" in text or "skills/operator-analysis/SKILL.md" in text:
            errors.append(f"{name} description still points at dead skill path")

    # doctor_host callable
    payload = doctor_host("opencode")
    if "checks" not in payload:
        errors.append("doctor_host missing checks")

    # missing_reference helper
    if missing_reference_paths([{"path": "x", "status": "missing"}]) != ["x"]:
        errors.append("missing_reference_paths broken")

    # silence unused imports for static checkers
    _ = (attach_host_step, issue_dispatch_ticket, check_bundle_readable, materialize_method_bundle, scope_allows_path)

    if errors:
        print("HOST_CONTRACT_FAIL")
        for e in errors:
            print(" -", e)
        return 1
    print("HOST_CONTRACT_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
