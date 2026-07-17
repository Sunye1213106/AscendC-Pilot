---
name: tg-plan
description: >-
  Intake Understand KB, extract generation conditions, and build L0–L3 coverage
  plan. Use when the user runs /tg-plan or asks to plan testcase generation.
argument-hint: "<project_root> --op-name <op_name> [--level L0|L1|L2|L3] [--topic <id>] [--focus \"<scope>\"]"
---

# /tg-plan

Intake + extract + coverage plan in one command (no separate tg-init).

Resolve install paths from `skills/PATHS.md` (or `~/.config/opencode/testcase-agent-plugin` after install).

```powershell
tg-plan <project_root> --op-name <op_name> --level L1
tg-plan <project_root> --op-name <op_name> --level L3 --topic determinism
```

`<project_root>` must contain pre-built `.understand-operator/<op_name>/`.

Levels:

- `L0`: functional-attribute smoke (all independent feature attributes / families / paths / dtype / optional inputs) — not a single minimal case.
- `L1`: runtime/functional/boundary/reject coverage.
- `L2`: exhaustive reachable TilingKey.
- `L3`: topic-only suite (`--topic` required).

Outputs worth reading:

- `plan/review.md` — design rationale + 测试点覆盖明细（覆盖什么/多少条）
- `plan/levels/<level>/` — per-level archive (L0 and L1 do not overwrite each other)
- `plan/coverage_matrix.yaml` — includes `test_points`

If `extract/EXTRACT_GAP.yaml` appears, optionally write LogicExpr patches to `extract/llm_patches.yaml` and re-run `tg-plan`. Do not invent CSV rows.

## HARD STOP — human review (AskQuestion buttons)

After `tg-plan` completes, **stop**. Do **not** auto-approve and do **not** run `tg-solve` until the user decides.

1. Summarize `plan/review.md` for the user (level design, test-point counts, blockers).
2. Use the runtime **AskQuestion / question UI** so the user sees buttons. Present exactly these choices:

   - `approve` — 批准，并**立即**执行 `tg-solve`
   - `reject` — 拒绝当前计划，结束流程
   - `suggest` — 给出修改建议（调整后重跑 `tg-plan` 再审阅）

   Only fall back to printing the CLI command when the button UI is unavailable.
3. After the user chooses, record the decision:

```powershell
python -X utf8 -m testcase_agent.review_checkpoint <project_root> --op-name <op_name> --decision <approve|reject|suggest> [--notes "..."]
```

Decision effects:

- `approve` — write `decision: approve` + current `snapshot_hash` / `plan_hash` / `approved_at`，然后**立刻**运行：

```powershell
tg-solve <project_root> --op-name <op_name>
```

- `reject` — 写入拒绝状态，结束本次 workflow（不要跑 `tg-solve`）。
- `suggest` — 把用户修改建议写入 `--notes`（或继续追问补全），按建议调整 focus/level/patches 后重跑 `tg-plan`，再 AskQuestion 审阅。不要直接 `tg-solve`。

Never invent a silent `approve`. Do not modify Understand Canonical KB.
