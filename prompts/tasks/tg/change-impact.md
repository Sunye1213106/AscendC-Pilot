<task>
根据 PR 改动清单与 CodeMap，分析改动影响了哪些控制路径。只写本步草稿。
</task>

<input>
- Goal artifacts.changeset
- CodeMap（已有 .uo 时）
</input>

<delta_constraints>
1. affected / changed_paths 必须能对上 diff 或 CodeMap。
2. 不要做 code review，不要写测试义务。
</delta_constraints>

<output>
写入本步草稿 YAML。不要写正式 Goal 文件。
</output>
