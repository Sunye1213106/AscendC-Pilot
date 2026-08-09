---
name: uo-codemap-build
description: >
  编译 AscendC CodeMap（operator.uo）：确认分析范围、评估 CompilerFacts /
  确定性 Pass 完整性、消解语义缺口、审查 CodeMap 结构一致性。
  面向任意 AscendC/C++ 算子源码项目。原名 uo-kb-build。
---

# UO CodeMap 建立

目标：单个可查询的 AscendC CodeMap（`.uo`），而非多层 YAML 投影。

```text
确认范围 → Clang CompilerFacts → 确定性 Pass → 缺口消解 → 写入 .uo → 审查
```

权威分层见 `references/authority-model.md`。  
完整性见 `references/completeness.md` 与 `_shared/completeness.md`。

## 要点

1. **范围**：确认根目录与 architecture / BuildVariant；结论不超出范围。
2. **Compiler vs AscendC**：Clang 只产出 CompilerFacts；AscendC 语义由确定性 Pass 写入统一 CodeMap。
3. **完整性**：`existence ≠ completeness`；receipt / summary 驱动。
4. **推导**：有表达式 ≠ exact；见 `references/derivation-quality.md`。
5. **缺口**：仅无法确定的 semantic gap 允许 agent resolve；能结构检查的不要启 LLM。
6. **产物**：正式权威是 `.ascendc-pilot/uo/<op>.<arch>.uo`；YAML 仅 `uo-dump` 临时展开。

## 按需参考

| 条件 | 文件 |
|---|---|
| 权威/投影/digest | `references/authority-model.md` |
| 文件在但语义空 | `references/completeness.md` |
| 字段推导质量 | `references/derivation-quality.md` |
| 抽取覆盖 | `references/extraction-quality.md` |
| 共享证据纪律 | `_shared/evidence-quality.md` |
| 投影是否过期 | `_shared/artifact-freshness.md` |
