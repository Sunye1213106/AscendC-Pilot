<task>
对当前绑定的 git/PR diff 做只读代码审查；除 findings 外，汇总后给后续 TG 一段可直接消费的 Planning Context。
</task>

<context>
- Project: `<PROJECT_ROOT>`
- UO: `<UO_ROOT>`
- Current phase: session `current_phase`（scope / review）
- Plan (if present): `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/ce/plan/*_plan.md`
- Diff: 引擎内存捕获；可选 `runs/<RUN_ID>/actions/change_capture/diff.md`

本入口不写 ce/review。稳定审查方法见 session `method.md`（`code-review/standalone-review`）。
</context>

<output>
在 Task 回复中给出 `path:line` findings。双轴汇总必须附一段 `TG Planning Context`，包含 changed_scope / affected_scope / risks / test_intent / validation_targets，供后续 `/tg-plan` 与 `tg/init.yaml` 合并。不要写 yaml 或新的 CE 正式产品。
</output>
