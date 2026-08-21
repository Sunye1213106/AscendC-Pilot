# 证据不变量（面向模型，短）

1. 搜索 / UO 图定位 ≠ 证明。高置信度需要磁盘上的源码窗口。
2. `confidence: high` / `source_verified: true` 必须同时具备该窗口的 `evidence_window_sha256` 与连续 `evidence_snippet`（窗口子串）。
3. 禁止编造哈希、行号，或粘贴不连续片段。邻窗 / 错窗 sha 复用视为伪造。
4. 缺席断言需要机器可检查的否定证据，不是「我搜了很多」。
5. 闭合账本：`T = (R ∩ T) ∪ E`，且 `R ∩ E = ∅`。R 只来自真实 oracle 的成功观测。E 只来自经审查的源码引理。`Replay reject ≠ E`。搜索耗尽、样本缺失、模型分数不能单独进 E。

全文：`pilot/policies/evidence/POLICY.md`。
