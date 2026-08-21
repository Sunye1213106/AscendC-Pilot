<task>
基于本次 `tg/init.yaml` 与已给定的 Planning Context，生成 `plan.md` 草稿；不要重新解释自然语言输入，也不要重新做 PR review。
</task>

<input>
- Init: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/tg/init.yaml`
- Planning Context: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/runs/<RUN_ID>/actions/plan_scope/parts/purpose.md`（外加用户意图 / CE plan「测试内容」 / session handoff）。不要假定必须先做过 PR review，也不要在本步再自由查一轮图。
- UO query authority: `<UO_ROOT>`
- Draft: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/runs/<RUN_ID>/actions/plan_fuse`
</input>

<output>
写入本步草稿 markdown：测试范围、精度/功能、性能、覆盖与 solve 判据说明 + 末尾 YAML 义务表。Planning Context 是 `plan_scope/parts/purpose.md`；缺失时返回 `PLAN_SCOPE_REQUIRED`，不要写正式 `tg/plan.md`。
</output>
