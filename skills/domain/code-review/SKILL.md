---
name: code-review
description: >
  基于代码知识库、Codemap、源码和变更信息进行代码审查。
  用于分析代码修改、定位潜在缺陷、验证实现一致性、评估影响范围，
  或判断一个改动是否可能破坏已有程序语义。
---

# 代码审查

从代码变更出发，分析它如何影响程序行为，并寻找有源码证据的缺陷。

```text
代码变化 → 受影响状态 → 传播路径 → 被破坏约束 → 可观察后果
```

优先少量高质量问题。

## 核心流程

```text
理解改动 → 定位符号 → 最小影响域 → 识别约束 → 追踪路径
→ 构造失败场景 → 尝试推翻 → 输出结论
```

## 1–3. 理解、定位、影响域

归类语义变化；精确解析符号；只扩展相关关系。见 `_shared/cpp-semantics.md`（模板/重载）。

## 4. 程序约束

说明违反了什么约束。通用扩展：`references/domain-checks.md`。

## 5. 沿路径验证

Finding 必须解释：什么条件下产生什么错误结果。

## 6. 跨层一致性

同一语义经多层传播时检查生产者/消费者一致。  
涉及 dtype / optional / dispatch / template / feature / arch 时：`references/cross-layer-contracts.md`。  
AscendC 专项：`references/ascendc-checks.md`。

## 7–9. 边界、证伪、完整性

相关边界才展开；报告前尝试推翻；`partial` 索引不得证伪存在性。  
见 `_shared/evidence-quality.md`、`_shared/completeness.md`。旧结论：`_shared/artifact-freshness.md`。

## 10–11. 结果

- **FINDING** / **NO_CONFIRMED_ISSUE** / **UNRESOLVED**
- 结构见 `references/examples.md`；不报告纯风格问题（除非任务要求）

## 按需参考

| 条件 | 文件 |
|---|---|
| dtype/optional/dispatch/模板声明 | `references/cross-layer-contracts.md` |
| Host/Kernel/同步/buffer | `references/ascendc-checks.md` |
| 并发同步 | `references/concurrency.md` |
| 通用约束 | `references/domain-checks.md` |
| Finding 形态 | `references/examples.md` |
| C++ 语义 | `_shared/cpp-semantics.md` |
| 证据/完整性/新鲜度 | `_shared/evidence-quality.md`、`completeness.md`、`artifact-freshness.md` |
