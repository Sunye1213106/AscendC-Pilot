# `/tg-init` 命令块（父代理）

变量（`PLUGIN_ROOT` 按平台选一，见 `skills/PATHS.md`）：

```powershell
# OpenCode:
$PLUGIN_ROOT = Join-Path $env:USERPROFILE ".config\opencode\testcase-agent-plugin"
# Cursor:
# $PLUGIN_ROOT = Join-Path $env:USERPROFILE ".cursor\testcase-agent-plugin"
# Codex:
# $PLUGIN_ROOT = Join-Path $env:USERPROFILE ".agents\testcase-agent-plugin"

$PROJECT_ROOT = "<算子仓>"
$OP_NAME = "<op>"
$TEST_ROOT = "<测试工具>"
```

派发 / schema：`$PLUGIN_ROOT/prompts/init/dispatch.md`、`$PLUGIN_ROOT/agents/references/`。

## Phase 1 — thin contract + scaffolds

```powershell
tg-init "$PROJECT_ROOT" --op-name $OP_NAME --test-script-root "$TEST_ROOT"
```

## Phase 2–5 — 自动绑定环

```text
WHILE not (verify_pass AND audit_pass):
  并行 Task Follow uo-query（cap 8）→ realization/uo_query_resolve/*.yaml
  tg-init ... --merge-uo-resolve
  读 mid_symbol_queue → 非空则继续 Task
  tg-init ... --verify-csv-closure
  Task tg-init-audit → init/audit_report.yaml
  # fail → 自动再进 WHILE；禁止问用户「是否继续」
```

```powershell
tg-init "$PROJECT_ROOT" --op-name $OP_NAME --merge-uo-resolve
tg-init "$PROJECT_ROOT" --op-name $OP_NAME --list-open-mids
tg-init "$PROJECT_ROOT" --op-name $OP_NAME --verify-csv-closure
```

## Phase 6 — confirm

```powershell
tg-init "$PROJECT_ROOT" --op-name $OP_NAME --confirm
```

细则：`$PLUGIN_ROOT/skills/tg-init/references/tg-uo-query-escalation.md`。
