# Testcase Agent path hints

`PLUGIN_ROOT` = repository root of `testcase-agent/` (contains `skills/`, `testcase_agent/`, `install.ps1`).

## Commands

| Skill | CLI |
|-------|-----|
| `/tg-contract` | `tg-contract <算子仓\|kb> --op-name <op> --test-script-root <测试工具>` |
| `/tg-plan` | `tg-plan <算子仓\|kb> --op-name <op> (--test-script-root <测试工具> \| --contract-root <realization>) [--level …]` |
| `/tg-solve` | `tg-solve <算子仓> --op-name <op> [--level …] [--dry-run]` |

Path roles:

- `project_root`：算子仓（含 `.understand-operator/<op_name>/`）。也可直接传 KB 路径。
- `--test-script-root` / `--csv-consumer-root`：测试工具 → **自动 contract** 再 plan。
- `--contract-root`：已有 contract 产物（`realization/`）→ 复用，不再扫测试工具。
- 二者缺一且无 contract：CLI 失败并返回 `ask=missing_plan_inputs`（agent 应 AskQuestion）。
- Outputs：`.testcase-generator/<op_name>/`（在算子仓下）。

## Windows PowerShell

```powershell
$PLUGIN_ROOT = "$env:USERPROFILE\.config\opencode\testcase-agent-plugin"
Test-Path $PLUGIN_ROOT
```

If `Test-Path` is False: in the repo root run `./install.ps1 opencode`. Do **not** search the whole disk.

## Notes

- Intake reads pre-built YAML under `.understand-operator/` directly; `understand_operator` plugin is optional.
- Human review (AskQuestion): `approve` → write `plan/human_supplement.yaml` then immediately `tg-solve`; `reject` stop; `suggest` re-plan.
- Do not modify `.understand-operator/`.
- Agents must run the real CLI for `/tg-plan`; never hand-write plan YAML as a substitute.
