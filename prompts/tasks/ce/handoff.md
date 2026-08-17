<task>
将当前 CE 会话整理为交接文档，供下一窗口继续。
</task>

<context>
- Plan: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/ce/intent/plan.md`
- Todo: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/ce/apply/todo.md`
- Existing handoff: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/ce/session_handoff.md`
</context>

<instructions>
1. 只引用已有产物路径（plan.md、todo.md、后续 slash 命令），不要复制需求或审查正文。
2. 写明后续 slash 命令与未决决策。密钥写成占位。
3. 不要改源码或知识库。不要读 intent.yaml 或 review YAML。
</instructions>

<output>
写入会话交接文档。
</output>
