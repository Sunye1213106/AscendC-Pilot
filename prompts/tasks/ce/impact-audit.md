<task>
独立审计 CE 影响切片、风险分类与验证义务账本。
</task>

<context>
- Impact root: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/ce/impact`
- UO product root: `<UO_ROOT>`
- Run: `<RUN_ID>`
</context>

<instructions>
1. 核对变更锚点与最小源码窗口，禁止以 CodeMap 节点替代源码证据。
2. 检查每个风险类是否有对应义务，且 O/V/X/Open 集合一致。
3. 发现缺漏时返回 `OBLIGATION_REWORK`，不得直接改写确定性账本。
</instructions>

<output>
写入 `ce/impact/audit_report.yaml`，包含 `status`、`reason_codes`、`findings`、`source_citations` 和 `referee_id`。
</output>
