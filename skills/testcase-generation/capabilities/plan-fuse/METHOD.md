# TG plan-fuse

把 test_request 融进 **一份** `plan.md`。上半散文，下半 YAML 义务表。正式文件由 `plan_promote` 写入。

## 顺序

1. 读 `tg/init.yaml`（强制）和 `.uo`。
2. 有则读 test_request（`--intent` / 对话 / `ce/plan/*_plan.md` / 审查结论 / `session_handoff.md`），拆成精度考虑和性能考虑（可重叠）。禁止读 `tg_plan_intent.yaml`。
3. 对每条做 **uo-query**，root 到 CSV/XLS 列，有限覆盖后写出义务。
4. 没有意图时默认 L0，仍要有能 root 的精度/性能义务。禁止空表，禁止 T=D。

## 控制面 = 列

- 算子真实有的 INPUT 缺列 → `test_harness_gap` 补列，先 CE 改测试仓。
- 列有但 `generate_inputs` 造不出 → `test_harness_gap` 改生成器。
- root 不到 → 列入 `untestable`（带 `reason`），不进义务表。

## 指标只有两类

- `replay`：Host tiling（无 NPU）看 key / TD / OP_CHECK / 分支；写 `hit.pred`。
- `derived`：这行输入 + 代码逻辑可推；写 `hit.formula`。

没有第三类「上板误差/耗时」。YAML 字段：`id, why, uo{query,span}, control{columns,recipe}, class, hit, cover`。

覆盖：L0 每维一次 / L1 成对 / L2 有界笛卡尔 / L3 异常。全量 tilingkey 只在 intent 点名时做。

## 禁止

- 写正式 `tg/plan.md`
- 默认 T=D / `tilingkey_full_coverage`
- 义务不 root 到 init.yaml 列
