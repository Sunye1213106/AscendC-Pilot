<task>
读用户原文，判断要做哪些事（对应 knowledge / change_analysis / test_generation / code_review / implement），以及输入从哪来。
</task>

<input>
- 用户原文在本步 session prompt 与 run state 的 intent 字段，原样保留。
- 当前若已有 project / architecture，只作上下文，不是解析器。
</input>

<delta_constraints>
1. 不要输出可执行工作流链（禁止写 uo-init / tg-plan / ce-review 顺序）。
2. PR URL 只是输入来源，不是意图。
3. 没说过审查就不要填 code_review。
</delta_constraints>

<output>
写入本步草稿 YAML：objective_zh、source、needed_capabilities、constraints。不要写 Goal 正式文件。
</output>
