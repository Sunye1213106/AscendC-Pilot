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


def test_installers_copy_all_opencode_ts_hooks() -> None:
    sh = (ROOT / "install.sh").read_text(encoding="utf-8")
    ps1 = (ROOT / "install.ps1").read_text(encoding="utf-8")
    assert "opencode-plugin/*.ts" in sh
    assert 'Filter "*.ts"' in ps1
    assert "zz-uo-query-return-value.ts" in sh
    assert "zz-uo-query-return-value.ts" in ps1
