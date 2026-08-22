<task>
调查当前 unresolved CodeMap semantic residuals：分类根因，指出确定性引擎还缺什么能力。
</task>

<context>
Host/Kernel IR 与确定性 CodeMap Pass 是 canonical `.uo` 的唯一事实来源。本任务解释 blocker 为何未闭合，而不是把 LLM 推断写进 `.uo`。
方法细节见打包 Skill `uo-investigate`。
</context>

<instructions>
1. 读取 `uo/ir/unresolved.yaml` 与当前 bundle 指定的 blocker ids。
2. 用结构化 CodeMap 查询 + 最小源码窗口取证。
3. 对每个 blocker 分类，例如：`deterministic_engine_gap` / `unsupported_operator` / `needs_loop_summary` / `needs_interprocedural` / `opaque_expression` / `missing_evidence`。
4. 说明缺少的 analyzer 能力（模块/pass），并给出可复现源码位置。
5. 证据不足保留 unknown；禁止编造闭合关系，禁止建议把 LLM 推断 merge 进 canonical `.uo`。
</instructions>

<output>
只写调查报告：`uo/ir/gap_investigation.yaml` 与 Action 声明的 `report.yaml`。
不修改 canonical `.uo` / UO IR 产品面，不产出可 merge 的 gap patch。
</output>
