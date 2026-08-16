<task>
审查 CE 验证账本中的排除候选，防止未经证明的义务进入 X。
</task>

<input>
- Obligations: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/ce/impact/obligations.yaml`
- Ledger: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/ce/impact/ledger.yaml`
- Residual: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/ce/verify/residual.yaml`
- External evidence: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/ce/verify/external_evidence.yaml`
</input>

<delta_constraints>
1. 先读 `ce/impact/change_capture.yaml`，把 `head_sha` 原样写入 `change_head_sha`；不得复用旧 review。
2. X 只表示“由源码证明不可能触达/不适用”，不是“测试过了”。
3. 每个批准排除必须基于 Tier A 路径，并给出非空 `proof_refs`。
4. 外部 evidence receipt 只能进入 V，不能直接作为 X。
5. 证据不足时 `verdict: reject` 并返回 `OBLIGATION_REWORK`。
6. 不得改写 O/V/X；这里只产出 referee verdict。
</delta_constraints>

<output>
写入 `ce/verify/exclusion_review.yaml`（schema `ce-exclusion-review/v1`）。
每条 `verdicts[]`：`obligation_id`、`verdict`（approve|reject）、`evidence_tier`、`proof_refs`、`reason_codes`。
`change_head_sha` 必须等于 `change_capture.yaml.head_sha`。
</output>
