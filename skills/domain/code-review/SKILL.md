---
name: code-review
description: >
  基于代码知识库、Codemap、源码和变更信息进行代码审查。
  用于分析代码修改、定位潜在缺陷、验证实现一致性、评估影响范围，
  或判断一个改动是否可能破坏已有程序语义。
---

# 代码审查

从代码变更出发，分析它如何影响程序行为，并寻找有源码证据的缺陷。

目标不是总结 diff，而是建立：

```text
代码变化 → 受影响的程序状态 → 传播路径 → 被破坏的约束 → 可观察后果
```

优先报告少量高质量问题，不制造低置信度警告。

## 核心流程

```text
理解改动
 ↓
定位关键符号
 ↓
建立最小影响域
 ↓
识别程序约束
 ↓
追踪执行路径
 ↓
构造失败场景
 ↓
尝试推翻
 ↓
输出结论
```

## 1. 理解改动

先回答：改了什么？为何值或行为会不同？谁产生/消费该状态？在哪些条件下发生？

不要逐行复述 diff。把修改归类为程序语义：控制条件、数据计算、状态写入、接口契约、类型或模板、内存布局、资源生命周期、并发与同步、错误处理、配置或注册、性能路径。

## 2. 定位关键符号

优先通过精确 KB / Codemap：`definition` `writers` `readers` `guards` `callers` `callees` `parents` `children` `roots` `path` `source` `completeness`。

模糊搜索只用于发现候选。确定性分析前必须解析到明确符号。多同名/重载/模板时不得静默择一。

## 3. 建立最小影响域

只扩展与当前问题相关的关系：

- 变量：来源 → 写入 → guard → 变换 → 读取者
- 函数：调用者 → 修改逻辑 → 写入状态 → 被调用函数 → 下游消费
- 配置/编译期：输入条件 → 派生状态 → 分支选择 → 实现路径

## 4. 找到被修改的程序约束

有效缺陷通常意味着某条约束被破坏。常见约束：使用前完成定义；生产者与消费者语义一致；同一状态不同表示一致；分支前提满足实现假设；资源在最后消费者完成前不可复用；同步在合法路径上匹配；边界覆盖支持输入；错误路径不继续使用无效状态。

领域扩展：`references/domain-checks.md`。必须说明违反了什么约束。

## 5. 沿执行路径验证

构造：输入/初始状态 → 修改后条件 → 状态变化 → 下游传播 → 错误行为。

检查 guard、early return、dispatch、调用、覆盖、alias、编译期分支、错误处理。Finding 必须解释：什么条件下，这个改动会产生什么错误结果？

## 6. 检查跨层一致性

同一语义经多层传播时：输入 → 派生状态 → 中间表示 → 调度/配置 → 执行实现。

检查：新状态是否到达所有消费者；枚举/标志含义；字段单位/范围/默认值；分支改状态却未改下游选择；消费者是否隐含生产者不再保证的前提。

AscendC/C++ 专项：`references/ascendc-checks.md`

## 7. 检查边界与特殊路径

仅与当前改动相关时展开：0/1、上下界、`<`/`<=`、整除与向上取整、alignment、tail、空/可选输入、特殊模式、dtype、模板实例、错误返回、初始化与默认值。

## 8. 主动推翻候选问题

报告前尝试证伪：更早 guard？使用前重赋值？修正逻辑？消费者真可达？上层校验已保证？特殊实例？分析是否仅 partial？

反证成立则删除候选；仍不确定则 `UNRESOLVED`。

## 9. 尊重分析完整性

结构化索引用于定位。对「没有其他 writer/caller/consumer」「分支不可达」「值永不出现」须有足够完整性。

**查询未命中 ≠ 源码不存在。**

## 10. Finding 标准

```yaml
severity: high | medium | low
title: ...
condition: ...
invariant: ...
path: [...]
impact: ...
evidence:
  - source: <file:line>
    reason: ...
verification:
  counterargument_checked: true
  notes: ...
```

不报告纯风格问题，除非任务明确要求。

## 11. 结果分类

- **FINDING**：源码支持完整错误路径
- **NO_CONFIRMED_ISSUE**：检查的影响域内无已证实问题（≠ 项目绝对正确）
- **UNRESOLVED**：关键证据不足；明确缺失信息

## 按需参考

- `references/ascendc-checks.md`
- `references/cpp-semantics.md`
- `references/concurrency.md`
- `references/domain-checks.md`
- `references/examples.md`
