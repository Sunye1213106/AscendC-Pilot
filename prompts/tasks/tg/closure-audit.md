<task>
审计当前 TilingKey closure 是否达到可 certify 状态。
</task>

<targets>
`<TARGET_IDS_OR_FILES>`
</targets>

<context>
- Project: `<PROJECT_ROOT>`
- TG: `<TG_ROOT>`

Closure 只能由 Replay confirmed 或经审查的 exclusion proof 正式关闭。审计检查就绪性，不发明新的 exclusion 规则。
方法细节见打包 Skill `testcase-generation`（closure-safety 相关参考由其按需加载）。
</context>

<instructions>
1. 核对义务账本、证据引用与未闭合 residual。
2. 发现证据链断裂、规则越权或目标集被静默扩大时驳回。
3. 不新增 exclusion 规则，不把搜索失败当作不可达。
</instructions>

<output>
返回 `PASS` 或 `REJECT`，并列出关键理由。写入 `runs/<RUN_ID>/actions/closure_audit/review.yaml`。
</output>
