# Infer scenarios from a named plan

**When to load**：写 `{slug}_plan.md` 的「测试内容」节，或 TG 从该节总结义务时。

CE **不写** `ce-scenario-set/v1` 或任何场景 yaml。合法 `P-*` / `F-*` id 仍以 `references/scenario-catalog.md` 为准；若计划里点名这些 id，`/tg-plan` 自己读 catalog 并 root 到脚本列。Agent **不得发明 id**。

## 计划里怎么写

用散文写清应覆盖的字段/开关与不要做的范围，例如：确定性 on/off、band 调度启用 vs DISABLED。需要精确 id 时从 catalog 抄，不要静默扩成全部合法 Key。

截断查询或 stale UO 是披露边界，不是「没有精度/性能影响」。
