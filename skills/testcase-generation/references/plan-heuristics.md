# 规划启发式（cannbot 口径内化）

**何时加载**：`plan-fuse`。把用户/CE/对话意图融进义务表，不要先套全覆盖再贴标签。

## 融合顺序

1. 读强制产物 `tg/init.yaml`。没有就停，去 `/tg-init`。
2. 有意图就拆：精度考虑 / 性能考虑（可重叠）。来源可以是 `--intent`、对话、`ce/plan/*_plan.md`、`session_handoff.md`。禁止 `tg_plan_intent.yaml`。都没有 → 默认 L0，仍要写出能 root 的精度/性能义务。
3. 每条义务做 uo-query，root 到列，写 `cover`（L0 每维一次 / L1 成对 / L2 有界笛卡尔 / L3 异常）。
4. 全量 tilingkey 只在意图点名时做。禁止默认 T=D。

## 闸门

- 算子真实有的 INPUT 缺列 → `harness_intent` 补列，先 CE 改测试仓，禁止 start solve。
- 列有但 `generate_inputs` 造不出 → `harness_intent` 改生成器。
- root 不到 → `untestable` + `reason`，不进义务表。
- YAML 字段：`id, why, uo{query,span}, control{columns,recipe}, class, hit, cover`。
