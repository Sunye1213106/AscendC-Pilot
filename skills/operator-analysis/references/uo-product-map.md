# UO Product Map（progressive）

短地图：认清权威 → 调用 `pilot_cli` `uo-query` → 查询完成后立即作答。简单查询直接调用；复杂查询同一轮委派。禁止 `pilot_run`。怎么查见 `capabilities/uo-query/METHOD.md`。

同一查询目标可沿图继续调用（跟卡片 `next`）。是否并行委派见 `routing/uo-query.md`。

## 权威分层

| 层 | 是什么 | 不是什么 |
| --- | --- | --- |
| **正式产品** | 已 commit 的 `.ascendc-pilot/<arch>/uo/<op>.<arch>.uo` | LLM 记忆、未校验草稿 |
| **图** | `entity` / `relation` / `source_span` | 任何可重建索引本身 |
| **加速投影** | 查询用的派生视图 | 独立事实源；过期由 engine 回退正式产品 |

无法验证 freshness 时不得当作 fresh。

## Claim 层级（不静默扩大）

1. **domain** — 声明域允许什么值
2. **template-admissible** — 编译期模板/宏是否接纳
3. **host-produced** — Host 在何条件下写出
4. **kernel-consumed** — Kernel 是否消费
5. **full reachability** — 端到端可达（常需 TG）

主问只需 1–3 时不要扩展到第 5 层。不同层级分开说，不能用 Host 不产生去否定「模板可接纳」。

## 日常任务 → 调用形态

按手头任务选最短查询。配对、时序、仿真、sanitizer **不在 UO**。

| 任务 | 先调用 | 再补 | UO 不回答 |
| --- | --- | --- | --- |
| 名字 / 定义 / 字段写读 | 标识符（卡片含边与写读） | `--file --line` | 长报告 |
| 模板能否编过 / kernel 是否注册 | `Dim=V` | 维名见无参数索引 | 运行时日志解读 |
| 卡死 / Host schedule | 标识符（Host 调用点在卡片上） | 无参数索引看 launch 阶段 | happens-before、测量 |
| 多阶段 launch | 无参数索引 | 跟 PIPE 名再查 | 把内层函数名当阶段 |
| 从已知位点扩邻居 | `--file --line` | 卡片 `next` | Git / PR |
| UT / 白盒线索 | `Dim=V` + 字段名 | 无参数索引的 gaps 计数 | 生成完整 ST 矩阵 |

`source_span` 或查询返回的带行号 `snippet` **视为已 Read**。覆盖类 `dim_coverage` / `total_matched` 是全集。缺语义用 `PARTIAL` / `UNKNOWN`。空结果按 `hint` 用更短名字再查一次，禁止仓级 findstr。

## 按需域文档

| 域 | 文档 |
| --- | --- |
| TilingKey / packing | `uo-key.md` |
| TilingData 字段写读 | `uo-tilingdata.md` |
| Kernel 分支 | `uo-kernel.md` |
| Template / BuildVariant | `uo-template.md` |
| Buffer | `uo-buffer.md` |
| unresolved | `uo-gaps.md` |
| 场景 query 钩子 | `uo-scenario-hooks.md` |

Worked example（**non-normative**）：`examples/uo-query-splitaxis/`。
