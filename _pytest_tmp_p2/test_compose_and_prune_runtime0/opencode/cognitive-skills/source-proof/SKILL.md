---
name: source-proof
description: '基于 CodeMap 与源码证明或反驳程序语义命题。证明某条件必然导致某结果、 某状态不可出现、某字段只能取特定值，或为静态结论建立可审计源码证据时使用。

  '
---

# 源码引理证明

针对明确的程序语义命题，建立可审计的源码证明。

> 在给定前提下，是否存在任何合法执行路径可以推翻这个结论？

```text
PROVED | REFUTED | INSUFFICIENT
```

## 核心原则

```text
命题 → 分解证明义务 → 定位状态 → 验证控制/数据流 → 主动寻反例
→ PROVED / REFUTED / INSUFFICIENT
```

模型预测、搜索失败、历史未出现、测试覆盖不足，都不能证明不可达。  
详见 `references/evidence-quality.md`。**未找到 ≠ 不存在。**

## 步骤

1. **明确命题**：`前提 P ⇒ 结论 Q`；优先最小命题。
2. **证明义务**：入口、控制流、赋值、调用、覆盖、替代路径、观测绑定、完整性。关闭法：`references/proof-obligations.md`。
3. **先结构查询，再读源码**：partial 不得证明「不存在」。静态输出：`references/static-evidence.md`。
4. **追踪决定性状态**：定义 → 赋值 → guard → 调用 → early return → 覆盖 → 消费。
5. **主动寻反例**：其他入口、分流、间接调用、模板/宏、alias。踩坑：`references/failure-patterns.md`。
6. **结论与证书**：`references/proof-certificate.md`；裁判：`references/referee-replay.md`；新鲜度：`references/artifact-freshness.md`。

## 按需参考

| 条件 | 文件 |
|---|---|
| 关闭义务 | `references/proof-obligations.md` |
| 静态证据 | `references/static-evidence.md` |
| 证书 | `references/proof-certificate.md` |
| 裁判 replay | `references/referee-replay.md` |
| 假证模式 | `references/failure-patterns.md` |
| 踩坑 | `references/gotchas.md` |
| C++ / 证据 / 完整性 | `references/cpp-semantics.md` / `references/evidence-quality.md` / `references/completeness.md` |
