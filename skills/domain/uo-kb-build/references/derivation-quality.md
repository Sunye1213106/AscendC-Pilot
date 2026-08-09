# 推导质量

**何时加载**：字段/表达式「已导出」却要用于证明、排除或完整性判定时。

## 核心区别

```text
有表达式（derived）
≠
已准确推导（exact）
```

## 四级质量

| 等级 | 含义 | 允许用途 |
|---|---|---|
| **EXACT** | 决定性依赖已闭合；表达式可作为精确语义 | 导航、候选、**排除型证明** |
| **CONSERVATIVE** | 保守超集；含多余可能值 | 导航、候选生成；**不得**单独证明不可达 |
| **PARTIAL** | 仍有 free var / unresolved guard / 未闭合调用 / alias | 仅提示缺口；不得当完备事实 |
| **UNKNOWN** | 无法形成可信推导 | 标 gap；禁止伪装成功 |

## 硬规则

```text
derived ≠ exact
```

只有 **EXACT**，或针对当前命题已补齐必要 completeness 的结果，才能参与排除型证明。

报告推导结果时至少交代：exactness、free vars、input roots、undecided guards、完整性标记。勿用「表达式很长/很短」代替质量等级。
