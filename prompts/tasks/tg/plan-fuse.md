<task>
基于本次 `tg/init.yaml` 与已给定的 Planning Context，生成 `plan.md` 草稿；不要重新解释原始用户 NL，也不要重新做 PR review。
</task>

<input>
- Init: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/tg/init.yaml`
- Planning Context: 当前 Task stub 提供的审查结论 / CE plan「测试内容」 / 用户测试计划 / uo-query 综合 / session handoff；若存在也可读 `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/context/review_planning_context.md`。不要假定必须先做过 PR review。
- UO query authority: `<UO_ROOT>`
- Draft: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/runs/<RUN_ID>/actions/plan_fuse`
</input>

<output>
写入本步草稿 markdown：测试范围、精度/功能、性能、覆盖与 solve 判据说明 + 末尾 YAML 义务表。Planning Context 缺失时返回 `PLAN_CONTEXT_REQUIRED`，不要写正式 `tg/plan.md`。
</output>
