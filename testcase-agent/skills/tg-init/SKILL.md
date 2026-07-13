---
name: tg-init
description: >-
  Initialize TestAgent phase 1 from an existing Understand Operator KB. Use when
  the user runs /tg-init or asks to intake .understand-operator artifacts for
  testcase generation planning.
argument-hint: "<project_root> --op-name <op_name>"
---

# /tg-init

Use this command to initialize TestAgent phase 1 from an existing Understand Operator KB.

Run:

```powershell
tg-init <project_root> --op-name <op_name>
```

Rules:

- Read `.understand-operator/<op_name>/` only.
- Reuse Understand final validation in check-only/read-only mode.
- Export the `testcase-contract` view.
- Write only `.testcase-generator/<op_name>/`.
- Do not call CBM, scan operator source, generate cases, generate CSV, execute kernels, or modify `.understand-operator/`.
