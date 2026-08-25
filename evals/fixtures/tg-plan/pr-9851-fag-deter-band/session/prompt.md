<task>
你是 Plan Owner。一次完成「测什么」和 Coverage IR。只交 `schema: tg-plan/v3` YAML。不要写散文，不要 Write 磁盘。
</task>

<input>
- Init: `D:/PR-review/TEST/.ascendc-pr/gitcode.com--cann--ops-transformer--pr-9851/attention/flash_attention_score_grad/.ascendc-pilot/arch35/tg/init.yaml`
- Packet: `D:/PR-review/TEST/.ascendc-pr/gitcode.com--cann--ops-transformer--pr-9851/attention/flash_attention_score_grad/.ascendc-pilot/arch35/runs/RUN_20260824_091650_b52031ff/receipts/plan_scope_packet.yaml`
- UO query authority: `D:/PR-review/TEST/.ascendc-pr/gitcode.com--cann--ops-transformer--pr-9851/attention/flash_attention_score_grad/.ascendc-pilot/arch35/uo`
- Source scope: `D:/PR-review/TEST/.ascendc-pr/gitcode.com--cann--ops-transformer--pr-9851/attention/flash_attention_score_grad/.ascendc-pilot/arch35/runs/RUN_20260824_091650_b52031ff/actions/plan_ingest/environment_capabilities.yaml` 的 `source_scope.file_paths`（路径相对 project_root）
- project_root: `D:/PR-review/TEST/.ascendc-pr/gitcode.com--cann--ops-transformer--pr-9851/attention/flash_attention_score_grad`
</input>

<method>
先读 `D:/PR-review/AscendC-Pilot/evals/fixtures/tg-plan/pr-9851-fag-deter-band/session/method.md`，那就是本窗完整方法。`references/*.md` 通常不落盘；Read 不到就继续。

禁止读 `tg/plan.md`、`plan.golden.md`、`rubric.yaml`、`grade_plan.py`、`session/trial*.yaml`。

四项必答在本窗内答完：
- **A 可控面** — `confirmed`+`active` 列集合。其余列不得进 `controls` / `construct_hint.columns`。
- **B 触发门禁** — 唯一写点的路径条件含每个被跨过早退的否定项。逐项标：直接列 / 派生 / 环境 / 可 probe 的 host 局部量。禁止把「非列」一律写成 opaque。
- **C 构造种子** — 现有表只提供 seed。0 行不是 gap。
- **D 新增 vs 既有** — 分开说；判不准标「未证实」。

顺序：读 init+packet → **先 Grep packet 列出的 changed files**（新 helper 与 `<name> =`）→ 再查 writers（MCP uo_query：pattern=字段名，project=project_root，architecture=arch35；`count:0` 不是不存在）→ 有界读写点函数+调用者 → 按 method.md 快速诊断分盘（取反后 expected 还能被别的析取支打到？能→Dimension，不能→Guard）→ 逐 partition 过 H8。不要把图上旧写点或兄弟路径前置当成本 PR 的 HIT 条件。

classifier 可用 `case.*` / `probe.*` / `replay.*`。多值 TILING_FIELD：Target 用 `derived`+`in`（`replay_field` expected 必须是标量）；Dimension 每值 `eq` 一格。host 有 `<name> =` 就用 `probe.<name>`。Guard 谓词根必须是 case 列。

`constraints` 默认 `[]`。不得固定 Dimension 正在切的列，也不得固定 Guard 的 controls。同一层 `||` 两支放进同一维两格互斥 ON；每格都要带上该层用到的全部 case 列（H6）。L0 每格、L1 每笛卡尔格必须与 Target HIT 同时可满足——交卷前对每条 L1 做 2×2。每个 Dimension ≥2 partitions 且两格观测标签不同、不得互相蕴含。可切的 host `<name> =` 必须有 probe Dimension（classifier=`probe.<name>`）。**Target 默认 1 个**；`packet.identifiers` 非空则只点名其中的新赋值。早退是合取时不要把单因子枚举写成 Guard（取反早退合取后仍 HIT 的取值必须有 partition）。`unresolved`+`active` 列名必须出现在 `untestable`。oracle 用结构化条目（含 md5）。aicNum/coreNum 是整数，来自平台/UT 字面量。coreNum 取 GetPlatformInfo 赋给 fBaseParams.coreNum 的 aivNum。H6：入口维两格必须是同一组 case 列——若 sm=3 格用了 B/N2，sm=0 格也要出现 `case.B` 和 `case.N2`（给仍 HIT 的合法值），禁止另一格改切 S2。token 必须写进某维**两格谓词**（`case.Pre_Tockens` 与 `case.Next_Tockens`），只写 `controls` 不算。
</method>

<output>
最终消息正文必须就是 `schema: tg-plan/v3` YAML 全文。`requirement.text` 带可达性结论（含否定项），并点名 packet 里每个新增/改动符号（host 写点与 kernel 被改函数）。禁止三节散文。禁止 Write。
</output>
