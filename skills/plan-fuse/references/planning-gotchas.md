# 计划易错点

**何时加载**：写 `plan.md` 义务表时对照。

- **控制面是列**：义务必须 root 到 `init.yaml` 的 CSV/XLS 列，不是全部合法 Key。依赖列禁止当独立笛卡尔维。
- **禁止默认全量 tilingkey**：全量只在意图点名时做。
- **融合，不是先套覆盖再贴标签**：有意图就拆精度/性能考虑；没有意图默认 L0，仍要能 root 的精度/性能义务。
- **指标只有 `replay` 和 `derived`**：没有第三类上板误差/耗时。
- **root 不到另列 `untestable.reason`**：不要写成 `class: untestable`。
- **缺列或缺 `generate_inputs` → `test_harness_gap`**：先改测试脚本仓，禁止 start solve。
- **批准前可变，批准后冻结**：`approved` 写在 `plan.md` YAML 围栏里。
