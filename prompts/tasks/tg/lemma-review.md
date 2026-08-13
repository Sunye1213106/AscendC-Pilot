<task>
回放并裁决本轮 producer 提交的引理证书（轮内 expected-growth rejects，不是搜完清理）。
</task>

<targets>
`<TARGET_IDS_OR_FILES>`
</targets>

<context>
- Project: `<PROJECT_ROOT>`
- TG: `<TG_ROOT>`

证据以当前 Action bundle/session 声明的 evidence pack 与 producer certificates 为准，并对照当前 R 与最新 `round_analysis.yaml` / reject 观察。
方法细节见打包 Skill `source-proof`（由该 Skill 选择所需 referee-replay 参考，勿假设 Host 物理路径）。
</context>

<instructions>
1. 只做 replay 裁决，不开启新假设。
2. 把“搜索未命中”或“裸 Host reject”当成不可达的证书一律 `reject`。
3. 证据不足时 `defer`，禁止用猜测补全证明链。
</instructions>

<output>
每个候选返回 `accept` | `reject` | `defer`，并附简短理由。写入 `runs/<RUN_ID>/actions/lemma_review/review.yaml`。
</output>
