# TG Closure — Gotchas

- **每轮立刻分析**：Replay 后马上看 `growth_match`；expected → 轮内 lemma 消化 reject，unexpected → 用已发现 R + 源码定向构造。禁止“先搜完再证明”。
- **闭合定义是集合等式**：Solve 闭合 `T = (R∩T) ∪ E`；全覆盖证书额外要求 `D = (R∩D) ∪ E`。overlay `scenario_targeted` 的 T 是 ScenarioSet，不是 `T=D`。
- **R 只来自真实 Host witness**（或 L3 经真实 same-key replay + TD/STATE observation + branch_eval 的 outcome）；solver SAT alone 不能进 R。
- **L3 off-key 不计覆盖**：候选 replay 后实际 TilingKey 与目标 key 不一致时，只记录 rewrite/诊断证据，不能结算 TD 或 Kernel branch obligation。
- **candidate target / set-cover claim 不是 runtime evidence**：`solver_goals`、`covers`、静态 producer-cone 命中都只能指导搜索，不能把 obligation 标为 `COVERED`。
- **decoder 缺失必须 fail-open-debt / fail-closed-certificate**：无法解 raw `###TD` 时保持相关 obligation open，禁止用 TilingData over-approx 冒充实测值。
- **同一份 runtime ledger**：L3 必须更新 canonical `obligation_inventory.yaml`，不得另建一份只给 generator 自己看的“已覆盖”账本。
- **E 只来自可审计源码引理 / 字段 pin**：命名猜测、经验规则不得进 excluded。
- **不得改 D**：声明集合来自 Kernel；undeclared key 进报告，不进 D。
- **CONFLICT 优先于 OPEN**：同一 key 既 witnessed 又 excluded 时先消冲突。
- **Agent 不得 declare closure PASS**：证书与 gate 由 harness / referee 判定。
