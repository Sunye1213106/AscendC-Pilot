---
name: solve
description: 为未覆盖义务构造输入，对照 Replay 后的 MISS/UNKNOWN 决定 refine、发证明请求或停止。plan 已批准、要求解时使用。不要用于规划覆盖、源码证明、或已 TARGET_HIT 后的精度/性能邻域。
---

# 求解

为 OPEN 义务找 witness。LLM 不宣布 Target HIT；CLOSED 由引擎 `coverage_eval` 写入。Replay `HIT` / `REWRITE` / `REFUSE` ≠ Target HIT。搜不到 ≠ 不可达。本步不证明不可达，不写 exclusion。

## 循环

1. 读 OPEN 义务与 `solve_index.yaml`。
2. 构造缺失 witness，交给引擎按 Plan 谓词展开行并 Replay。
3. 引擎 `coverage_eval` 把义务标成 CLOSED / MISS / UNKNOWN。
4. 对 MISS / UNKNOWN 选下一动作：`refine` / `proof_request` / `stop`。
5. 只有 `CASE_REFINABLE` 才继续换 case。HARNESS / PLAN gap 停止构造。

两阶段：

- 构造 witness：`references/construct.md`
- Replay 分类后选下一动作：`references/replay-classification.md`

程序语义不可达交给 `skills/source-proof/SKILL.md`（发 `proof_request`）。谓词字面冲突由引擎合并时标 unreachable。accepted proof 才能由引擎写 exclusion。已 TARGET_HIT 的精度/性能邻域不在本步，见 `skills/certify/SKILL.md`。
