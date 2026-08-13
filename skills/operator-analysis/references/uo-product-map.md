# UO Product Map（progressive）

短地图：认清权威分层 → 选语义下一跳 → 够 claim 就停。域细节按需读底部链接。

## 权威分层

| 层 | 是什么 | 不是什么 |
| --- | --- | --- |
| **Semantic authority** | 已 commit 的 `.ascendc-pilot/<arch>/uo/<op>.<arch>.uo` | LLM 记忆、未校验 staging |
| **Canonical representation** | `entity` / `relation` / `source_span`（属性在 `entity.data`；`attribute` 表不再填充） | 任何可重建索引的「捷径」本身 |
| **Materialized projections** | `view_blob/*`（加速索引） | 独立事实源；由 engine 管 freshness |

Query 路径：projection provenance mismatch / legacy unverifiable → `VIEW_STALE`（或兼容 reason）→ **engine** fallback 到 canonical；无法安全重建则把缺口返回给 Agent，禁止把“无法验证 freshness”当作 fresh。

## Claim 层级（sufficiency，不是固定槽）

认清要证明的层级，**不静默扩大**：

1. **domain** — 声明域/枚举/TPL 允许什么值  
2. **template-admissible** — 模板/宏在编译期是否接纳  
3. **host-produced** — Host 在何 guard 下写出/改写该值  
4. **kernel-consumed** — Kernel/分支是否消费该维或字段  
5. **full reachability** — 端到端可达（常需 TG；UO 只给结构证据）

主问只需 1–3 时，不要为了「更完整」拖到 5。不同层级必须分别陈述，不能用 Host 不可达去否定 template-admissible。

## 默认探索环

```text
mission → identify_claim → read this map → choose_semantic_next_hop
  → acp uo-query (structured) | minimal source window
  → claim_sufficient? → STOP ANSWERED
  → material gap? → STOP PARTIAL | else next_hop
```

预算（软/硬由 harness 执行）：semantic 优先；源码窗口极少；禁止重复同 semantic query / 同 source span。

## 日常任务 → `uo-query` mode

按开发者手头的任务选最短查询，不要全文 Grep 结构事实。配对、时序、仿真图、sanitizer 测量 **不在 UO**。

| 任务 | 先查 | 再补 | UO 不回答 |
| --- | --- | --- | --- |
| 检视代码 / 看风险 | `impact`（改动文件）或 `locate` + `tiling_data` / `buffer` / `kernel_api` | Host 校验点：`locate` 字段名，看 `facts.check_sites`；侧别按 `op_host/` vs `op_kernel/` | 条例级 API 细则、长报告 |
| 检视 PR | 先有 diff，再 `impact` 切片 | 同检视；finding 必须落在 diff 范围内 | 拉 PR / 写 PR 文案 |
| 561002（Tiling 失败 / Kernel 找不到） | `tiling_key` → `legal_key`（该组合是否模板可接纳） | `kernel_branch` / `template_match`；Host 写出：`tiling_data` writers | 运行时 aclnn 日志解读、复测 |
| 561003（dtype / 接口声明） | `search` INPUT/OUTPUT，看 `facts.dtype`；`tiling_key` 声明域 | 已有 opdef / source_contract 声明 dtype。默认 extract **不**开 API clang（`with_api` 仅 `full` profile） | 默认 `UO_INIT_PROFILE=full` |
| 卡死 / 崩溃 / 越界 / 同步缺失 | `kernel_api`（SetFlag/WaitFlag 看 `flag_paired`；EnQue/DeQue 看 QUEUE/`tposition`）+ `buffer` | `locate` 调用点；`impact` 分到 sync/memory | happens-before、sanitizer 测量 |
| 精度（搬运 / EnQue·DeQue / Cast / 多 dtype） | `kernel_api` Cast/DataCopy；INPUT `dtype`；`buffer` VECIN/VECOUT | 字段公式：`field` 的 `facts.rhs` / `value_defining_sites` | golden 对比、atol/rtol 判定 |
| 性能（结构事实） | `tiling_key` + `buffer`（空间/队列方向） | `tiling_data` 切分字段 rhs | profiling 数字、仿真图 |
| UT / 白盒 / ST 覆盖 | `legal_key` 过滤；`kernel_branch`；`gaps` | 字段写读与校验点作覆盖线索 | 替换白盒整段源码分析；生成完整 ST 矩阵 |
| 精度/性能场景推断 | `kernel_api` / `buffer` / `field` / `impact` | 见 `references/uo-scenario-hooks.md` | golden、profiler 数字、配对 |
| Issue：定位 → 最小改动 | 无 diff：`locate` / `tiling_key` / `field` 先钉锚点 | 有 diff：`impact` 按 dispatch/layout/memory/sync/precision/contract 分桶 | Git 写操作、fork、PR API |

