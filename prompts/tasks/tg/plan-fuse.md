<task>
基于本次 `tg/init.yaml` 与已给定的 Target model，生成完整 `plan.md` 正文：语义 Dimension partitions、结构化谓词、L0–L3。
</task>

<input>
- Init: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/tg/init.yaml`
- Planning Context: Host 注入的上一窗 session 捕获（外加用户意图 / CE plan「测试内容」 / session handoff）。不是磁盘 `targets.yaml`。
- UO query authority: `<UO_ROOT>`
</input>

<output>
最终消息交回完整 `plan.md`（散文三节：测什么 / 覆盖什么 / 怎么判定，然后 `schema: tg-plan/v3` YAML 围栏）。缺失 Planning Context 时返回 `PLAN_SCOPE_REQUIRED`。不要 Write staging / parts / 正式 `tg/plan.md`。
</output>
