---
name: source-lemma-proof
description: >
  基于代码知识库、Codemap 与源码证明或反驳程序语义命题。
  当任务需要证明某条件必然导致某结果、某状态不可出现、某字段只能取特定值，
  或需要为静态分析结论建立可审计源码证据时使用。
---

# 源码引理证明

针对一个明确的程序语义命题，建立可审计的源码证明。

目标不是寻找「支持这个结论的代码」，而是回答：

> 在给定前提下，是否存在任何合法执行路径可以推翻这个结论？

最终只允许三种结果：

```text
PROVED        源码足以证明
REFUTED       找到合法反例
INSUFFICIENT  当前证据不足
```

## 核心原则

```text
命题 → 分解证明义务 → 定位状态 → 验证控制/数据流 → 主动寻反例
→ PROVED / REFUTED / INSUFFICIENT
```

模型预测、搜索失败、历史未出现、测试覆盖不足，都不能证明不可达。

详见 `_shared/evidence-quality.md`。**未找到 ≠ 不存在。**

## 1. 明确命题

整理为 `前提 P ⇒ 结论 Q`。优先最小命题。含糊时先澄清前提、结论、状态与全称/局部范围。

## 2. 建立证明义务

默认：入口、控制流、赋值、调用、覆盖、替代路径、观测绑定、完整性。  
每项 `OPEN | CLOSED | BLOCKED`。必要项未关不得 `PROVED`。

关闭法：`references/proof-obligations.md`

## 3. 先结构查询，再读源码

KB/Codemap：`definition` `writers` `readers` `guards` `callers` `callees` `roots` `path` `source` `completeness`。  
`partial` 时不得用缺失证明「不存在」。

有静态 derivation 输出时：`references/static-evidence.md`

## 4. 追踪决定性状态

定义 → 赋值点 → guard → 调用 → early return/dispatch → 后续覆盖 → 消费点。  
支持路径找到后仍须排除推翻路径。

## 5. 证明方式

条件蕴含 / 完备赋值分析 / 路径不可满足（见 obligations）。  
排除型证明要求推导为 EXACT（或已补齐必要完整性）；见 `references/static-evidence.md` 与 `_shared/completeness.md`。

## 6. 主动寻反例

其他入口、分流、early return、间接调用、模板/宏、覆盖、alias。找到即 `REFUTED`。

常见踩坑：`references/failure-patterns.md`

## 7–8. 完整性与结论

全称用语依赖完整性。模板/宏/别名见 `_shared/cpp-semantics.md`。  
`PROVED` / `REFUTED` / `INSUFFICIENT` 标准见上；证书形态：`references/proof-certificate.md`。  
复用旧证书前查 `_shared/artifact-freshness.md`。

## 按需参考

| 条件 | 文件 |
|---|---|
| 关闭义务细节 | `references/proof-obligations.md` |
| 静态分析证据包 | `references/static-evidence.md` |
| 写/验证书 | `references/proof-certificate.md` |
| 裁判 replay | `references/referee-replay.md` |
| 假证/漏分流等 | `references/failure-patterns.md` |
| 模板/宏/别名 | `_shared/cpp-semantics.md` |
| 证据/完整性/新鲜度 | `_shared/evidence-quality.md`、`completeness.md`、`artifact-freshness.md` |
