---
name: source-proof
description: 证明或反驳程序命题。要证明 P⇒Q、不可达、字段只能取某值，或静态结论需要源码窗口时使用。
---

# 源码证明

问：在给定前提下，是否存在合法执行路径可以推翻这个结论？审查、调查、构造 case 只要碰到硬命题都可以读本文件，不必等 `/tg-solve`。

**未找到 ≠ 不存在。** 搜索耗尽、样本未出现、索引 partial，只能 `INSUFFICIENT` 或继续搜，不能写成源码不可达。

## 输入 / 输出 / 停

读：命题（或能改写成 P⇒Q 的线索）、查图卡片、源码窗口、静态证据包（若有）。写：`PROVED | REFUTED | INSUFFICIENT`，每条义务有源码窗口。

没有明确 antecedent→consequent 就先改写，不要证明「感觉正确」。

## 步骤

1. **写成最小命题。** 前提 P ⇒ 结论 Q。来自运行观测时，证明须解释该观测：走了哪条入口、为何改写或拒绝。禁止把构造器先验拒采写成源码不可达。
2. **分解证明义务。** 入口、控制流、赋值、调用、后续覆盖、替代路径。每项 `OPEN | CLOSED | BLOCKED`。漏入口 → 不得 CLOSED。写入集合声明为 partial → 该项最多 BLOCKED，禁止 PROVED。调用目标未解析 → BLOCKED 或继续读源码。关闭法见 `references/proof-obligations.md`。
3. **先结构查询，再读窗口。** 先查图拿 span，再按 `file:line` 开最小窗口。partial 索引不能证明不存在。完整性用语（全部、唯一、从不、没有其他、必然、不可能、不可达）依赖完整性；不足时继续关缺口，或整体 `INSUFFICIENT`。
4. **主动找反例。** 其他入口、第一行分流、模板/宏/重载/特殊模式、alias、保存-修改-恢复。假证模式见 `references/failure-patterns.md`。
5. **静态包怎么读。** 有 expression / domain / def_sites 时先读 `references/static-evidence.md`。expression 是缩小阅读范围，不是证明。**value domain ≠ reachable domain。** 有 undecided 或 free vars 时，不得对「不可能 / 不可达」返回 PROVED。derived ≠ exact。

## 常驻判断

完成：`PROVED` | `REFUTED` | `INSUFFICIENT`，每条义务有源码窗口。只贴行号不够，要有推理链且无后续覆盖。

不要做的：

- 有限构造未命中 → 写成不可达
- 把 Host Replay reject 当源码证明
- 把运行时值回填成宏条件的唯一真值
- 把所有 failure return 扔掉从而放宽合法输入域
- 无观测写运行时不可达

Host/Kernel 条件须经 TilingKey 映射；跳过 TemplateArg 的跨层蕴含通常错误。

## 看到这样

| 现象 | 判断 |
| --- | --- |
| 命题含糊 | 先改写成 P⇒Q |
| 搜索未命中 | INSUFFICIENT |
| 索引 partial | 不能证「不存在」 |
| domain 很窄 | ≠ 可达 |
| 有 expression 摘要 | 缩小阅读范围，不是证明 |
| 无观测 | 不得声称运行时不可达 |
| 漏入口 / 第一行分流 | 不得 PROVED |
| Host reject | 不够 |

## 完成勾选

- [ ] 结论是三选一，不是「大概对」
- [ ] 每条义务有窗口；完整性用语有完整性支撑
- [ ] 主动找过反例
- [ ] 静态包按 domain ≠ reachable 读

## 循环

1. 把用户句子改写成 P⇒Q。写不出就停。
2. 列义务。完整性用语先标「需要完整性」。
3. 查图 → 窗口。静态包只用来找 def_sites，不当证明。
4. 找反例。找不到且义务全 CLOSED → PROVED；找到 → REFUTED；缺口 → INSUFFICIENT。
5. 交结论。不要升级 exclusion（那是调用方的事）。

## 输出形状

```text
result: PROVED | REFUTED | INSUFFICIENT
P: ...
Q: ...
closed: [entry, ...]
open_or_blocked: [writes=partial, ...]
windows: [file:line, ...]
```

完整性用语未支撑时不得 PROVED。

## 指针

义务如何关：`references/proof-obligations.md`。假证：`references/failure-patterns.md`。静态包：`references/static-evidence.md`。证书形状：`references/proof-certificate.md`。
