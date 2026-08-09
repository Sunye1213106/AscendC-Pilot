<task>
只解决 `prepare` 确定性扫描留下的 operator scope / architecture 歧义。
</task>

<context>
`prepare` 已完成候选发现。若 receipt 表明范围唯一或已自动接受，不要重新选择；只有明确的多候选、根目录冲突或 architecture 不确定时才需要判断。
</context>

<instructions>
1. 比较 bundle 中的候选路径、architecture 和确定性 evidence。
2. 选择能完整覆盖当前 operator 的最小源码范围，排除明显的其他算子或其他 architecture。
3. 若现有证据仍不能唯一决定，向用户询问唯一缺失的选择，不进行 Host/Kernel 语义分析。
4. 不手工构造源码清单，不绕过 `acp uo-scope` / prepare 的候选结果。
</instructions>

<output>
只提交当前 `uo-prepare-v1` 合同需要的 scope / BuildVariant 决策；不要执行 extract、analyze 或 resolve。
</output>
