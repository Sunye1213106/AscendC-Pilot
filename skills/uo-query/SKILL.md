---
name: uo-query
description: 只读查询已有 Operator CodeMap。用户问图上有什么、谁调用、Key/Data/Kernel 怎么连时使用。
---

# 查 CodeMap

用已 commit 的 `.uo` 回答本路 FOCUS。工具：Cursor 用 MCP `uo_query`；OpenCode 用插件 `pilot_cli` 的 `uo-query`。四种形态见 kb-query。全局访问约束见 code-access。不要 `python -m ascendc_pilot uo-query`，不要包装脚本。

Agent 只选输入形状。不要规划 `field_impact` / `neighbors` / `edges` / `controllability` —— 那些是引擎内部的。卡片上的 `host.writers`、`kernel.readers`、`coverage` 是读结果，不是再调一次工具。

## 输入 / 输出 / 停

读：本路 FOCUS、已有 `.uo`、查询卡片。写：对话作答。不写正式产物，不改 `.uo`。

缺 `.uo`：停，交给主控 `/uo-init` 或源码作答。已有标识符 / `Dim=V` / `--file --line` 时直接用。否则先无参数索引。

完成：本 FOCUS 能用 `file:line` 作答，或 PARTIAL 并写明缺什么。partial 图不能证明「不存在」。

## 四种输入

1. **无参数** — 索引（三相 launch / PIPE 名）。
2. **标识符** — 名字 / 定义 / 谁写谁读。一张卡含 `definition`、`host.writers`、`kernel.readers`、`flow`。不必再跟 `next` 才能答写读。
3. **`Dim=<维名>` 或 `Name=Value`** — 某维合法集 / 某组能否编过。看 `sel_sites` / `dim_coverage`。
4. **`file` + `line`** — 已知位点的语句窗。卡含 enclosing + `impact`。路径只从上一张卡复制。

## 步骤

1. **选最短形态。** 上表四选一。多阶段 launch 先看无参数索引。
2. **卡片是证据指针。** 用 `file:line`、`sel_sites`、`host.writers` / `kernel.readers` 定位。snippet 只帮助认地方；引用一个构造前必须看到该构造自己的行。
3. **`count:0` 缩短再查。** 跟 `hint` / `canonical` / `text_hits`。仍空：对算子目录做 `pilot_cli` `ro-search`。然后 PARTIAL / UNKNOWN。
4. **列表结论要有总数。** 模板维用 `dim_coverage` / `matching_block_count` / `legal_key_count`。写点用 `host.writers` 与 `edges.*.count`。`count` 大于已列出邻居 ⇒ PARTIAL。
5. **问哪一层答哪一层。** Host 不产生 ≠ 模板不接纳。差分题（hang / 精度）无运行时日志不得 ANSWERED。

## 常驻判断

**Claim 五层（不静默扩大）**

1. domain — 声明域允许什么值
2. template-admissible — 编译期模板/宏是否接纳
3. host-produced — Host 在何条件下写出
4. kernel-consumed — Kernel 是否消费
5. full reachability — 端到端可达（常需测试生成，不在本步发明）

完整性用语（全部 / 唯一 / 从不）依赖覆盖字段或 `edges.*.count`；索引 partial 时最多 PARTIAL。

`coverage_checked` = 合法宇宙已扫完，与命中数无关。0 命中且已扫完仍是已覆盖的空集。Host 失败码打到 `ge.graphStatus` 根。问句里的局部名常常不是 TILING_FIELD 名；空了看 `canonical` / `text_hits`。

## 看到这样

| 现象 | 判断 |
| --- | --- |
| 没有标识符 | 无参数索引 |
| 这个名字是什么 / 谁写谁读 | 标识符；读 `host.writers` / `kernel.readers` |
| 这维会不会编过 / 有没有 kernel | `Dim=V` 或 `Name=Value`；看 `sel_sites` |
| 已有 `file:line`，要该行语句 | `--file --line`；读 `enclosing` / `impact` |
| `count:0` | 按 `hint` 缩短再查；不是「不存在」 |
| `edges.CALLS.count` > 列出的 neighbors | 列表未穷尽，PARTIAL |
| 时序 / 测量 / sanitizer | 停：不在 UO |
| 缺 `.uo` | 停：不是本步 |

## 完成勾选

- [ ] 结论有 `file:line`，或 PARTIAL 并写出缺什么
- [ ] 列表型结论引用了覆盖字段或 `edges.*.count`
- [ ] 层没扩：Host 没说成 Kernel，「没查到」没说成「不存在」
- [ ] 没有改 `.uo`，没有跨 arch 借命中
- [ ] 没有把 DECL / 第一页 snippet 当成 SEL 命中块

## 循环

每一轮只推进本路 FOCUS。

1. 手头有标识符 / `Dim=V` / `file:line`？没有 → 无参数索引。
2. 调用 MCP `uo_query`（或 OpenCode `pilot_cli` `uo-query`）。读卡片上的 `file`、`host.writers`、`kernel.readers`、`impact`、覆盖字段。
3. 够作答就停。`next` 只跟卡里还没展开的相关名，不要为「找 writer」再查一次。
4. 不够：按 `hint` 缩短。仍不够 → 最小源码窗，或 PARTIAL。
5. 写结论：先 verdict，再窗口。问哪一层答哪一层。

## 输出形状

```text
verdict: ANSWERED | PARTIAL | UNKNOWN
layer: domain | template | host | kernel
span: file:line
coverage: dim_coverage=... / count=...   # 列表型结论必填
missing: ...                             # PARTIAL 必填
```

## 指针

走到该域才打开：

- TilingKey / packing：`references/uo-key.md`
- TilingData 写读：`references/uo-tilingdata.md`
- Kernel 分支：`references/uo-kernel.md`
- Template / BuildVariant：`references/uo-template.md`
- Buffer：`references/uo-buffer.md`
- unresolved：`references/uo-gaps.md`

权威分层与任务→形态：`references/uo-product-map.md`。
