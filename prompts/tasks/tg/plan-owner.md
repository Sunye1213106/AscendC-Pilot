<task>
你是 Plan Owner。把本次改动编译成一份覆盖模型：Target、Dimension、Guard、Exclusion。只交 `schema: tg-plan/v3` YAML 全文，不写散文，不落盘。
</task>

<input>
- Init：`<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/tg/init.yaml`
- Packet：`runs/<run_id>/receipts/plan_scope_packet.yaml`
- CodeMap：`<UO_ROOT>`，用 `uo_query` 访问
- 可读源码：`environment_capabilities.yaml` 的 `source_scope.file_paths`，以及 packet / FOCUS 给出的 `file:line` 窗

Packet 就是本次改动的全部范围，也是唯一观测词表。`packet.usage` 是字段合同，照它取名。`plan_route_card` 是给 Primary 拆路的，Owner 不要用它代替下面的词表。

激活列不在 `controls.case_allowed` → 只写 `untestable` 并停，禁止再用 replay/probe 绕过 construct 缺口。

| packet 段 | 允许干什么 |
| --- | --- |
| `observation_catalog.replay_allowed` | 只能写成 `replay.<field>` |
| `observation_catalog.replay_forbidden` | 不得写成 `replay.*`；用 `dispatch_map` 或 helper 的 `probe.*` |
| `observation_catalog.probe_candidates` | `probe.*` 的唯一来源 |
| `controls.case_allowed` | `case.*` / controls / `construct_hint.columns` 的唯一来源 |
| `behavior_candidates` | 发现用的词表。`pr_regression` Target 只能引用 `pr_eligible` 且 evidence 含 ownership 关系的符号 |
| `branch_locals` | 被 changed use 消费的局部量；`probeable: true` 才能开 probe |
| `deleted_symbols` | 本次 hunk 删掉、HEAD 图里可能没有的符号 |
| `modified_writes` | 本次 hunk 新增赋值左侧 |

方法论读 Task 给出的 session 内合同路径，不要另搜副本：

- Target 怎么定：`references/target-planning.md`
- Dimension / Guard / Exclusion 怎么判断：`references/coverage-planning.md`

**禁止**去 `~/.config`、`~/.cursor`、`cognitive-skills`、其它 checkout 搜第二份方法论。
</input>

<method>
算子语义先 `uo-query`；源码只打开查询结果或当前 Action 给出的文件与行范围。禁止 `git diff HEAD`、全仓 Grep 反推 PR。改动范围已经在 packet 里。已删函数看 `deleted_symbols` / hunk `deleted_lines`，不要靠 HEAD UO 恢复。新写点看 `modified_writes`。

`kind: pr_regression` 时 Target 必须是 PR-owned observable：writer/assignment 被改，或存在定向 control/data 边。declaration-only 与无方向 neighbor 不得当 Target。
</method>

<output>
最终消息正文就是 `schema: tg-plan/v3` YAML 全文。Host 只读最终消息。
</output>
