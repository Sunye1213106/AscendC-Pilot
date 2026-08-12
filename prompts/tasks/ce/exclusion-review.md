<task>
审查 CE 验证账本中的排除项，防止未经证明的义务进入 X。
</task>

<context>
- Ledger: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/ce/impact/ledger.yaml`
- Residual: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/ce/verify/residual.yaml`
- External evidence: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/ce/verify/external_evidence.yaml`
</context>

<instructions>
1. 每个排除项必须有明确理由、范围和可复核证据。
2. 外部证据仅在 schema 与声明路径有效时可用。
3. 证据不足时拒绝排除并返回 `OBLIGATION_REWORK`。
</instructions>

<output>
写入 `ce/verify/exclusion_review.yaml`，包含逐义务 verdict、证据引用、reason_codes 和 `referee_id`。
</output>
