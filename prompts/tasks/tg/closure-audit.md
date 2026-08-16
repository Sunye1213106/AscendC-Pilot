<task>
审计当前 TilingKey closure 是否达到可 certify 状态。
</task>

<input>
- Targets: `<TARGET_IDS_OR_FILES>`
- Project: `<PROJECT_ROOT>`
- TG: `<TG_ROOT>`
Closure 只能由 Replay confirmed 或经审查的 exclusion proof 正式关闭。
</input>

<delta_constraints>
1. 核对义务账本、证据引用与未闭合 residual。
2. 发现证据链断裂、规则越权或目标集被静默扩大时驳回。
3. 不新增 exclusion 规则，不把搜索失败当作不可达。
</delta_constraints>

<output>
返回 `PASS` 或 `REJECT`，并列出关键理由。
写入本 Action 的 `review.yaml`。
</output>
