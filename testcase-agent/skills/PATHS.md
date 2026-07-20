# Testcase Agent path hints

`PLUGIN_ROOT` = repository root of `testcase-agent/` (contains `skills/`, `testcase_agent/`, `install.ps1`).

## Commands

| Skill | CLI |
|-------|-----|
| `/tg-contract` | `tg-contract <project_root> --op-name <op> --csv-consumer-root <test_script_root>` |
| `/tg-plan` | `tg-plan <project_root> --op-name <op> --csv-consumer-root <root> [--level L0\|L1\|L2\|L3]` |
| `/tg-solve` | `tg-solve <project_root> --op-name <op> [--level …] [--dry-run]` |

`project_root` must contain `.understand-operator/<op_name>/` (pre-built KB).  
`--csv-consumer-root` is the test script / CSV consumer tree (e.g. `TEST/fag_debug_tools`).  
Outputs go to `.testcase-generator/<op_name>/`.

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
