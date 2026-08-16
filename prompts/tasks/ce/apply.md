<task>
对照已确认的变更意图和锚点，修改算子源码。
</task>

<context>
- Intent: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/ce/intent/intent.yaml`
- Features: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/ce/intent/feature_decomposition.yaml`
- Anchors: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/ce/intent/anchors.yaml`
- Project: `<PROJECT_ROOT>`
</context>

<instructions>
1. 只改锚点覆盖的 `op_host/` / `op_kernel/` 文件。
2. 每个改动留下路径与行号。一次一个垂直切片。
3. 不要写知识库，不要宣布验证已通过。
4. 写入 `ce/apply/patch_notes.yaml`，列出改了哪些路径。
</instructions>

<output>
修改源码，写入 `ce/apply/patch_notes.yaml`，并写明改了哪些路径。
</output>
