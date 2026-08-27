<task>
为 OPEN 义务交回 `schema: tg-solve-fill/v1`。不要手写义务条数，不要枚举行，不要宣布 HIT。
</task>

<input>
- Plan: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/tg/plan.md`
- Init: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/tg/init.yaml`
- Solve index（引擎已展开）：`<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/tg/solve_index.yaml`
</input>

<delta_constraints>
1. 只填 `baseline` / `hits` / 可选 `guard_witnesses`。不要写 `columns` / `rows` / `unreachable`。
2. 身份字段由框架写入。不要 Write 正式产物。
</delta_constraints>

<output>
最终消息正文就是 `schema: tg-solve-fill/v1` YAML 全文。不要 Write。
</output>
