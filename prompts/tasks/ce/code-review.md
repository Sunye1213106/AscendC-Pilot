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
1. 先读取 `ce/impact/change_capture.yaml`，将 `head_sha` 原样写入 `change_head_sha`；不得猜测或复用旧 SHA。
2. 先按 obligation anchor 查询 CodeMap，再读最小必要源码窗口。
3. `NO_CONFIRMED_ISSUE` 不是验证证据，不得关闭 obligation。
4. 只有 closure requirement 可由静态源码证明满足时，才可输出 `VERIFIED`；runtime/external obligation（dispatch 复测、精度、性能、卡死复现）必须保持 `UNRESOLVED`，等 `ce-external-evidence/v1` 测量收据。
5. 每条 `VERIFIED` 必须带非空 `evidence_refs`（`path:line` 或区间）和 `evidence_tier` A/B。
6. 不确定内容标记 `UNRESOLVED`，禁止猜测。审查叙述不能充当 UT/ST/精度/profiling 收据。
</instructions>

<output>
写入 `ce/verify/code_review.yaml`，严格使用：

```yaml
schema: ce-code-review-evidence/v1
change_head_sha: <ce/impact/change_capture.yaml.head_sha>
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