默认探索仍走下面的「何时读 projection」表。主问只需声明域时，不要拖到 full reachability。

## 何时读 projection vs canonical vs 源码

| 需要 | 优先 | fallback |
| --- | --- | --- |
| 符号 / 邻接 / 路径 / guard | `acp uo-query`（canonical graph） | — |
| TilingKey 维域 / packing / producer | `tiling_key` | entity attrs + relations；**不要默认触发 legal-key 枚举** |
| 某个 Key 组合是否合法 | `legal_key` indexed filter（dim/value 或多维条件） | template blocks / canonical dims；stale 时显式 gap |
| 字段写读 / 短 rhs | `tiling_data` / `field` | entity attrs + relations |
| Host 校验点 | `locate` 字段/输入，看 `facts.check_sites` | Host BRANCH `branch_kind=host_check` |
| 分支 / 模板匹配 | `kernel_branch` / `template_match` | neighbors + source_span |
| Buffer / 存储类 / tposition | `buffer` | BUFFER / QUEUE entities |
| 源码定位 | `locate` | entity span + packing / writer / check sites |
| Kernel API / sync 调用 | `kernel_api` | Flag：SIGNALS/AWAITS + flag_paired；TQue：QUEUE |
| 改动影响 | `impact`（有向有用边 + skill 分桶） | `slice_forward` / `slice_backward` |
| 已知缺口 | `gaps` | unresolved entities / `ir/unresolved.yaml` |
| 已有 path:line 但缺语义细节 | 先用现有 span | enum 数值、表达式细节、矛盾或用户问实现时才开最小源码窗口 |
| 仅缺 path:line | **已有 `source_span` / packing site 即足够引用** | 不为行号而 Read |

## Citation

- `source_span` 或 packing site 的 `path:line`（或 `path:start-end`）**足够引用**。  
- KB 节点 / `evidence_ref` 可并列，不能替代 span。  
- 语义证据不足不得假装 `ANSWERED`；用 `PARTIAL` / `UNKNOWN` + `reason_code`（如 `NOT_FOUND_IN_SCOPE` / `VIEW_STALE`）。

## 交付（kb-answer-v1）

保留 schema 名。`answer_zh` 必填。`findings` / `gaps` / `useful_locations` **optional**。  
未找到：`status: UNKNOWN` + `reason_code: NOT_FOUND_IN_SCOPE`（不要发明事实）。

## 按需域文档

| 域 | 文档 |
| --- | --- |
| TilingKey / packing / legal space | `uo-key.md` |
| TilingData 字段写读 | `uo-tilingdata.md` |
| Kernel 分支 / root trace | `uo-kernel.md` |
| Template / macro / BuildVariant | `uo-template.md` |
| Buffer / LocalTensor | `uo-buffer.md` |
| unresolved / gaps | `uo-gaps.md` |
| 精度/性能场景 query 钩子 | `uo-scenario-hooks.md` |

Worked example（**non-normative**）：`examples/uo-query-splitaxis/`。
