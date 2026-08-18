<task>
读用户原文，判断要跑哪些用户工作流（目录见 session refs/workflow-catalog.md）。
</task>

<input>
- 用户原文在本步 session prompt 与 run state 的 intent 字段，原样保留。
- 当前若已有 project / architecture，只作上下文，不是解析器。
- 工作流目录由 Harness 注入，不要猜 slash。
</input>

<delta_constraints>
1. 不要写执行顺序或前置工作流。
2. PR URL / diff / local 只是 source，不隐含某个 workflow。
3. 不要发明目录外的 id。不要输出 skill 名。
</delta_constraints>

<output>
写入本步草稿 YAML：objective_zh、source、needed_workflows、constraints。不要写 Goal 正式文件。
</output>
