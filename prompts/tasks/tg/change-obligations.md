<task>
把已校验的改动影响收成结构化测试义务（change / condition / affected / contrast / boundaries / required_hits）。
</task>

<input>
- Goal artifacts.impact
- CodeMap 标识符
</input>

<delta_constraints>
1. 标识符必须存在。
2. 不要写 tg/plan.md 或 cases 表。
3. 不要把审查意见当成义务。
</delta_constraints>

<output>
写入本步草稿 YAML，字段 obligations: []。不要写正式产物。
</output>
