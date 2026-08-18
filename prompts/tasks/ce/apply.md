<task>
对照当前计划 markdown 的未完成 todo，修改算子源码。
</task>

<context>
- Plan: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/ce/plan/` 下当前 `{slug}_plan.md`
- Project: `<PROJECT_ROOT>`
</context>

<instructions>
1. 只改 `op_host/` / `op_kernel/` / `common/` / `test_script/`。超出本次 todo 的文件不要写。
2. 一次只做一个未勾选 todo，每个改动留下路径与行号。
3. 不要写知识库，不要写 yaml，不要宣布验证已通过。
4. 做完勾选该计划文件里对应的 `- [x]`。
</instructions>

<output>
修改源码，并勾选当前计划 markdown 的对应 todo。
</output>
