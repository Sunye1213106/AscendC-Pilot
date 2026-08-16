<task>
审计 TG Init 产物：按 tilingkey 全覆盖 checklist 出具 `init/audit_report.yaml`。
顶层 `status` 只能是 `pass` 或 `fail`。
</task>

<context>
- Project: `<PROJECT_ROOT>`
- TG: `<TG_ROOT>`
- UO: `<UO_ROOT>`
- Op: `<OP_NAME>`
- Architecture: `<ARCHITECTURE>`

方法见 session `method.md`（`testcase-generation/tg-init-audit`）。
</context>

<constraints>
全覆盖确定性模式下空 `reads` / 空 `exactness` 不是 blocker。禁止 `conditional_pass`。
</constraints>

<output>
写入本步声明的 audit 报告路径：`version`、`status: pass|fail`、`checks[]`、`blockers`、`warnings`。
</output>
