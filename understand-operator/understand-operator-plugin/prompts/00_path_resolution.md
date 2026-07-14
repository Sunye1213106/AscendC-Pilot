# Path Resolution

Never search the whole disk for Understand Operator scripts. In particular,
do not run recursive `C:\` scans.

Resolve paths from the active skill/plugin location:

1. `SCRIPT_DIR` is the directory containing `prepare_operator.py`.
   Expected OpenCode path:
   `~/.config/opencode/skills/understand-operator`.
2. `PLUGIN_ROOT` is the installed plugin root containing `prompts/` and
   `agents/`. Expected OpenCode path:
   `~/.config/opencode/understand-operator-plugin`.
3. `PROMPT_DIR` is `$PLUGIN_ROOT/prompts`.
4. `PROJECT_ROOT` is the target operator repository, never the OpenCode config
   directory and never the Understand Operator plugin directory.
5. `UO_ROOT` is `$PROJECT_ROOT/.understand-operator/$OP_NAME`.

If a required script or prompt is missing, stop and ask the user to reinstall:

```powershell
.\understand-operator\install.ps1 opencode
```

Do not recover by scanning outside the known skill/plugin roots.
