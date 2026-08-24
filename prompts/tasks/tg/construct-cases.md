<task>
为 worklog 围栏里仍 OPEN 的义务构造脚本仓能直接吃的用例行，或交引擎配方。全量 TilingKey 禁止枚举行。
</task>

<input>
- Plan: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/tg/plan.md`
- Init: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/tg/init.yaml`
- Worklog: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/tg/worklog.md`
</input>

<output>
最终消息交回 YAML：`columns` + `rows` 和/或 `recipe`。不要 Write `parts/` 或正式 `tg/cases.*`。

**最终消息正文必须就是 YAML 全文**，Host 只读最终消息，中间消息取不到；不要只交摘要或写「见上文」。

行值类型对齐 `init.yaml` 的 `domains.<col>.profile.inferred_type`：`int` 列交数字不加引号，`enum-string` 列交字符串。从 case 表挑行当基底时 CSV 读出来是字符串，必须转换后再交 —— 引擎 `eq`/`in` 严格比较，`'4' == 4` 为假，类型不对义务会静默 MISS。
</output>
