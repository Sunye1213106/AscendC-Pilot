<task>
把本次改动编译成一份覆盖模型：Target、Dimension、Guard、Exclusion。只交 `schema: tg-plan/v3` YAML 全文，不写散文，不落盘。
</task>

<input>
- Init：`<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/tg/init.yaml`
- Packet：`runs/<run_id>/receipts/plan_scope_packet.yaml`
- CodeMap：已经编进 packet（`behavior_candidates` / `observation_catalog` / `controls`）。只读 packet，不要自己再 `uo_query`
- 可读源码：`environment_capabilities.yaml` 的 `source_scope.file_paths`，以及 packet / FOCUS 给出的 `file:line` 窗

Packet 就是本次改动的全部范围，也是唯一观测词表。字段怎么取名只认 `packet.usage`。`plan_route_card` 是给 Primary 拆路的，Owner 不要用它代替 observation_catalog。

方法论只读 Task 给出的 session 内 `method.md` 与 refs，不要另搜副本。禁止去 `~/.config`、`~/.cursor`、`cognitive-skills`、其它 checkout 搜第二份方法论。
</input>

<method>
算子语义已经在 packet 里。源码只打开 packet / 当前 Action 给出的文件与行范围。禁止 `git diff HEAD`、全仓 Grep 反推 PR。改动范围已经在 packet 里。已删函数看 `deleted_symbols` / hunk `deleted_lines`，不要靠 HEAD UO 恢复。新写点看 `modified_writes` 与 `behavior_candidates.*.writers`。
</method>

<output>
最终消息正文就是 `schema: tg-plan/v3` YAML 全文。Host 只读最终消息。
</output>
