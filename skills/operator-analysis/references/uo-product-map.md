# UO Product Map（progressive）

短地图：认清权威 → 选 mode → 查完就答。短问主控自己查；深问再开 uo-query 子代理。怎么执行见 `capabilities/uo-query/METHOD.md`。

同一场景可沿图跳：`locate`/`tiling_key` → `field` → `kernel_branch` → `impact`。互不相关的独立域再拆 Task。

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

主问只需 1–3 时不要拖到 5。不同层级分开说，不能用 Host 不产生去否定「模板可接纳」。

## 日常任务 → mode

按手头任务选最短查询。配对、时序、仿真、sanitizer **不在 UO**。

| 任务 | 先查 | 再补 | UO 不回答 |
| --- | --- | --- | --- |
| 检视 / 看风险 | `impact` 或 `locate` | `buffer` / `kernel_api`；校验点看 `locate` | 长报告、条例级 API |
| 检视 PR | 先有 diff，再 `impact` | finding 必须落在 diff 内 | 拉 PR / 写 PR |
| Tiling 失败 / Kernel 找不到 | `tiling_key` → `legal_key` | `kernel_branch`；Host 写出用 `tiling_data` | 运行时日志解读 |
| 声明 dtype | `search` INPUT/OUTPUT | 已有声明即可；不要默认全量抽取 | 默认改成 full profile |
| 卡死 / 越界 / 同步 | `kernel_api` + `buffer` | `impact` 分到 sync/memory | happens-before、测量 |
| 精度（Cast / 搬运 / 多 dtype） | `kernel_api` + `field` | `buffer` 方向 | golden / atol |
| 性能（结构事实） | `tiling_key` + `buffer` | 切分字段 `field` | profiling 数字 |
| UT / 白盒线索 | `legal_key` + `kernel_branch` + `gaps` | 字段写读作覆盖线索 | 生成完整 ST 矩阵 |
| 精度/性能场景推断 | `kernel_api` / `buffer` / `field` / `impact` | `uo-scenario-hooks.md`；id 以 CE catalog 为准 | golden、profiler |
| Issue 定位 / 改码影响 | 无 diff：`locate` / `field`；有 diff：`impact` | — | Git / PR |

`source_span` 或查询返回的带行号 `snippet` **视为已 Read**，不要 Grep/再 Read 同一段。缺语义用 `PARTIAL` / `UNKNOWN`，不要编事实。不够就用更短名字再查一次。看到 `functions` 目录时按问题选函数名再查；`field` 只问字段名，packing 表达式走 `tiling_key`。

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
