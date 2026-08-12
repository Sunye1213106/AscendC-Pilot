<task>
审计 TG init 的缺口与阻塞项，按可处置方式分类。
</task>

<targets>
`<TARGET_IDS_OR_FILES>`
</targets>

<context>
- Project: `<PROJECT_ROOT>`
- TG: `<TG_ROOT>`
- UO: `<UO_ROOT>`

Init 要把覆盖义务建立在新鲜、完整的 UO 之上；审计只分类缺口，不擅自改契约或跳过证据。
方法细节见打包 Skill `testcase-generation`（audit）。
</context>

<instructions>
1. 对照当前 TG init 产物与 UO 就绪状态，列出 gaps / blockers。
2. 每个 gap 归为：`auto-fixable` / `needs human` / `needs UO rebuild`。
3. 证据不足时保留为 blocking，禁止用猜测“修掉”。
</instructions>

<output>
输出分类后的 gap 清单与简短依据；写入 Action 声明的 audit 报告路径。
</output>
