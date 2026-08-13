<task>
对本轮 Round Analysis 给出的源码引理线索做证明或反驳（轮内 claim，不是搜完后的清理）。
</task>

<targets>
`<TARGET_IDS_OR_FILES>`
</targets>

<context>
- Project: `<PROJECT_ROOT>`
- UO: `<UO_ROOT>`
- TG: `<TG_ROOT>`

权威闭合证据只有 Host Replay（R）与经审查的源码引理（E）。搜索失败或裸 Host reject 本身不等于不可达。
方法细节见打包 Skill `source-proof`；遵守当前 Action 的 output contract / session 字段。
</context>

<instructions>
1. 只处理 closed lead pack 中的线索，禁止发明新 lead；有 companion evidence pack 时一并使用。
2. 优先对照最新一轮 Host `refuse` / rewrite 观察与 `round_analysis.yaml` 模式。
3. 主动寻找反例；闭合所需 proof obligations。
4. 不得把 missing / search failure / replay reject 单独升级为 exclusion。
</instructions>

<output>
每个候选给出 `PROVED` | `REFUTED` | `INSUFFICIENT`，并附源码窗口证据。
只写入本 Action 的 `parts/` 草稿，不要写正式 closure IR。
</output>
