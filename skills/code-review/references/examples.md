# 审查示例与 Finding 形态

**何时加载**：准备写 finding，或核对报告结构时。

## Finding 推荐结构

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

## 高质量 finding

- 明确触发条件 + 被违反约束 + `path:line` + 可观察影响
- 已尝试推翻 H1 并记录为何仍成立
- 快速入口：短描述 + 一行证据即可，不要贴大段报告

## 误报常见原因

- 忽略更早 guard
- 把 partial 索引当成「没有其他调用者」
- 风格偏好当作缺陷
- 未解析 overload 就下结论
