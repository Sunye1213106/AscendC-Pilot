---
name: code-review
description: >
  基于 CodeMap、源码和变更信息进行代码审查：分析修改、定位缺陷、验证实现一致性、
  评估影响范围，或判断改动是否破坏已有程序语义。
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

## 要点

1. 归类语义变化；精确解析符号；只扩展相关关系（`references/cpp-semantics.md`）。
2. 说明违反了什么约束：`references/domain-checks.md`。
3. Finding 必须解释：什么条件下产生什么错误结果。
4. 跨层一致性：`references/cross-layer-contracts.md`；AscendC：`references/ascendc-checks.md`。
5. 报告前尝试推翻；partial 索引不得证伪存在性。
6. 结果：FINDING / NO_CONFIRMED_ISSUE / UNRESOLVED。

## 按需参考

| 条件 | 文件 |
|---|---|
| 跨层契约 | `references/cross-layer-contracts.md` |
| AscendC 检查 | `references/ascendc-checks.md` |
| 并发 | `references/concurrency.md` |
| 通用约束 | `references/domain-checks.md` |
| Finding 形态 | `references/examples.md` |
| 踩坑 | `references/gotchas.md` |
| 共用纪律 | `references/evidence-quality.md` / `references/completeness.md` / `references/artifact-freshness.md` |
