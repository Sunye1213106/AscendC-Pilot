# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_return_value_hook_is_ephemeral_and_narrow() -> None:
    text = (ROOT / "opencode-plugin" / "zz-uo-query-return-value.ts").read_text(encoding="utf-8")
    assert "ASCENDC_ACTION_RESULT" in text
    assert "pendingByProject" in text
    assert '"tool.execute.before"' in text
    assert "next_primary_finalize" in text
    assert "kb-answer-v1" in text
    assert "isKbLookupFinalize" in text
    assert "spawnSync(" not in text
    assert "writeFileSync" not in text
    assert "--result-file" not in text


def test_task_hook_uses_pending_dispatch_project() -> None:
    plugin = (ROOT / "opencode-plugin" / "ascendc-pilot.ts").read_text(encoding="utf-8")
    driver = (ROOT / "opencode-plugin" / "pilot-driver.ts").read_text(encoding="utf-8")
    assert "ascendc-pending-dispatch.json" in plugin
    assert "readPendingDispatchProject" in plugin
    assert "isPilotProjectRoot(cwdNow)" in plugin
    assert "readLatestPendingDispatch" in driver
    assert "return readLatestPendingDispatch()" in driver


def test_installers_copy_all_opencode_ts_hooks() -> None:
    sh = (ROOT / "install.sh").read_text(encoding="utf-8")
    ps1 = (ROOT / "install.ps1").read_text(encoding="utf-8")
    assert "opencode-plugin/ascendc-pilot.ts" in sh
    assert "ascendc-pilot.ts" in ps1
    assert "zz-uo-query-return-value.ts" in sh
    assert "zz-uo-query-return-value.ts" in ps1
    # Library must not be copied into the OpenCode autoload directory.
    assert 'Remove-Item -Force -LiteralPath $legacyDriver' in ps1 or "Removed autoloaded library" in ps1
    assert 'rm -f "$PLUGINS/pilot-driver.ts"' in sh
