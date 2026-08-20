# Policy: output-quality

## Purpose

产物诚实、角色写面分离、schema 合规。置信度合同见 `evidence`，本策略不另开例外。

## Rules

1. Producer ∩ Referee 可写面 = ∅。
2. Producer 不得写 referee verdict。
3. Referee 不得改被审产物正文。
4. unresolved / needs_human 必须显式诚实。
5. 只写声明的输出合同路径；禁止改 contracts（测项合同属 TG 流程）当处于 UO Action。
6. 禁止编辑引擎独占正文（引擎生成的 IR / 收据仅引擎写入）。
