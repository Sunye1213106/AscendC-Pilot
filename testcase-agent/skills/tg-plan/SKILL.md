# /tg-plan

Use this command to build the phase 1 coverage plan from a frozen TestAgent snapshot.

Run:

```powershell
tg-plan <project_root> --op-name <op_name>
```

After it completes, stop for human review. In OpenCode, prefer a `question` selection with:

- `approve`: allow phase 2
- `revise`: modify coverage plan
- `supplement`: add human test focus
- `stop`: stop

Human supplements must be written to `.testcase-generator/<op_name>/plan/human_supplement.yaml`. Do not modify Understand Canonical KB.
