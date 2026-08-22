---
name: source-proof
description: 证明或反驳程序命题。要证某维只能取某值、某组合不可达、P⇒Q，或静态结论需要源码窗口时使用。
---

# 源码证明

先分清层，再查图拿窗口，再关义务。`Dim=` / `Name=Value` 只回答模板是否编过，不回答 Host 会不会写出。cover 命中 ≠ 可达；cover 未命中 ≠ Host 不可达。

**未找到 ≠ 不存在。** 卡片 `count:0` 且覆盖未勾、writers 只有 packing 点、snippet 在 `return` 前截断，都只能 `INSUFFICIENT`。

## 输入 / 输出 / 停

读：命题、已有 `.uo`、查询卡片、函数剩余窗口。写：`PROVED | REFUTED | INSUFFICIENT`，带层。

缺 `.uo` → 停，去 `/uo-init`。写不出「层 + P⇒Q」就先改写。本步不升级 exclusion。

## 步骤

1. **钉层。** 「某维只能是 / 某组合没有」先问在哪一层：
   - domain — DECL / `declared_coverage`
   - template — SEL / `product_coverage`
   - host — Host 赋值、early return、`GRAPH_FAILED`、改写
   - kernel — 消费
   - full — host 写出且 template 接纳
   组合题默认按 **host** 证，除非第 2 步证明该值根本不在 product 里。一次只证一层。

2. **查图三刀。** 怎么查见 `skills/uo-query/SKILL.md`。
   - `Dim=<维>` → `declared` 对 `product`（须 `completeness=coverage_checked`）
   - `<维>=V` 或 `A=1,B=2` → `matching_block_count`。**>0：模板接纳，必须转 host。=0 且 `completeness=coverage_checked`：才是 template 排除。`coverage_checked` 只表示宇宙已扫完，与命中数无关。**
   - Host 状态码根（`catalog=ge.graphStatus`）上的边是拒单入口（该路径活不到后续 Host 产出）。存在失败根 ≠ 某维永不产生；命题是否被这条 guard 覆盖仍要读站点。
   - 标识符 → packing writers + 赋值函数。第一张卡可能是错 kind（`IsRope` 会先落到 TilingData 字段）。跟 `next` / 全部 kind，不要只信第一页。

3. **卡片只是入口。** snippet 截断处按卡片 `file:line` 打开**函数剩下的正文**。`GRAPH_FAILED`、后续赋值、析取例外（PREFIX / 改写 layout）不在第一页就不能关。`--file --line` 会拌进邻近字段，不够就按定义 span 读完该函数。查询方法见 `skills/uo-query/SKILL.md`，关法见 `references/proof-obligations.md`。

4. **按层关义务。**
   - template：只引用覆盖字段。第一页 SEL 不是全集。
   - host：谁调用、赋值函数的全部写点、packing 读的是否同一字段、有没有后续覆盖、替代路径。`DetermineMode` 写出某值，后面仍可能被 `ProcessQuantInfo` 拒掉——写出 ≠ 能活到 `GetTilingKey`。
   - writers 列表经常只有 packing 点，不是 Host 字段的写点全集。字段赋值要另查 `fBaseParams.<field>`。

5. **反例。** 其他入口、第一行分流、空 tensor SEL、宏隔离、别名写。假证见 `references/failure-patterns.md`。**cover 命中的组合是 template 反例，不是 host 反例。** 其他层的事实不当本层反例。

## 常驻判断

uo-query 能定位、能分层，不能单独闭合「只能 / 从不」。完整性用语依赖覆盖字段或写点全集。`coverage_checked` 与命中数无关：宇宙扫完且 0 命中仍是已覆盖的空集，不是「没查完」。有 undecided / 截断窗口 / 漏入口 → `INSUFFICIENT`。

Host `ge.graphStatus` 失败根上的边是「这条路径活不到 Host 产出」的入口。命题是否被该 guard 覆盖仍要读站点，不能凭「图上有失败码根」写成某维永不产生。

不要做的：

- 没钉层就证「只能是 / 没有」
- 用 cover>0 当 Host 可达，或用 cover=0 当 Host 不可达
- 把 `DetermineMode` 赋值当成已发出的 Key
- 把 Replay reject 当源码证明
- 跨 arch 借命中

## 看到这样

| 现象 | 判断 |
| --- | --- |
| `declared` 有 4、`product` 无 4 | template 可证不接纳；host 另证 |
| 组合 cover>0 | 模板接纳；引理若是「不可达」必须走 host |
| 组合 cover=0 且 completeness=coverage_checked | 模板层已扫完的空集；host 另证 |
| 查到失败码 catalog 根 | 只证明存在 Host 拒单入口；覆盖哪条路径要读站点 |
| 函数卡截在 `if (dtype==FP8)` | 还没看到 `return`，不得 PROVED |
| packing writers 只有 `GetTilingKey` | 去查 `fBaseParams.xxx` 的赋值函数 |
| `IsRope` 第一张是 TilingData | 看同名 TILING_KEY 卡 |
| `hasRope` 查到 kernel 分支 | 换 `IsRope` / `fBaseParams.hasRope` |
| Host 赋了 4 又 `GRAPH_FAILED` | host 层「活不到 packing」 |

## 完成勾选

- [ ] 命题带层；组合题已用 cover 判定该走 template 还是 host
- [ ] 列表型结论引用了覆盖字段
- [ ] Host 层读完赋值函数，不只停在 snippet
- [ ] 写点 / 覆盖 / 替代路径有窗口；没有拿错层当反例

## 循环

1. 写成「层 + P⇒Q」。组合先查 cover，再决定层。
2. 查标识符拿 packing 与赋值函数。
3. 截断处读完函数。静态包只找 def_sites。
4. 本层反例 → REFUTED；义务全 CLOSED → PROVED；缺口 → INSUFFICIENT。
5. 交结论。不要升级 exclusion。

## 输出形状

```text
result: PROVED | REFUTED | INSUFFICIENT
layer: domain | template | host | kernel | full
P: ...
Q: ...
coverage: declared=... product=... combo_matched=... completeness=...
closed: [entry, writes, overwrite, alternatives, ...]
open_or_blocked: [...]
windows: [file:line, ...]
```

## 指针

义务如何关：`references/proof-obligations.md`。假证：`references/failure-patterns.md`。静态包：`references/static-evidence.md`。证书：`references/proof-certificate.md`。查图：`skills/uo-query/SKILL.md`。
