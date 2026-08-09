# 权威分层模型

**何时加载**：决定 CodeMap 事实写哪里、能否用模型摘要驱动下一轮抽取、或审查「假权威」污染时。

## 分层

```text
Source
  ↓ Clang CompilerFacts + deterministic Passes
Semantic authority = operator.<arch>.uo（统一 CodeMap）
  ↓
uo-dump / query views（临时展开，非持久权威）
  ↓
LLM digest / explanation（说明层）
```

| 层 | 性质 | 可否被下一轮当静态事实 |
|---|---|---|
| Semantic authority (`.uo`) | 抽取 + 已审 patch | 是 |
| Dump / query views | 可由 `.uo` 重建 | 是（须可重算） |
| LLM digest | 解释/导航 | **否** |

## 硬规则

```text
LLM summary 不得成为下一轮静态事实的隐式输入
```

模型提出的语义补丁必须显式走：

```text
candidate → evidence → review → accepted fact
```

不得悄悄写回 authority，也不得用 digest 冒充实抽取结果。

## 与完整性的关系

「文件在 projection 路径上」不等于 authority 已填充。见 `completeness.md`。
