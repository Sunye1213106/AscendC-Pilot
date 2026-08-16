# CE harness evidence check

核对测试仓跑测收据是否覆盖 ScenarioSet 中的精度与性能义务。不改账本，不把收据写成排除项。

详见 `references/evidence-tiers.md`、`references/evidence-discipline.md`、`references/harness-oracle.md`。

## 方法

1. 读 `ce/impact/obligations.yaml`、`ce/scenarios/scenario_set.yaml`、`ce/verify/external_evidence.yaml`。
2. 精度义务只接受 golden 比对收据；性能义务只接受 profiling 收据。审查叙述不是测量。
3. 缺少测试仓适配器时，精度/性能保持未关闭，并记录 `harness_missing`。
4. Host replay 只能佐证 dispatch / TilingKey，不能关闭 `P-*` / `F-*`。
5. 列出每条精度/性能义务的 `covered` / `open` 与对应收据路径；未覆盖的保持 Open。

## 禁止

- 把外部收据直接写成排除项（X）
- 用审查叙述关闭 precision/perf
