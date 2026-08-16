# UO Product Map（progressive）

短地图：认清权威 → 选 mode → 查完就答。主控先对人说出路由：短问自查，深问必须派 uo-query 子代理（禁止把深问改成主控连查），禁止 `pilot_run`。怎么查见 `capabilities/uo-query/METHOD.md`。

同一场景可沿图跳（同一结案条件）：`locate`/`tiling_key` → `field` → `kernel_branch` → `impact`。是否并行拆 Task 见 `routing/uo-query.md`（编译器 `host_step.tasks` 优先；启发式看独立证据空间）。

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
| Tiling 失败 / Kernel 找不到 / 某维有没有编 | **`template_match` → `legal_key`** | `kernel_branch`；Host 写出用 `tiling_data` | 运行时日志解读。禁止 grep SEL 头文件 |
| 声明 dtype | `search` INPUT/OUTPUT | 已有声明即可；不要默认全量抽取 | 默认改成 full profile |
| 卡死 / hang / SetScheduleMode | `locate`（Host TilingContext） | 核内 `kernel_api` SyncAll / `buffer`；`impact` | happens-before、测量 |
| 越界 / 核内同步 API | `kernel_api` + `buffer` | `impact` 分到 sync/memory | happens-before、测量 |
| 精度（Cast / 搬运 / 多 dtype） | `kernel_api` + `field` | `buffer` 方向 | golden / atol |
| 性能（结构事实）/ 分核 / 占核 | `field`（问句标识符；空则 `local_aliases`）+ `tiling_key` | `buffer` | profiling 数字 |
| Pre / Main / Post / 三相 | `kernel_launch`（pipeIn/pipeBase/pipePost + KERNEL / `*_entry*.h`） | `kernel_api` Destroy / SyncAll | 把内层 `Process()` / `*_apt.cpp` 当三相 |
| UT / 白盒线索 | `legal_key` + `kernel_branch` + `gaps` | 字段写读作覆盖线索 | 生成完整 ST 矩阵 |
| 精度/性能场景推断 | `kernel_api` / `buffer` / `field` / `impact` | `uo-scenario-hooks.md`；id 以 CE catalog 为准 | golden、profiler |
| Issue 定位 / 改码影响 | 无 diff：`locate` / `field`；有 diff：`impact` | — | Git / PR |

`source_span` 或查询返回的带行号 `snippet` **视为已 Read**，不要 Grep/再 Read 同一段。`template_match.dim_coverage` / `legal_key.total_matched` 是全集，不要用第一块 SEL snippet 否定其它组。缺语义用 `PARTIAL` / `UNKNOWN`，不要编事实。空结果按 `hint` 用更短名字再查一次，禁止仓级 findstr。看到 `functions` 目录时按问题选函数名再查；`field` 只问字段名，packing 表达式走 `tiling_key`。局部变量名常常不是 TILING_FIELD 名，空了看 `local_aliases`。

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
