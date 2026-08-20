# 完整性（UO KB）

**何时加载**：声称范围已覆盖、gate 通过、或看到 required 产物「文件存在」时。

## 硬规则

```text
artifact existence ≠ semantic completeness
```

`path.exists()`、空壳 YAML、`not_extracted` 占位 **不能** 当作抽取完成。

完整性必须描述**真正抽到了什么**，不能描述「计划抽什么」或默认 profile。

## 应检查

- declared scope（机器校验后的 Source Scope / Clang closure，非人工确认清单）
- expected entities vs observed entities
- unresolved / skipped / partial relations
- source coverage（范围内文件——含 SHARED common——是否进入抽取）
- 关键字段是否有定义与消费，而非仅有表头

## 危险模式

| 现象 | 为何危险 |
|---|---|
| required 文件在，内容 `not_extracted` | gate 被「文件存在」骗过 |
| completeness 抄自 env/profile | 与真实 extraction receipt 无关 |
| 索引 partial 却报「无其他符号」 | 假完备 |

不足时：补抽取、记 gap，或阻断；禁止声称完备。
