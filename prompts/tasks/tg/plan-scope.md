<task>
弄清这次要测什么。像 uo-query：读对话和 `tg/init.yaml`，用自然语言回答。禁止 Write，不要交 YAML 文件。
</task>

<input>
- Init: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/tg/init.yaml`
- Optional intent: 用户这句话、`ce/plan/*_plan.md`、`session_handoff.md`
- Pin: `<PROJECT_ROOT>/.ascendc-pilot/control/change_contract.yaml`（只读）
- UO: `<UO_ROOT>`（只查询，不写）
</input>

<output>
最终消息直接回答：测哪条实现行为、什么条件下成立/不成立、还缺什么证据。

必须包含四项（缺一项 fuse 就只能靠猜）：
- **A 可控面**：逐列读 init.yaml 的 `control.status` / `confidence`，给出「`confirmed`+`active` 可做确定 classifier 的列」集合。
- **B 触发门禁**：主行为成立条件写成合取式，逐项标注由哪个列控制、该列 confidence，或标明是「非列」（平台常量 / 环境值 / 内部派生量）。拆到列级。
- **C 可达性**：现有 case 表里同时满足 B 全部合取项的行数，答具体数字；为 0 就说 0，并指出缺哪几项。
- **D 新增 vs 既有**：本次改动引入的符号 与 同文件里原本就有的符号分开说；判不准标「未证实」。

改动文件只作方向线索。允许取符号级变更摘要判定新增/既有，禁止按 diff 行铺覆盖清单，禁止 `git diff HEAD`（PR checkout 工作区干净，该命令无意义）。

记住载体分工：Replay 出 evidence（TilingKey / TilingData 字段），测试脚本仓只出 oracle（精度 / md5）。测试脚本仓看不到 tiling 字段不等于该字段不可观测。

不要 Write，不要交 `targets.yaml` / `plan.md`。Primary 读你的回答即可。

**最终消息的正文必须就是完整回答本身。** Host 只读最终消息，中间消息取不到。不要只交摘要，不要写「见上文」/「已在上面给出」。
</output>
