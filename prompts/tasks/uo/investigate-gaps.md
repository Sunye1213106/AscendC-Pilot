<task>
显式诊断当前 unresolved CodeMap semantic residuals：分类根因，指出确定性引擎还缺什么能力。不要用于普通语义查询。
</task>

<context>
- Blockers: `uo/ir/unresolved.yaml` 与当前 bundle 指定的 blocker ids
- UO: `<UO_ROOT>`
方法细节见 session method（`uo-investigate`）。
</context>

<output>
只写调查报告：`uo/ir/gap_investigation.yaml` 与 Action 声明的 `report.yaml`。
不修改 canonical `.uo` / UO IR 产品面。
</output>
