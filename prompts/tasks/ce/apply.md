<task>
对照已确认的变更计划，修改算子源码。
</task>

<context>
- Plan: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/ce/intent/plan.md`
- Todo: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/ce/apply/todo.md`
- Project: `<PROJECT_ROOT>`
</context>

<instructions>
1. 只改 `op_host/` / `op_kernel/` / `common/`。超出本次切片的文件不要写。
2. 先读 `plan.md` 与 `todo.md`。一次只做一个未勾选垂直切片，每个改动留下路径与行号。
3. 不要写知识库，不要改 `ce/intent/plan.md`，不要宣布验证已通过。
4. 不要读 intent.yaml / feature_decomposition / anchors YAML。勾选 `todo.md` 对应项，写入 `ce/apply/patch_notes.yaml`，列出改了哪些路径以及对齐了哪条 plan / todo。
</instructions>

<output>
修改源码，写入 `ce/apply/patch_notes.yaml`，并写明改了哪些路径。
</output>
