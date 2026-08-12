<task>
对指定目标做有源码依据的缺陷审查，并给出逐目标判定。
</task>

<targets>
`<TARGET_IDS_OR_FILES>`
</targets>

<context>
- Project: `<PROJECT_ROOT>`
- UO: `<UO_ROOT>`
- Topic: `<TOPIC>`
- Context pack: `<CONTEXT_PACK_PATH>`

CE 消费已有 CodeMap 做跨层影响与缺陷定位，不重建源码权威。
方法细节见打包 Skill `code-review`。
</context>

<instructions>
1. 先用 Codemap/KB 定位，再读最小必要源码窗口。
2. 只报告有证据支撑的问题；不确定则标 `UNRESOLVED`，禁止猜测。
3. 结论引用 `path:line`（或区间）；可附 CodeMap 节点，但不能替代源码引用。
</instructions>

<output>
每个目标返回其一：`FINDING` | `NO_CONFIRMED_ISSUE` | `UNRESOLVED`，并附简短理由与证据引用。
</output>
