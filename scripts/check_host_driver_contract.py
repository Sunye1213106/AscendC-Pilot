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
    for name in ("ascendc-pilot.ts", "pilot-driver.ts", "pilot-progress.mjs"):
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
        "compactPilotRunPayload",
        "error_detail",
        "hint_zh",
        "toPluginToolResult",
        "createProgressReporter",
        "createToolRowProgressReporter",
        "publishVisibleProgress",
        "withProgressArg",
        "Do not call ctx.metadata",
        "await reporter.flushAsync()",
        "isHumanDecision",
        "isAcpStartSuccess",
        "normalizeResumeDecision",
        "answer_from_source",
        "primary_router",
        'startedKind === "primary_router"',
        'decision === "uo-init"',
        'decision === "source"',
        "applyForceNew",
        "ctx.metadata",
        "export default",
        "PilotDriverLibraryPlugin",
        'from "./pilot-progress.mjs"',
    ):
        if marker not in driver_src:
            errors.append(f"pilot-driver.ts missing {marker}")
    # Must not concat stderr into JSON parse buffer
    if 'stdout || ""}\n${result.stderr' in driver_src or "stdout + stderr" in driver_src:
        errors.append("pilot-driver.ts still concatenates stderr into JSON parse")
    if "compactPilotRunPayload(result)" not in driver_src:
        errors.append("toPluginToolResult must serialize compactPilotRunPayload, not the full ACP blob")
    if "return runPilotDriver(" in driver_src:
        errors.append("pilot_run execute must wrap runPilotDriver with toPluginToolResult")
    if '"uo-update": ["prepare"' in driver_src:
        errors.append("pilot-driver.ts must not hardcode uo-update as prepare/extract/analyze")
    if "JSON.stringify(rec, null, 2)" in driver_src:
        errors.append("toPluginToolResult must not pretty-print the full ACP result to the model")
    if "spawnSync" in driver_src:
        errors.append("pilot-driver.ts must stream acp via spawn (not spawnSync) so progress can update")
    if "invokeToolMetadata" in driver_src:
        errors.append("pilot-driver.ts must not call ctx.metadata (it resets GenericTool input)")
    progress_src = (plug / "pilot-progress.mjs").read_text(encoding="utf-8")
    for marker in (
        "buildToolPartProgressPatch",
        "patchRunningToolPart",
        "validateOpencodeToolPartPatch",
        "createToolRowProgressReporter",
        "clientBaseUrl",
        "never call it from this path",
        "session.message.v1",
        "inner.patch.sessionID",
        "inner.patch.v1",
        "path: { id:",
        "sdkInner",
        "Never write stderr/stdout",
        "transportDead",
        "isDummyOpenCodeUrl",
    ):
        if marker not in progress_src:
            errors.append(f"pilot-progress.mjs missing {marker}")
    if "console.error(" in progress_src:
        errors.append("pilot-progress.mjs must not console.error into the OpenCode TUI")
    plugin_src = (plug / "ascendc-pilot.ts").read_text(encoding="utf-8")
    for marker in (
        "extractProjectFromAcpCommand",
        "isAcpResumeStartCommand",
        'status !== "pending"',
        "isPilotDriver",
        "resolveInstalledSkillMd",
        "Do NOT overwrite OpenCode Task",
        "rgMissingRewrite",
        "patchPilotReadPermissions",
        'perm.external_directory = "allow"',
        "Do not widen task",
        "extractKbAnswer",
        "nativeTaskResultCap",
        "captureUoQueryTaskReturn",
        "ASCENDC_ACTION_RESULT",
        "isKbLookupFinalize",
        "must not finalize itself",
        "isHarnessCheckout",
        "rewriteAcpProjectFlag",
        "pinOperatorBashContext",
        "boundOperatorRoot",
        "recoverSkillToolOutput",
        "lastSkillName",
        "createPilotSkillTool",
        "createPilotCliTool",
        "createPilotRunStub",
        "ACP_HELP_USAGE_CARD",
        "Do not use --help to discover protocol",
        "isReadonlyInspectBash",
        "isPrimaryPilotAgent",
        "patchWindowsShell",
        "ensureOpenCodeRipgrep",
        "ensureAcpOnPath",
        "prependPilotToolPath",
        "openCodeRgBinDirs",
        "resolveInstalledSkillPath",
        "isolateNativeOpenCodeAgents",
        "denyPilotWorkflowSkills",
        "rememberSessionAgent",
        "NATIVE_OPENCODE_AGENTS",
        "PILOT_WORKFLOW_SKILLS",
        "Do not assign plugin.tool.skill",
        "Never default unlabeled sessions to ascendc-pilot",
        '"chat.params"',
    ):
        if marker not in plugin_src:
            errors.append(f"ascendc-pilot.ts missing {marker}")
    if "args.location = { directory: projectRoot }" in plugin_src:
        errors.append("ascendc-pilot.ts must not pin Task location.directory to operator package")
    if ").skill = createPilotSkillTool" in plugin_src or "pilotTools as Record<string, unknown>).skill" in plugin_src:
        errors.append("ascendc-pilot.ts must not override native OpenCode skill (Build/Plan isolation)")
    if "createAcpCliTool" in plugin_src or ").acp = createPilotCliTool" in plugin_src:
        errors.append("ascendc-pilot.ts must not register a plugin tool named acp")
    if "pilotTools = {}" in plugin_src and "createPilotRunStub" not in plugin_src:
        errors.append("ascendc-pilot.ts must stub pilot_run when driver load fails")
    if "createPilotSkillTool" not in plugin_src:
        errors.append("ascendc-pilot.ts must keep createPilotSkillTool for Pilot SKILL.md recovery")
    if 'if (perm["*"] === undefined) perm["*"] = "deny"' in plugin_src:
        errors.append("plugin must not add top-level * deny on Primary (blocks read/grep)")
    if "denyPilotWorkflowSkills" not in plugin_src:
        errors.append("plugin must deny Pilot workflow skill names on native Build/Plan")
    if "ensureOpenCodeRipgrep" not in plugin_src:
        errors.append("ascendc-pilot.ts must seed OpenCode cache rg.bin")
    auth_src = (repo / "pilot" / "ascendc_pilot" / "authorize" / "__init__.py").read_text(
        encoding="utf-8"
    )
    if "workflow_uses_host_driver" not in auth_src:
        errors.append("authorize must allow Task of host_driver=False actors (uo-query)")
    if "CONTAINMENT_PRIMARY_READ" not in auth_src:
        errors.append("authorize must allow primary Read/Glob during containment")
    driver_src = (plug / "pilot-driver.ts").read_text(encoding="utf-8")
    if "Do not strip to the yaml fence" not in driver_src:
        errors.append("pilot-driver.ts must keep native Task text (not yaml-fence-only)")
    if "NATIVE_TASK_RESULT_CAP" not in driver_src:
        errors.append("pilot-driver.ts missing NATIVE_TASK_RESULT_CAP")
    if "UO_QUERY_NOT_HOST_DRIVEN" not in driver_src:
        errors.append("pilot-driver.ts must reject pilot_run for uo-query")
    uo_query_reject = driver_src.split('if (workflow === "uo-query")')[1].split("const parentSessionId")[0]
    if "acp uo-query" in uo_query_reject and "--mode" in uo_query_reject:
        errors.append("pilot-driver.ts uo-query reject must not teach acp uo-query --mode")
    if "3_600_000" not in driver_src:
        errors.append("pilot-driver.ts auto drain must use hour-level timeout")
    if "ACP_TIMEOUT" not in driver_src:
        errors.append("pilot-driver.ts must return ACP_TIMEOUT on drain timeout")
    if "USE_PILOT_RUN" not in auth_src:
        errors.append("authorize must deny bash acp start / run-action auto (USE_PILOT_RUN)")
    if "PRIMARY_DIAGNOSTIC" not in auth_src:
        errors.append("authorize must allow primary diagnostic python")
    if "write_opencode_cann_root" not in (repo / "pilot" / "ascendc_pilot" / "paths" / "__init__.py").read_text(
        encoding="utf-8"
    ):
        errors.append("paths must persist OpenCode CANN root cache")
    compose_src = (repo / "scripts" / "compose_runtime.py").read_text(encoding="utf-8")
    if '"external_directory": "allow"' not in compose_src:
        errors.append("compose_runtime.py must allow OpenCode external_directory for Pilot agents")
    if '"read": "allow"' not in compose_src:
        errors.append("compose_runtime.py must allow OpenCode read for Pilot agents")
    if '"Get-ChildItem": "allow"' not in compose_src:
        errors.append("compose_runtime.py must allow bare Get-ChildItem for OpenCode bash")
    if "opencode_primary_task_permission" not in compose_src:
        errors.append("compose_runtime.py must emit Primary task whitelist")
    if "opencode_isolated_primary_permission" not in compose_src:
        errors.append("compose_runtime.py must isolate Primary permission from Build/Plan")
    if 'Do **not** set top-level ``*: deny``' not in compose_src:
        errors.append("compose_runtime.py must not use top-level * deny on Primary (blocks read)")
    if '"pilot_run": "allow"' not in compose_src:
        errors.append("compose_runtime.py must allowlist pilot_run on Primary")
    if "OPENCODE_PRIMARY_TASK_ALLOW" not in compose_src:
        errors.append("compose_runtime.py missing OPENCODE_PRIMARY_TASK_ALLOW")
    if '"task": "allow"' in compose_src:
        errors.append("compose_runtime.py must not emit task: allow for Primary")
    if 'perm.task = "allow"' in plugin_src:
        errors.append("plugin must not widen Primary task to allow")
    sh = (repo / "install.sh").read_text(encoding="utf-8")
    ps1 = (repo / "install.ps1").read_text(encoding="utf-8")
    frontend = repo / "engines" / "understand-operator" / "native" / "uo_frontend" / "CMakeLists.txt"
    if not frontend.is_file():
        errors.append("native uo_frontend/CMakeLists.txt missing")
    if "native/uo_frontend" not in sh.replace("\\", "/"):
        errors.append("install.sh must cmake uo_frontend")
    if "native\\uo_frontend" not in ps1 and "native/uo_frontend" not in ps1.replace("\\", "/"):
        errors.append("install.ps1 must cmake uo_frontend")
    if "native/uo_walk" in sh or "native\\uo_walk" in sh:
        errors.append("install.sh still references stale uo_walk")
    if "native\\uo_walk" in ps1 or "native/uo_walk" in ps1:
        errors.append("install.ps1 still references stale uo_walk")
    if "Keep workflow skills plugin-internal" not in ps1:
        errors.append("install.ps1 must not link workflow skills into global OpenCode skills/")
    if "plugin-internal only. Global skills/" not in sh:
        errors.append("install.sh must not link workflow skills into global OpenCode skills/")
    if "Only expose AscendC-Pilot" not in sh:
        errors.append("install.sh must only link ascendc-pilot.md as OpenCode Tab")
    if "leftover OpenCode Tab" not in ps1:
        errors.append("install.ps1 must clean leftover OpenCode Tabs")

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
    for name in ("uo-query.yaml", "tg-analyst.yaml", "ce-reviewer.yaml"):
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
