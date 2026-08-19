<task>
对当前绑定的 git/PR diff 做只读代码审查；除 findings 外，汇总后给后续 TG 一段可直接消费的 Planning Context。
</task>

<context>
- Project: `<PROJECT_ROOT>`
- UO: `<UO_ROOT>`
- Current phase: session `current_phase`（scope / review）
- Plan (if present): `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/ce/plan/*_plan.md`
- Change index: `runs/<RUN_ID>/actions/change_capture/index.md`
- Optional UO hints: `runs/<RUN_ID>/actions/change_capture/uo_hints.md`
- Optional hunk windows: `runs/<RUN_ID>/actions/change_capture/hunks/`

本入口不写 ce/review。稳定审查方法、取证顺序与反证规则见 session `method.md`（`code-review/standalone-review`）。
</context>

<output>
在 Task 回复中给出 `path:line` findings。双轴齐了之后 Primary 对人说的结构必须是：审查完成；这个 PR 做什么；改了哪些文件；问题 1/2/3…；要测的变量（字段与取值）。不要把内部轴标记表当作用户正文。不要写 yaml 或新的 CE 正式产品。
</output>
