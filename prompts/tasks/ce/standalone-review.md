<task>
对当前修改做只读代码审查。输入只有 git/PR diff。
</task>

<context>
- Project: `<PROJECT_ROOT>`
- UO: `<UO_ROOT>`
- Current phase: session `current_phase`（scope / review）
- Plan (if present): `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/ce/plan/*_plan.md`
- Diff: 引擎内存捕获；可选 `runs/<RUN_ID>/actions/change_capture/diff.md`

本入口不写 ce/review。方法见 session `method.md`（`code-review/standalone-review`）。
</context>

<constraints>
无 diff 则停。Spec / Standards 由并行隔离子代理做。结论写在 Task 回复（`path:line`）。不要写 `ce/**`。不要合成 LGTM。
语义只用 `uo-query` 形态 3 再形态 1。不要 `acp uo impact` / `explain-*`。
</constraints>

<output>
在 Task 回复中给出 `path:line` 结论。不要写 yaml。
</output>
