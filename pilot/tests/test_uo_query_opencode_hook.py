# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_return_value_hook_is_ephemeral_and_narrow() -> None:
    text = (ROOT / "opencode-plugin" / "ascendc-pilot.ts").read_text(encoding="utf-8")
    assert "ASCENDC_ACTION_RESULT" in text
    assert "uoQueryPendingByProject" in text
    assert '"tool.execute.before"' in text
    assert "next_primary_finalize" in text
    assert "UO_QUERY_NATIVE_TASK_RESULT_CAP" in text
    assert "isKbLookupFinalize" in text
    assert "SLICE_ID=" in text
    assert "fanout_slice" in text
    assert "fillEmptyUoQueryTaskOutput" in text
    assert "empty native task_result" in text
    capture_fn = text.split("function captureUoQueryTaskReturn")[1].split("export const AscendCHarnessPlugin")[0]
    assert "--result-file" not in capture_fn
    assert "isKbLookupFinalize" in capture_fn


def test_task_hook_uses_session_safe_pending_dispatch() -> None:
    plugin = (ROOT / "opencode-plugin" / "ascendc-pilot.ts").read_text(encoding="utf-8")
    driver_facade = (ROOT / "opencode-plugin" / "pilot-driver.ts").read_text(encoding="utf-8")
    driver_core = (ROOT / "opencode-plugin" / "pilot-driver-core.ts").read_text(encoding="utf-8")
    driver = driver_facade + "\n" + driver_core
    assert "ascendc-pending-dispatch.json" in plugin
    assert "readPendingDispatchProject" in plugin
    assert "isHarnessCheckout" in plugin
    assert "rewriteAcpProjectFlag" in plugin
    assert "pinOperatorBashContext" in plugin
    assert "boundOperatorRoot" in plugin
    assert "Do NOT overwrite OpenCode Task" in plugin
    assert "resolveInstalledSkillMd" in plugin
    assert "resolveInstalledSkillPath" in plugin
    assert "recoverSkillToolOutput" in plugin
    assert "createPilotSkillTool" in plugin
    assert "createPilotCliTool" in plugin
    assert "createPilotRunStub" in plugin
    assert "createAcpCliTool" not in plugin
    assert "patchWindowsShell" in plugin
    assert "Do NOT set args.env" in plugin
    assert "ensureOpenCodeRipgrep" in plugin
    assert "ensureAcpOnPath" in plugin
    assert "prependPilotToolPath" in plugin
    assert "openCodeRgBinDirs" in plugin
    assert "denyPilotWorkflowSkills" in plugin
    assert "PILOT_WORKFLOW_SKILLS" in plugin
    assert ").skill = createPilotSkillTool" not in plugin
    assert 'pilotTools as Record<string, unknown>).skill' not in plugin
    assert "Do not assign plugin.tool.skill" in plugin
    assert "Must not be applied to the global OpenCode config" in plugin
    assert "return patchWindowsShell(out)" not in plugin
    assert "  ensureAcpOnPath()" not in plugin
    assert "delete perm[\"*\"]" in plugin or 'delete perm["*"]' in plugin
    assert '"shell.env"' in plugin
    assert "lastSkillName" in plugin
    assert "return output || {}" in plugin
    assert "patchPilotReadPermissions" in plugin
    assert "isolateNativeOpenCodeAgents" in plugin
    assert "rememberSessionAgent" in plugin
    assert "NATIVE_OPENCODE_AGENTS" in plugin
    assert "Never default unlabeled sessions to ascendc-pilot" in plugin
    assert "ownedPilotAgentIds" in plugin
    assert "install-manifest.json" in plugin
    assert "PILOT_AGENT_PREFIXES" not in plugin
    assert 'resolve(openCodeHome(), "agents")' not in plugin
    assert "Never scan ~/.config/opencode/agents" in plugin
    assert '"chat.params"' in plugin
    assert 'perm.external_directory = "allow"' in plugin
    assert 'perm.task = "allow"' not in plugin
    assert "Do not widen task" in plugin
    assert "UO_QUERY_NOT_HOST_DRIVEN" in driver
    assert "args.location = { directory: projectRoot }" not in plugin
    assert "readLatestPendingDispatch" in driver
    assert "readDispatchFor" in driver_facade
    assert "currentHostSessionHint" in driver_facade
    assert "return readLatestPendingDispatch()" not in driver_facade
    assert '"tasks"' in driver
    assert "native_tasks" in driver
    assert "host_step.tasks" in driver
    assert "hostSpawnFanout" not in driver_core
    assert "client.session.create" not in driver_core
    assert "nativeTaskHandoff" in driver_core
    assert "FANOUT_INCOMPLETE" not in driver_core
    assert "Do not strip to the yaml fence" in driver
    assert "NATIVE_TASK_RESULT_CAP" in driver
    assert "200_000" in driver


def test_installers_copy_all_opencode_ts_hooks() -> None:
    sh = (ROOT / "install.sh").read_text(encoding="utf-8")
    ps1 = (ROOT / "install.ps1").read_text(encoding="utf-8")
    assert "opencode-plugin/ascendc-pilot.ts" in sh
    assert "ascendc-pilot.ts" in ps1
    assert "opencode-plugin/zz-uo-query-return-value.ts" not in sh
    assert 'opencode-plugin\\zz-uo-query-return-value.ts' not in ps1
    assert '@("ascendc-pilot.ts", "zz-uo-query-return-value.ts")' not in ps1
    # Library must not be copied into the OpenCode autoload directory.
    assert 'Remove-Item -Force -LiteralPath $legacyDriver' in ps1 or "Removed autoloaded library" in ps1
    assert 'rm -f "$PLUGINS/pilot-driver.ts"' in sh
    assert "LOCALAPPDATA" in ps1
    assert r"opencode\bin" in ps1
    assert "XDG_CACHE_HOME" in sh
    assert "XDG_CONFIG_HOME" in sh
    assert "Keep workflow skills plugin-internal" in ps1
    assert "plugin-internal only. Global skills/" in sh
    assert "XDG_CONFIG_HOME" in ps1
    assert ".cache/opencode/bin" in sh
    assert ".cache\\opencode\\bin" in ps1
    assert "Get-AcpExe" in ps1
    assert "resolve_acp_bin" in sh
    assert "function Remove-ReparseOrItem" in ps1
    assert "function Invoke-CmdQuiet" in ps1
    assert "PSNativeCommandUseErrorActionPreference" in ps1
    assert ps1.rstrip().endswith("exit 0")
    assert "function Install-DirLink" in ps1
    assert "function Write-CannHint" in ps1
    assert "New-Item -ItemType Junction" not in ps1
    assert 'mklink /J `"$Link`" `"$Target`"' in ps1
    assert "--fixup" in ps1
    assert r"_cann\pkg" in ps1
    assert "_cann/pkg" in sh