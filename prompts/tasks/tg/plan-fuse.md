<task>
基于本次 `tg/init.yaml` 与已给定的独立测试变量，生成 `plan.md` 草稿：求解方向 + 观测 + L0–L3。
</task>

<input>
- Init: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/tg/init.yaml`
- Planning Context: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/runs/<RUN_ID>/actions/plan_scope/parts/targets.yaml`（外加用户意图 / CE plan「测试内容」 / session handoff）
- UO query authority: `<UO_ROOT>`
- Draft: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/runs/<RUN_ID>/actions/plan_fuse`
</input>

<output>
写入本步草稿 markdown。缺失 Planning Context 时返回 `PLAN_SCOPE_REQUIRED`。不要写正式 `tg/plan.md`。
</output>
