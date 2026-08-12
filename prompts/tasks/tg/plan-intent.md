<task>
确定本轮 TG 的精确 TilingKey 目标选择器。不构造用例、不跑 replay、不断言可达性。
</task>

<context>
- Project: `<PROJECT_ROOT>`
- TG: `<TG_ROOT>`

算子/架构来自 Pilot 与 `.uo`。Plan 只冻结“要覆盖什么”；是否可达由后续 Solve + Replay/引理决定。
方法细节见打包 Skill `testcase-generation`。
</context>

<instructions>
1. 用户已给明确 TilingKey 列表 → `target_mode: explicit_keys`。
2. 用户已给维度/取值过滤 → `target_mode: dimension_filter`。
3. 用户未指定目标 → `target_mode: all_declared`（T = 当前 Kernel 声明域 D 全集）。
4. 不要推断不可达 key、不要推导 19 维公式、不要在规划阶段调用全局 SAT。
5. 目标请求矛盾或歧义时显式标出，禁止静默扩大范围。
</instructions>

<output>
只返回构建 `target_set.yaml` 所需的 planning intent：target mode、显式 keys 或维度过滤、以及任何阻塞性歧义。
后续确定性 `plan_build` 会校验 T ⊆ D 并冻结 hash。
</output>
