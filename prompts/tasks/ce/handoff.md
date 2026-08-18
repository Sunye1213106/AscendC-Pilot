<task>
将当前会话整理为交接文档，供下一窗口继续。
</task>

<context>
- Plan dir: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/ce/plan/`
- Existing handoff: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/session_handoff.md`
</context>

<instructions>
1. 只引用已有产物路径（`{slug}_plan.md`、tg 文件、后续 slash），不要复制需求或审查正文。
2. 必须有 `next:` 一条 slash。若下一跳是 `/tg-plan`，用散文写下该测什么。
3. 密钥写成占位。不要改源码或知识库。不要写 yaml。
</instructions>

<output>
写入 `.ascendc-pilot/<ARCHITECTURE>/session_handoff.md`。
</output>
