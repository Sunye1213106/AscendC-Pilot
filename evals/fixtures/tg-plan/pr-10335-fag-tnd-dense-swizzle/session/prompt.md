<task>
把本次改动编译成一份覆盖模型：Target、Dimension、Guard、Exclusion。只交 `schema: tg-plan/v3` YAML 全文，不写散文，不落盘。
</task>

<input>
- Init: `D:/PR-review/TEST/.ascendc-pr/gitcode.com--cann--ops-transformer--pr-10335/attention/flash_attention_score_grad/.ascendc-pilot/arch35/tg/init.yaml`
- Packet: `D:/PR-review/TEST/.ascendc-pr/gitcode.com--cann--ops-transformer--pr-10335/attention/flash_attention_score_grad/.ascendc-pilot/arch35/runs/RUN_10335_eval/receipts/plan_scope_packet.yaml`
- UO query authority: `D:/PR-review/TEST/.ascendc-pr/gitcode.com--cann--ops-transformer--pr-10335/attention/flash_attention_score_grad/.ascendc-pilot/arch35/uo`
- Source scope: `D:/PR-review/TEST/.ascendc-pr/gitcode.com--cann--ops-transformer--pr-10335/attention/flash_attention_score_grad/.ascendc-pilot/arch35/runs/RUN_10335_eval/actions/plan_ingest/environment_capabilities.yaml` 的 `source_scope.file_paths`（路径相对 project_root）
- project_root: `D:/PR-review/TEST/.ascendc-pr/gitcode.com--cann--ops-transformer--pr-10335/attention/flash_attention_score_grad`
</input>

<method>

先读 `D:/PR-review/AscendC-Pilot/evals/fixtures/tg-plan/pr-10335-fag-tnd-dense-swizzle/session/method.md`，那就是本窗形式规范。禁止打开 `evals/fixtures`。禁止读 plan.golden.md / rubric.yaml / grade_*.py / session/trial*.yaml。

算子语义已经在 packet 里。源码只打开 packet / 当前 Action 给出的文件与行范围。禁止 `git diff HEAD`、全仓 Grep 反推 PR。改动范围已经在 packet 里。已删函数看 `deleted_symbols` / hunk `deleted_lines`，不要靠 HEAD UO 恢复。新写点看 `modified_writes` 与 `behavior_candidates.*.writers`。
</method>

<output>
最终消息正文就是 `schema: tg-plan/v3` YAML 全文。Host 只读最终消息。
</output>
