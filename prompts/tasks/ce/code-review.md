<task>
按 CE obligation 做有源码依据的验证审查，并给出逐义务判定。
</task>

<context>
- Obligations: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/ce/impact/obligations.yaml`
- Impact slice: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/ce/impact/impact_slice.yaml`
- Project: `<PROJECT_ROOT>`
- UO: `<UO_ROOT>`

方法见 session `method.md`（`code-review/verify-review`）。
</context>

<constraints>
排除只由 `ce-change-referee` 处理。审查叙述不能充当测量收据。
</constraints>

<output>
写入 `ce/verify/code_review.yaml`（schema `ce-code-review-evidence/v1`），含 `change_head_sha`、`verified_obligations`、`findings`、`unresolved_obligations`。
</output>
