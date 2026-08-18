<task>
把意图融进 plan.md：上半散文推理，下半 YAML 义务表。每条义务必须 root 到 init.yaml 的列。
</task>

<input>
- Init: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/tg/init.yaml`
- Intent: `--intent` / 对话 / CE md / `ce/impact/tg_plan_intent.yaml`（有则融合，不做文件强制）
- UO: `<UO_ROOT>`
- Draft: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/runs/<RUN_ID>/actions/plan_fuse`
</input>

<delta_constraints>
1. 控制面是 CSV/XLS 列，不是 T=D / tilingkey 全覆盖。
2. 指标只有 replay（Host tiling，无 NPU）和 derived（公式）。没有第三类上板误差/耗时。
3. root 不到的另列 `untestable`（带 `reason`），不要写成 `class: untestable`。
4. 缺列或 generate_inputs 造不出 → `harness_intent`，先改测试仓。
5. 无意图时默认 L0，仍要有能 root 的精度/性能义务，禁止空表。
</delta_constraints>

<output>
写入本步草稿 markdown：散文 + 末尾 yaml 围栏。不要写正式 `tg/plan.md`。
</output>
