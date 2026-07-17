# Testcase Agent path hints

`PLUGIN_ROOT` = repository root of `testcase-agent/` (contains `skills/`, `testcase_agent/`, `install.ps1`).

After `./install.ps1 opencode`, the same tree is also linked as:

```text
~/.config/opencode/testcase-agent-plugin  →  PLUGIN_ROOT
~/.config/opencode/skills/tg-plan         →  PLUGIN_ROOT/skills/tg-plan
~/.config/opencode/skills/tg-solve        →  PLUGIN_ROOT/skills/tg-solve
~/.config/opencode/skills/tg-init         →  PLUGIN_ROOT/skills/tg-init   (deprecated)
```

## Commands

| Skill | CLI |
|-------|-----|
| `/tg-plan` | `tg-plan <project_root> --op-name <op> [--level L0\|L1\|L2\|L3] [--topic …]` |
| `/tg-solve` | `tg-solve <project_root> --op-name <op> [--dry-run]` |

`project_root` must contain `.understand-operator/<op_name>/` (pre-built KB).  
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
