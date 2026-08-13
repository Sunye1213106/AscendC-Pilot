<task>
按 CE obligation 做有源码依据的验证审查，并给出逐义务判定。
</task>

<context>
- Obligations: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/ce/impact/obligations.yaml`
- Impact slice: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/ce/impact/impact_slice.yaml`
- Project: `<PROJECT_ROOT>`
- UO: `<UO_ROOT>`

CE 消费已有 CodeMap 做跨层影响与缺陷定位，不重建源码权威。
</context>

<instructions>
1. 先按 obligation anchor 查询 CodeMap，再读最小必要源码窗口。
2. `NO_CONFIRMED_ISSUE` 不是验证证据，不得关闭 obligation。
3. 只有 closure requirement 可由静态源码证明满足时，才可输出 `VERIFIED`；runtime/external obligation 必须保持 `UNRESOLVED`。
4. 每条 `VERIFIED` 必须带非空 `evidence_refs`（`path:line` 或区间）和 `evidence_tier` A/B。
5. 不确定内容标记 `UNRESOLVED`，禁止猜测。
</instructions>

<output>
写入 `ce/verify/code_review.yaml`，严格使用：

```yaml
schema: ce-code-review-evidence/v1
reviewer_id: ce-reviewer
verified_obligations:
  - obligation_id: <id>
    verdict: VERIFIED
    evidence_tier: A
    evidence_refs:
      - path/to/file.h:10-20
findings: []
unresolved_obligations: []
```

不得输出 `excepted_obligations`；排除只由 `ce-change-referee` 处理。
</output>
