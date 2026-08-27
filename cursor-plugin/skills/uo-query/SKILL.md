---
name: uo-query
description: 只读消费已有 Operator CodeMap，回答图上已经确定的语义事实。用户问图上有什么、谁写谁读、某维能否编过时使用。不要用于修图、补边、或诊断 UO 引擎 residual。
---

# 查 CodeMap

用已 commit 的 `.uo` 回答本路 FOCUS。统一 `.uo` 是查询的唯一 authority。工具：Cursor 用 MCP `uo_query`；OpenCode 用插件 `pilot_cli` 的 `uo-query`。四种形态见 kb-query。全局访问约束见 code-access。不要 `python -m ascendc_pilot uo-query`，不要包装脚本。

Agent 只选输入形状。不要规划 `field_impact` / `neighbors` / `edges` / `controllability` —— 那些是引擎内部的。卡片上的 `host.writers`、`kernel.readers`、`coverage` 是读结果，不是再调一次工具。

不要把自然语言句子塞进 pattern。先把问题翻译成下表某一种形状。

```text
❌ "who writes deterBandScheduleMode and why?"
✅ deterBandScheduleMode
```

## 输入 / 输出 / 停

读：本路 FOCUS、run state / packet / framework 给出的 architecture、已有 `.uo`、查询卡片。写：对话作答。不写正式产物，不改 `.uo`。

**architecture 前置（本 Skill 不选择，只声明缺失则不能工作）：**

- architecture 必须由 run state / packet / framework 提供。
- 不自行推断 architecture。禁止默认 arch35。禁止借其它 architecture 的卡片回答。
- 缺失时停止查询，返回 `ARCHITECTURE_MISSING`（引擎码 `ARCHITECTURE_MISSING_IN_RUN_STATE`）。

缺 `.uo`：停，交给主控 `/uo-init` 或源码作答。不要自己打开 `product_map.json` 当第二套真值。

完成：本 FOCUS 能用 `file:line` 作答，或 PARTIAL / UNKNOWN 并写明缺什么。partial 图不能证明「不存在」。不要因为缺口去修 UO 引擎。

## 步骤

1. **确认 architecture。** 没有就不查。
2. **把问题收成一种形状。** 见路由表。多阶段 launch 先看无参数索引。
3. **调用一次查询，读卡片。** 用 `file:line`、`sel_sites`、`host.writers` / `kernel.readers`、覆盖字段定位。snippet 只帮助认地方；引用一个构造前必须看到该构造自己的行。
4. **按停规则决定是否再查。** 卡片已回答就停。
5. **`count: 0` 时只消费卡片给出的线索。** 跟 `hint` / `canonical` / `text_hits`；有 source window 就用窗口。确定性卡片仍不够 → 服从 `code-access` 的受控兜底。搜索结果只是定位器，不能单独证明复杂语义。未决保持 PARTIAL / UNKNOWN。
6. **列表结论要有总数。** 模板维用 `dim_coverage` / `matching_block_count` / `legal_key_count`。写点用 `host.writers` 与 `edges.*.count`。`count` 大于已列出邻居 ⇒ PARTIAL。
7. **问哪一层答哪一层。** Host 不产生 ≠ 模板不接纳。差分题（hang / 精度）无运行时日志不得 ANSWERED。

## 常驻判断

**Claim 四层（不静默扩大，不宣布 runtime 全可达）**

1. domain — 声明域允许什么值
2. template-admissible — 编译期模板/宏是否接纳
3. host-produced — Host 在何条件下写出
4. kernel-consumed — Kernel 是否消费

`template accepts` + `host can produce` + `kernel consumes` 仍不天然等于某 concrete test runtime 一定可达。那是 Plan / Solve / Replay 的组合结论。本步可以提供组分事实，**不声明 runtime full reachability**。

完整性用语（全部 / 唯一 / 从不）依赖覆盖字段或 `edges.*.count`；索引 partial 时最多 PARTIAL。

`coverage_checked` = 合法宇宙已扫完，与命中数无关。0 命中且已扫完仍是已覆盖的空集。Host 失败码打到 `ge.graphStatus` 根。问句里的局部名常常不是 TILING_FIELD 名；空了看 `canonical` / `text_hits`。

## 看到这样

| Intent | Shape |
| --- | --- |
| 浏览 UO 可回答什么 | 无参数索引 |
| 某 identifier 的定义 / producer / consumer | 标识符；读 `host.writers` / `kernel.readers` |
| 某维 / 某值是否合法、是否编译 | `Dim=V` 或 `Name=Value`；看 `sel_sites` |
| 延续已有 evidence window | `--file --line`；读 `enclosing` / `impact` |
| 自然语言整句 | 先翻译成上表某一行，禁止原句进 pattern |
| `count:0` | 跟卡片 `hint` / 窗口；不是「不存在」 |
| `edges.CALLS.count` > 列出的 neighbors | 列表未穷尽，PARTIAL |
| 时序 / 测量 / sanitizer | 停：不在 UO |
| 缺 architecture | 停：`ARCHITECTURE_MISSING` |
| 缺 `.uo` | 停：不是本步 |
| 卡片缺确定性证据 | `PARTIAL` + `gap_code` / `residual_id`；到此停止 |

**停规则：** 卡片已经回答问题 → STOP。只有卡片明确 incomplete、`count` 大于已返回项、或当前 claim 必须依赖尚未展开的 evidence 时，才继续 query。不要为「找 writer」再查一次。不要 follow 无关 `next`。

## 完成勾选

- [ ] architecture 来自 run state / packet / framework，没有猜
- [ ] 结论有 `file:line`，或 PARTIAL / UNKNOWN 并写出缺什么
- [ ] 列表型结论引用了覆盖字段或 `edges.*.count`
- [ ] 层没扩：Host 没说成 Kernel，「没查到」没说成「不存在」，没有宣布 full reachability
- [ ] 没有改 `.uo`，没有跨 arch 借命中，没有打开 `product_map.json` 当真值
- [ ] 没有把 DECL / 第一页 snippet 当成 SEL 命中块
- [ ] 缺口没有自动转去修 UO 引擎

## 循环

每一轮只推进本路 FOCUS。

1. 没有 architecture → 停。
2. 按路由表选一种形状。没有标识符 / `Dim=V` / `file:line` → 无参数索引。
3. 调用 MCP `uo_query`（或 OpenCode `pilot_cli` `uo-query`）。读卡片上的 `file`、`host.writers`、`kernel.readers`、`impact`、覆盖字段。
4. 够作答就停。不够：跟 `hint` 缩短。仍不够 → `code-access` 受控兜底，或 PARTIAL / UNKNOWN。
5. 写结论：先 verdict，再窗口。问哪一层答哪一层。

## 输出形状

```text
verdict: ANSWERED | PARTIAL | UNKNOWN
layer: domain | template | host | kernel
span: file:line
coverage: dim_coverage=... / count=...   # 列表型结论必填
missing: ...                             # PARTIAL 必填
gap_code: ...                            # 有缺口时
residual_id: ...                         # 卡片给出时原样带回
```

## 指针

走到该域才打开：

- TilingKey / packing：`references/uo-key.md`
- TilingData 写读：`references/uo-tilingdata.md`
- Kernel 分支：`references/uo-kernel.md`
- Template / BuildVariant：`references/uo-template.md`
- Buffer：`references/uo-buffer.md`
- unresolved 怎么写缺口：`references/uo-gaps.md`

权威分层：`references/uo-product-map.md`。
