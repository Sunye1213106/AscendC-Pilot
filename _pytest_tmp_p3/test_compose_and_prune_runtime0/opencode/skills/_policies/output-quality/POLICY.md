# Policy: output-quality

## Purpose

产物诚实、角色写面分离、schema 合规。

## Rules

1. Producer ∩ Referee 可写面 = ∅。
2. Producer 不得写 referee verdict。
3. Referee 不得改被审产物正文。
4. 不得伪造 high confidence。
5. unresolved / needs_human 必须显式诚实。
6. 只写声明的输出合同路径；禁止改 contracts（测项合同属 TG 流程）当处于 UO Action。
7. 禁止编辑引擎独占正文（如 `summary/confidence_report.md` 正文仅引擎生成）。
