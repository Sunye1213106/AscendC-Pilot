<task>
请用户确认：覆盖合同是否可以进入「规划测试义务」。
用人话说明目标、刚完成事项、以及选项后果（禁止甩内部字段名）。
</task>

<targets>
`<TARGET_IDS_OR_FILES>`
</targets>

<context>
- Project: `<PROJECT_ROOT>`
- TG: `<TG_ROOT>`

人确认只冻结「是否进入下一步」；不能豁免证据要求。AskQuestion 文案由控制面按人话合同生成。
</context>

<instructions>
1. Host 弹出 AskQuestion（选项原样使用控制面返回）。
2. 选「确认进入规划」后才能完成本步；返工/停止则不要完成本步。
3. 对用户转述只用意图/刚完成/下一步，禁止粘贴审计黑话。
</instructions>

<output>
写入 `tg/init/confirmation.yaml`（及同合同的 status / fingerprint）后由主控完成本步；未确认则保持在确认阶段。
</output>
