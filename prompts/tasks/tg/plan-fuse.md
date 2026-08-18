<task>
基于本次 `tg/init.yaml` 与已给定的 Planning Context，生成 `plan.md` 草稿；不要重新解释原始用户 NL，也不要重新做 PR review。
</task>

<input>
- Init: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/tg/init.yaml`
- Planning Context: 当前 Task 上下文中来自 `/ce-review`、`/ce-plan`、用户显式测试计划或 session handoff 的已确定测试意图
- UO query authority: `<UO_ROOT>`
- Draft: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/runs/<RUN_ID>/actions/plan_fuse`
</input>

<output>
写入本步草稿 markdown：测试范围/精度/性能/覆盖/solve 判据说明 + 末尾 YAML 义务表。Planning Context 缺失时返回 `PLAN_CONTEXT_REQUIRED`，不要写正式 `tg/plan.md`。
</output>
