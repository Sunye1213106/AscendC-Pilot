<task>
核对测试仓跑测收据是否覆盖 ScenarioSet 中的精度与性能义务。
</task>

<context>
- Obligations: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/ce/impact/obligations.yaml`
- Scenario set: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/ce/scenarios/scenario_set.yaml`
- External evidence: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/ce/verify/external_evidence.yaml`

方法细节见打包 Skill `code-engineering`。
</context>

<instructions>
1. 精度义务只接受 golden 比对收据；性能义务只接受 profiling 收据。审查叙述不是测量。
2. 缺少测试仓适配器时，精度/性能保持未关闭，并记录 `harness_missing`。
3. Host replay 只能佐证 dispatch / TilingKey，不能关闭 `P-*` / `F-*`。
4. 不得把外部收据直接写成排除项。
</instructions>

<output>
列出每条精度/性能义务的 `covered` / `open` 与对应收据路径；未覆盖的保持 Open。写入 `ce/verify/harness_evidence_check.yaml`。
</output>
