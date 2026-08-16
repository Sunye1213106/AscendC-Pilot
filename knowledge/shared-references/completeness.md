# 分析完整性（共享）

**何时加载**：结论含「全部 / 唯一 / 从不 / 没有其他 / 必然 / 不可能」时。

## 原则

```text
artifact existence ≠ semantic completeness
index miss ≠ absence in source
```

完整性必须描述**真正观察到什么**，不是计划抽什么。

## 至少检查

- declared scope vs observed entities
- unresolved / skipped / partial relations
- writers / callers / 宏上下文 / 模板实例是否闭合
- 对当前命题是否已补齐必要缺口

不足时：继续读源码，或返回 `INSUFFICIENT` / `UNRESOLVED`。详见各 domain 的 completeness / `evidence-quality.md`。
