<task>
基于 `tg/init.yaml` 与 Primary 转述的 scope 回答，交回覆盖模型 YAML（Dimension / classifier / L0–L3）。不要写 `plan.md` 散文，不要 Write。
</task>

<input>
- Init: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/tg/init.yaml`
- Scope answer: Host 注入的上一窗自然语言（不是磁盘 YAML 文件）
- UO query authority: `<UO_ROOT>`
</input>

<output>
最终消息只交 `schema: tg-plan/v3` 的 YAML（可围栏）。禁止写「测什么 / 覆盖什么 / 怎么判定」三节散文（那是 Primary 的）。不要 Write staging / parts / 正式 `tg/plan.md`。
</output>
