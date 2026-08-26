# Policy: output-quality

产物诚实、角色写面分离。置信度合同见 `evidence`。

1. Producer 写入面 ∩ Referee 写入面 = ∅。Producer 不得写 referee verdict；Referee 不得改被审产物正文。
2. unresolved / needs_human 必须显式留下。
3. 只写已声明的 output-contract 路径。禁止改引擎独占正文（IR / 收据仅引擎写入）。
