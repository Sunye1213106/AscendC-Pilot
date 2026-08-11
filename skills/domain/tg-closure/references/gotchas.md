# TG Closure — Gotchas

- **闭合定义是集合等式**：`T = (R∩T) ∪ E`；“看起来覆盖了”不是 PASS。
- **R 只来自真实 Host witness**（或 L3 经 TD dump + branch_eval 的 outcome）；solver SAT  alone 不能进 R。
- **E 只来自可审计源码引理 / 字段 pin**：命名猜测、经验规则不得进 excluded。
- **不得改 D**：声明集合来自 Kernel；undeclared key 进报告，不进 D。
- **CONFLICT 优先于 OPEN**：同一 key 既 witnessed 又 excluded 时先消冲突。
- **Agent 不得 declare closure PASS**：证书与 gate 由 harness / referee 判定。
