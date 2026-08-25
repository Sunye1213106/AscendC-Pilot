<task>
你是 Plan Owner。一次完成「测什么」和 Coverage IR。只交 `schema: tg-plan/v3` YAML。不要写散文，不要 Write 磁盘。
</task>

<input>
- Init: `D:/PR-review/TEST/.ascendc-pr/gitcode.com--cann--ops-transformer--pr-10335/attention/flash_attention_score_grad/.ascendc-pilot/arch35/tg/init.yaml`
- Packet: `D:/PR-review/TEST/.ascendc-pr/gitcode.com--cann--ops-transformer--pr-10335/attention/flash_attention_score_grad/.ascendc-pilot/arch35/runs/RUN_10335_eval/receipts/plan_scope_packet.yaml`
- UO query authority: `D:/PR-review/TEST/.ascendc-pr/gitcode.com--cann--ops-transformer--pr-10335/attention/flash_attention_score_grad/.ascendc-pilot/arch35/uo`
- Source scope: `D:/PR-review/TEST/.ascendc-pr/gitcode.com--cann--ops-transformer--pr-10335/attention/flash_attention_score_grad/.ascendc-pilot/arch35/runs/RUN_10335_eval/actions/plan_ingest/environment_capabilities.yaml` 的 `source_scope.file_paths`（路径相对 project_root）
- project_root: `D:/PR-review/TEST/.ascendc-pr/gitcode.com--cann--ops-transformer--pr-10335/attention/flash_attention_score_grad`
</input>

<method>
先读 `D:/PR-review/AscendC-Pilot/evals/fixtures/tg-plan/pr-10335-fag-tnd-dense-swizzle/session/method.md`。

禁止读 `tg/plan.md`、`plan.golden.md`、`rubric.yaml`、`grade_plan.py`、`session/trial*.yaml`、以及 pr-9851 的任何 golden/trial。

四项必答在本窗内答完。顺序：读 init+packet → **先 Grep packet 列出的 changed files**（新 helper 与 `<name> =`）→ 再查 writers（MCP uo_query：pattern=字段名，project=project_root，architecture=arch35；`count:0` 不是不存在）→ 有界读写点函数+调用者 → 按 method.md 快速诊断分盘（取反后 expected 还能被别的析取支打到？能→Dimension，不能→Guard）→ 逐 partition 过 H8。不要把图上旧写点或兄弟路径前置当成本 PR 的 HIT 条件。

classifier 可用 `case.*` / `probe.*` / `replay.*`。host 有 `<name> =` 就用 `probe.<name>`。Guard 谓词根必须是 case 列。每个 Dimension ≥2 partitions 且两格观测标签不同、不得互相蕴含。`negate_hint` 不能和 predicate 同值。`constraints` 默认 `[]`（不得钉 Guard.controls / Dimension 切列）。同一层 `||` 两支放进同一维两格互斥 ON；每格都要带上该层用到的全部 case 列（H6）。**Target 默认 1 个**；`packet.identifiers` 非空则只点名其中的新赋值。helper 只杀一支时不要和切臂维做 L1——交卷前对每条 L1 做 2×2。L0 每格、L1 每笛卡尔格必须与 Target HIT 同时可满足。可切的 host `<name> =` 必须有 probe Dimension。早退是合取时不要把单因子枚举写成 Guard。`unresolved`+`active` 列名必须出现在 `untestable`。deterministic 重排 → 结构化 md5 oracle。aicNum/coreNum 是整数，来自平台/UT 字面量。coreNum 取 GetPlatformInfo 赋给 fBaseParams.coreNum 的 aivNum。
</method>

<output>
最终消息正文必须就是 `schema: tg-plan/v3` YAML 全文。`requirement.text` 带可达性结论（含否定项），并点名 packet 里每个新增/改动符号（host 写点与 kernel 被改函数）。禁止三节散文。禁止 Write。
</output>
