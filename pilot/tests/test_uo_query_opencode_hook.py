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
    assert "captureUoQueryTaskReturn" in text
    assert "must not finalize itself" in text
    capture_fn = text.split("function captureUoQueryTaskReturn")[1].split("export const AscendCHarnessPlugin")[0]
    assert "--result-file" not in capture_fn
    assert "isKbLookupFinalize" in capture_fn


def test_task_hook_uses_pending_dispatch_project() -> None:
    plugin = (ROOT / "opencode-plugin" / "ascendc-pilot.ts").read_text(encoding="utf-8")
    driver = (ROOT / "opencode-plugin" / "pilot-driver.ts").read_text(encoding="utf-8")
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
    assert "ensureOpenCodeRipgrep" in plugin
    assert "ensureAcpOnPath" in plugin
    assert "prependPilotToolPath" in plugin
    assert "openCodeRgBinDirs" in plugin
    assert 'pilotTools as Record<string, unknown>).skill' in plugin or 'createPilotSkillTool()' in plugin
    assert '"shell.env"' in plugin
    assert "lastSkillName" in plugin
    assert "return output || {}" in plugin
    assert "patchPilotReadPermissions" in plugin
    assert 'perm.external_directory = "allow"' in plugin
    assert 'perm.task = "allow"' in plugin
    assert "UO_QUERY_NOT_HOST_DRIVEN" in driver
    assert "args.location = { directory: projectRoot }" not in plugin
    assert "readLatestPendingDispatch" in driver
    assert "return readLatestPendingDispatch()" in driver
    assert '"tasks"' in driver
    assert "native_tasks" in driver
    assert "host_step.tasks" in driver
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
    assert ".cache/opencode/bin" in sh
    assert ".cache\\opencode\\bin" in ps1
