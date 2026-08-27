# 精度邻域

**何时加载**：`plan.md` 的 `oracle` 已点精度，并且该变量已经 `TARGET_HIT`。

怎么跑、atol/rtol、golden 以当前仓 `tg/init.yaml` 为准。取值只能从 init domains ∩ harness 能造的输入 ∩ PR 影响到的 dtype/边界里选。

## 选法

- dtype：`supported_dtype ∩ affected_dtype`。没有的 dtype 不要编。
- 边界：合法域上、被改到的边界附近（对齐 vs +1 仅当该维允许不对齐）。
- 最小可复现 shape，须在 harness `generate_inputs` 能力内。
- 有 / 无可选输入，只走合法 shape。
- Disable / 排除行不上 NPU。
- empty / scalar / 零轴：仅当 domains 与 harness 都允许。

## clean 与 stress

- **clean**（normal / zero / near_zero / all_ones，以域内合法值为准）：必过门
- **stress**（big / neg_big / denormal，仅域内存在时）：信息性，不得当唯一硬门

Oracle 是 harness 精度 mode。Host TilingKey `HIT` 不是精度 PASS。
