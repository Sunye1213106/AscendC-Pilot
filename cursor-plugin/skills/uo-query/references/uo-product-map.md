# 查询产品地图

短地图：认清权威 → 调用 Cursor MCP `uo_query`（或 OpenCode `pilot_cli` `uo-query`）→ 查询完成后立即作答。简单查询直接调用；复杂查询同一轮委派。禁止 `pilot_run`。怎么查、Claim 分层、空结果纪律见 `skills/uo-query/SKILL.md`。

同一查询目标可沿图继续调用（跟卡片 `next`）。是否并行委派见 `pilot/policies/invariants/intent-reasoning.md`。

## 权威分层

| 层 | 是什么 | 不是什么 |
| --- | --- | --- |
| **正式产品** | 已 commit 的 `.ascendc-pilot/<arch>/uo/<op>.<arch>.uo` | LLM 记忆、未校验草稿 |
| **图** | `entity` / `relation` / `source_span` | 任何可重建索引本身 |
| **加速投影** | 查询用的派生视图 | 独立事实源；过期由 engine 回退正式产品 |

无法验证 freshness 时不得当作 fresh。

## 日常任务 → 调用形态

按手头任务选最短查询。TilingKey / Kernel / unresolved 分开查，不要一次扩到 full reachability。配对、时序、仿真、sanitizer **不在 UO**。

| 任务 | 先调用 | 再补 | UO 不回答 |
| --- | --- | --- | --- |
| 名字 / 定义 / 字段写读 | 标识符（卡片含边与写读） | `--file --line` | 长报告 |
| 模板能否编过 / kernel 是否注册 | `Dim=V` | 维名见无参数索引 | 运行时日志解读 |
| 卡死 / Host schedule | 标识符（Host 调用点在卡片上） | 无参数索引看 launch 阶段 | happens-before、测量 |
| 多阶段 launch | 无参数索引 | 跟 PIPE 名再查 | 把内层函数名当阶段 |
| 从已知位点看语句 | `--file --line`（语句窗） | 卡片 `next` | Git / PR |
| UT / 白盒线索 | `Dim=V` + 字段名 | 无参数索引的 gaps 计数 | 生成完整 ST 矩阵 |

Worked example（**non-normative**）：标识符 → 看 `sel_sites` / `edges.*.count` → 若 count > 已列出再查或 PARTIAL → `--file --line` 看语句 → verdict。
