<task>
审计 TG Init 产物：按 tilingkey 全覆盖 checklist 出具 `init/audit_report.yaml`。
顶层 `status` 只能是 `pass` 或 `fail`（禁止 conditional_pass / 嵌套 verdict.status）。
</task>

<targets>
`<TARGET_IDS_OR_FILES>`
</targets>

<context>
- Project: `<PROJECT_ROOT>`
- TG: `<TG_ROOT>`
- UO: `<UO_ROOT>`
- Op: `<OP_NAME>`
- Architecture: `<ARCHITECTURE>`

方法细节见 session 物化的 `method.md`（Skill `tg-init-audit` METHOD）与
`agents/references/init-audit-schema.md`。
</context>

<instructions>
1. 对照 init/realization 产物，对下列 id 逐条给出 `pass|fail`：
   `tilingkey_contract`, `declared_set_nonempty`, `binding_inventory`,
   `host_view_aligned`, `graph_fingerprint`, `integrity_gate`。
2. 全覆盖确定性模式下：绑定项的空 `reads` / 空 `exactness` **不是** blocker，不得因此 `fail`。
3. 真实缺失（合同空、声明集空、指纹不一致、完整性产物缺失等）才 `fail` 并写入 `blockers`。
4. 证据不足时对该 id 标 `fail` 并说明缺什么；禁止用猜测“修掉”。
5. 写入 Action 声明的 audit 报告路径；完成后短摘要即可，禁止 finalize。
</instructions>

<output>
```yaml
version: 1
status: pass | fail
checked_at: <iso>
op_name: <op>
checks:
  - { id: <checklist_id>, status: pass|fail, detail: "..." }
blockers: []
warnings: []
next: "acp run-action human_confirm"
```
</output>
