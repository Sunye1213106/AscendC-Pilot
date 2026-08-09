---
name: uo-kb-build
description: >
  建立或审校算子理解知识库（UO KB）：确认分析范围、评估抽取完整性、
  消解语义缺口、审查 KB 质量。面向任意 AscendC/C++ 算子源码项目。
---

# UO 知识库建立

目标：证据充分的算子 KB，而非「扫过一遍文件」。

```text
确认范围 → 评估抽取完整性 → 定位缺口 → 消解/标注 → 审查 → 可导出投影
```

权威分层见 `references/authority-model.md`。  
完整性见 `references/completeness.md` 与 `_shared/completeness.md`。

## 要点

1. **范围**：确认根目录与 architecture；结论不超出范围。
2. **完整性**：`existence ≠ completeness`；receipt 驱动，非计划 profile。
3. **推导**：有表达式 ≠ exact；见 `references/derivation-quality.md`。
4. **缺口**：结构查询 → 最小源码 → 补丁或 `UNRESOLVED`。
5. **审查**：产消一致、锚点齐全；LLM digest 不得回写权威层。

## 按需参考

| 条件 | 文件 |
|---|---|
| 权威/投影/digest | `references/authority-model.md` |
| 文件在但语义空 | `references/completeness.md` |
| 字段推导质量 | `references/derivation-quality.md` |
| 抽取覆盖 | `references/extraction-quality.md` |
| 共享证据纪律 | `_shared/evidence-quality.md` |
| 投影是否过期 | `_shared/artifact-freshness.md` |
