# TG plan-fuse

把 **`tg/init.yaml` + Planning Context** 融成一份 `plan.md`。上半散文，下半 YAML 义务表。正式文件由 `plan_promote` 写入。

本步 refs：`references/planning.md`、`references/plan-heuristics.md`、`references/planning-gotchas.md`、`references/planning-context.md`。

## 两项核心输入

1. **Harness contract**：`tg/init.yaml`（强制）。提供测试表列、值域、生成器、golden/compare、precision/performance 跑测入口等可执行控制面。
2. **Planning Context**（强制）。说明这次为什么测、改了什么、影响什么、哪些风险必须证明。来源按可用性读取，不要假定必须先做过 PR review：
   - 同一会话 `/ce-review` 结论（若 runtime 写了 `context/review_planning_context.md` 也可以读）；
   - `/ce-plan` 的「测试内容」；
   - 用户显式给出的测试计划/目标；
   - `session_handoff.md` 中等价的明确测试意图；
   - 用户明确只要用例、主控已综合的 `/uo-query` 结论（写在本步 stub 里）。

`.uo` 不是第三份“意图输入”，而是后续用 `uo-query` 给 Planning Context 做语义落根和可达性证明的事实权威。本步查图用 `pilot_cli`。

缺 Planning Context 时返回 `PLAN_CONTEXT_REQUIRED`；缺 `tg/init.yaml` 由 workflow gate 阻断。不要只看 PR URL 重新猜影响范围。

## 顺序

1. 读取 `tg/init.yaml`，确认可以控制的列、生成器与现有精度/性能入口。
2. 读取本次 Planning Context，拆出 changed/affected scope、风险、test intent 和 validation targets；不要重新审查 PR，也不要重新解释自然语言输入。
3. 对每条目标用 **uo-query** 求证涉及的输入、分支、tiling/kernel 契约和可观测行为，并 root 到 `init.yaml` 的列。
4. 将目标展开成计划义务：
   - **coverage**：改动直接路径、影响路径、边界/反例、必要组合；
   - **precision**：结合 init.yaml 的 compare/golden 能力说明输入、期望和判定；
   - **performance**：只有 init.yaml 暴露了可执行性能入口时才规划性能 case/口径；否则明确 gap，不发明 NPU 指标；
   - **solve metric**：每条义务必须给可执行的 replay 或 derived 命中判据，以及 solve 完成的闭合条件。
5. root 不到的目标列入 `untestable`（带 reason）；缺列、缺脚本、或生成器造不出（含随机数）写 `test_harness_gap` **说明书**（缺什么、应改测试仓哪一段、期望接口），交 `/ce-apply`，不得伪造成已覆盖。

## 控制面 = 列

- 算子真实 INPUT 缺列 → `test_harness_gap` 补列，先 `/ce-apply` 改测试仓。
- 列有但 `generate_inputs` 造不出（含随机数分布/种子） → `test_harness_gap` 改生成器。
- 没有测试脚本仓、但义务需要可执行 harness → `test_harness_gap` 说明书，让 `/ce-apply` 生成脚本仓。
- root 不到 → `untestable`（带 `reason`），不进义务表。
- UO 维度不要求和表头同名。允许确定性派生，例如 `IsNEqual := N1 == N2`、`IsTnd := Input_Layout == TND`；但 recipe 必须只依赖 `init.yaml` 可控列并能复算。

## 自动判定指标

- `replay`：Host tiling（无 NPU）看 key / TD / OP_CHECK / 分支；写 `hit.pred`。
- `derived`：当前行输入 + 已确认代码逻辑可推；写 `hit.formula`。

精度/性能执行入口来自 `init.yaml`，但不要把尚未实际执行的上板误差/耗时伪造成 Host replay receipt。YAML 义务字段保持 `id, why, uo{query,span}, control{columns,recipe}, class, hit, cover`。

覆盖：L0 每维一次 / L1 成对 / L2 有界笛卡尔 / L3 异常。全量 tilingkey 只在 Planning Context 明确要求时做。

## 禁止

- 写正式 `tg/plan.md`
- 重新做 PR review 或重新解析自然语言输入
- 没有 Planning Context 就静默生成默认计划
- 默认 T=D / `tilingkey_full_coverage`
- 义务不 root 到 init.yaml 列
