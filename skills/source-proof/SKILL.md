---
name: source-proof
description: 为 AscendC 覆盖规划/求解中的静态可达性与蕴含命题生成源码证明证书。用于证明某维取值/组合在 domain、template、Host 或 kernel 上是否可能，或证明 P⇒Q。不要用于普通源码解释、runtime HIT 判断、case 构造，或自行写 exclusion。
---

# 源码证明

把 Solve 发来的 claim 做成可审查证书。查图 ≠ 证明。本步不构造 case、不改 plan、不写 exclusion、不宣布 coverage CLOSED。

**未找到 ≠ 不存在。** cover 命中 ≠ Host 可达；cover 未命中 ≠ Host 不可达。写出 ≠ 活到 packing。Replay reject ≠ 源码证明。

## 输入 / 输出 / 停

读：规范化 claim（层 + P⇒Q）、已有 `.uo`、查询卡片、函数剩余窗口。写：注入的 `source-proof/v1` 证书。字段只认 `references/proof-certificate.md`。

缺 `.uo` → 停，去 `/uo-init`。写不出「层 + P⇒Q」就先改写。一次只证一层 atomic claim：`domain` / `template` / `host` / `kernel`。跨层 `full` 由引擎在两份 accepted 证书上合成，不是本步的 layer。

## 步骤

1. **钉层。** 「某维只能是 / 某组合没有」先问在哪一层。组合题默认 **host**，除非 template 覆盖已证明该值不在 product 里。
2. **取证据。** 查图与读窗口按 `code-access` 与 `skills/uo-query/SKILL.md`。本步要的是层语义，不是 CLI 形态。
   - template：须 `declared` / `product` 且 `completeness=coverage_checked`。cover>0 只说明模板接纳，不可达必须转 host。
   - host：赋值函数（不是 packing 那一行）+ 拒绝路径 + 后续覆盖 + 替代路径。`ge.graphStatus` 失败根只证明存在拒单入口，覆盖哪条路径要读站点。
   - 标识符第一张卡可能是错 kind。写点不全 → 该项最多 BLOCKED。
3. **关义务。** 清单与关法见 `references/proof-obligations.md`。snippet 截断处读完函数。静态包见 `references/static-evidence.md`。
4. **反例。** 其他入口、第一行分流、空 tensor SEL、宏隔离、别名写。cover 命中的组合是 template 反例，不是 host 反例。假证见 `references/failure-patterns.md`。
5. **交证书。** `PROVED | REFUTED | INSUFFICIENT`。completeness 的 `full` 必须引用机器 receipt，不得自填。不要自审自批。

## 常驻判断

uo-query 能定位、能分层，不能单独闭合「只能 / 从不」。完整性用语依赖覆盖字段或写点全集 receipt。有 undecided / 截断窗口 / 漏入口 → `INSUFFICIENT`。

lemma 是产物名词，不是另一个 Skill。审证 `accept | reject | defer` 由独立窗做。PROVED 变成 exclusion 只由引擎在 accept 之后做。

## 看到这样

| 现象 | 判断 |
| --- | --- |
| `declared` 有 4、`product` 无 4 | template 可证不接纳；host 另证 |
| 组合 cover>0 | 模板接纳；「不可达」必须走 host |
| 组合 cover=0 且 coverage_checked | 模板层已扫完的空集；host 另证 |
| 失败码 catalog 根 | 只证明存在拒单入口 |
| 函数卡尚未 `return` | 不得 PROVED |
| packing writers 只有 packing 出口 | 去查宿主字段赋值 |
| Host 赋了 4 又 `GRAPH_FAILED` | host 层「活不到 packing」 |

## 完成勾选

- [ ] claim 带 atomic 层；组合题已用 cover 判定 template 还是 host
- [ ] 列表型结论引用了覆盖字段或 closure receipt
- [ ] Host 层读完赋值函数，不只停在 snippet
- [ ] 没有自填 `completeness.*.status: full`
- [ ] 没有升级 exclusion

## 指针

证书合同：`references/proof-certificate.md`。义务：`references/proof-obligations.md`。假证：`references/failure-patterns.md`。静态包：`references/static-evidence.md`。查图：`skills/uo-query/SKILL.md`。
