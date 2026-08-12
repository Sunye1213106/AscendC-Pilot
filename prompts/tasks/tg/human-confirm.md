<task>
确认机器无法安全自动决定的 init 边界（范围 / 模式 / 例外）。
</task>

<targets>
`<TARGET_IDS_OR_FILES>`
</targets>

<context>
- Project: `<PROJECT_ROOT>`
- TG: `<TG_ROOT>`

人确认只冻结边界选择，不能豁免证据要求；未确认项必须继续阻塞。
方法细节见打包 Skill `testcase-generation`（human-confirm）。
</context>

<instructions>
1. 只确认 scope / mode / exceptions 等边界项。
2. 不要用确认去“放行”缺失证据或未闭合义务。
3. 歧义未消除则保持 unconfirmed。
</instructions>

<output>
记录已确认项；未确认项保持 blocking。
</output>
