<task>
调查当前 unresolved CodeMap semantic residuals；分类根因并给出 deterministic engine 改进建议。
</task>

<context>
确定性 CompilerFacts 与 CodeMap Pass 是 canonical `.uo` 的唯一事实来源。
你的职责是解释为什么某个 blocker 仍然 unresolved，而不是猜测一个 relation 写进 `.uo`。
</context>

<instructions>
1. 读取 `uo/ir/unresolved.yaml` 与当前 bundle 指定的 blocker ids。
2. 用结构化 CodeMap 查询 + 最小源码窗口定位证据。
3. 对每个 blocker 输出分类：`deterministic_engine_gap` / `unsupported_operator` /
   `needs_loop_summary` / `needs_interprocedural` / `opaque_expression` / `missing_evidence` 等。
4. 说明缺少的 analyzer 能力（模块/pass），并给出可复现的源码证据位置。
5. 证据不足时诚实保留 unknown；禁止编造闭合关系，禁止建议把 LLM 推断写入 canonical `.uo`。
</instructions>

<output>
只写调查报告（`gap_investigation.yaml` / `report.yaml`）。
不要修改 canonical `.uo` / UO IR 产品面，不要产出可 merge 的 gap patch。
</output>
