# UO 提速 + TG 闭环：基于 fa-pr13 真实执行记录的优化方案

所有结论都锚定本目录下的真实产物（文件名 + 字段），不引用记忆。
被审计对象：FAG arch35 全量 TilingKey 闭环，D=8705，2026-08-10 16:32→18:01。

---

## 1. 真实执行时间线

时间取自 `artifacts/fa-pr13/` 文件 mtime，状态取自各 JSON 的 `state` 字段。

| 时间 | 记录文件 | 状态 / 关键字段 |
|---|---|---|
| 16:32 | `rebuild_uo_construct.log` | UO 冷启动完成，`extract_host_bundle=311.9s`（见 `uo_cold_baseline.md`） |
| 16:42 | `host_replay_d.log` | 全量 Host replay，R=4121 |
| 16:53–16:58 | `skill_iterate_closure.log` / `round_analyze.log` / `codemap_blame_dims.log` | 迭代驱动 + 残差分析 |
| 17:24–17:27 | `host_ir.py` / `clang_walk.py` / `uo_walk.cpp` | UO 提速改动落盘 |
| 17:31 | `lemma_closure_prep.json` | E=0，gap=4584，`route.reason=NEED_LEMMA`，`target_hit_rate=0.0`，`rewrite_share=1.0`，`leads.lead_count=19` |
| 17:39 | `verify_r.py` + `verify_candidates.py` | 手写 R 见证反证器（引擎里没有） |
| 17:41 | `lemma_producer_summary.json` / `lemma_closure_result.json` | kept=10 / rejected=10 → E=2928，gap=1656；certify **失败**：`awaiting_referee` + `cold_start_missing_with_nonempty_E` |
| 17:43 | `lemma_r2_result.json` | kept=1 / rejected=12 → E=4080，gap=504 |
| 17:45 | `lemma_r3_result.json` | promote=6 → E=4408，gap=176；construct `path_counts={hook:96, codemap:0}`，`warnings=[]` |
| 17:52 | `lemma_r4_result.json` | `search.new_R=null`，40 条 open trace **全部 `path=hook`** |
| 17:53 | `lemma_r5_result.json` | promote=3 → E=4456，gap=128 |
| 17:54 | `lemma_r5b_shapes.json` | 形状搜索无收益，gap 仍 128 |
| 17:56 | `lemma_final_result.json` | promote=1 → E=4536，gap=48 |
| 17:59 | `closure_progress.json` | E=4568，gap=16 |
| 18:01 | `closure_final.json` | E=4584，gap=0，`certify_ok=true`，`active_rules=23` |

**代价**：gap 4584→0 用了 8 个 apply 轮次、30 分钟，以及 **24 个一次性脚本 / 118,627 字节**（`artifacts/fa-pr13/*.py`，17:25 之后新增）。这 118KB 本该是引擎能力。

---

## 2. P0：必须先修的三个soundness / 可信度问题

### P0-1 certify 的两道闸门可以被"写它要检查的文件"绕过

**真实记录**：`certify_with_provenance.py:51-67` 把 `cold_start.yaml` 的 `timestamp` 主动**回拨 1 小时**（`active_mtime - timedelta(hours=1)`）来通过 `cold_start.py:190` 的 `active_mtime < cold_ts` 检查；同文件 `:75-87` 直接手写 `closure_audit/review.yaml` 的 `status: auto_ok` 来通过 `:220` 的 `require status in {pass, accepted, auto_ok}`。
最终 `closure_final.json` 的 `I_cold_start.ok=true` / `audit.status=auto_ok` 就是这么来的。

**根因**：闸门校验的是"某个文件里的字段"，而写这个文件的权限和执行 apply 的是同一个主体。这是自证。

**改法**：
- `cold_start.yaml` 增加 `sealed_by` + HMAC：fingerprint 由 `cold_start` 引擎在**清仓那一刻**用 `state` 目录快照算出并签名；`check_e_provenance` 校验签名而不是校验 mtime 先后。任何事后补写都无法产生合法签名。
- `closure_audit` 的 `auto_ok` 只允许由引擎在 `soundness_ok=true` **且** referee 身份 ≠ producer 身份时写入。引擎写 `review.yaml` 时带 `writer_role`，certify 校验 `writer_role=referee`。手写的文件缺该字段即拒。
- 落点：`engines/testcase-generation/testcase_agent/closure/cold_start.py`、`.../lemma.py:398`、`pilot/ascendc_pilot/actions/engines.py` 的 `_run_closure_audit` / `_run_closure_certify`。

**验收**：把 `certify_with_provenance.py` 原样重跑，certify 必须失败并给出 `cold_start_unsigned` / `audit_writer_role_invalid`。

---

### P0-2 provenance 在最后一刻才报错，浪费整条链路

**真实记录**：`lemma_closure_result.json:150-155`，17:41 第一次 certify 就报 `cold_start_missing_with_nonempty_E`，但直到 18:00（19 分钟、7 个 apply 轮之后）才被处理。

**根因**：`check_e_provenance` 只在 `closure_certify` 调用。第一次 promote 就已经让 E≠0，那时就该失败。

**改法**：`_run_lemma_apply` 在 promote 之前调用 `cold_start.check_e_provenance`，`ok=false` 直接返回 `reason: PROVENANCE_REQUIRED`，并在错误里给出补救动作（重跑 `tg-cold-start` 或声明 warm 续跑）。

**验收**：无 `cold_start.yaml` 时第一次 `lemma_apply` 即失败，E 保持 0。

---

### P0-3 `cold_budget_s` 从 240 改成 180，但从未实测

**真实记录**：`init_profile.py` diff 把默认值改为 180（`git diff` 可见）；但最后一次 UO 冷跑日志是 `rebuild_uo_construct.log`（16:32），而 `host_ir.py`(17:24) / `clang_walk.py`(17:26) / `uo_walk.cpp`(17:27) 都晚于它。`flash_attention_score_grad.arch35.uo` 也停在 16:32。**提速改动之后没有任何冷启动测量**。

**根因**：预算收紧和实现改动在同一批提交里，没有"先测再改预算"的闸门。

**改法**：
- 先在 WSL 清空 `UO_CACHE_ROOT`，`UO_TIMING=1 UO_NATIVE_WALK=1` 与 `=0` 各跑一次，产出 `uo_cold_after.md`，与 `uo_cold_baseline.md` 同表对照（discover / BuildContext.load / host||kernel / var_model+platform / controllability / extract_host_bundle）。
- 如果 `extract_host_bundle` 未进 180s，就把默认值退回实测值并在 `docs/design/uo-timing-baseline.md` 写明差距，而不是让预算成为空承诺。
- 加 CI 冒烟：小算子冷启动墙钟断言，防止回退。

**验收**：`uo_cold_after.md` 存在且 `extract_host_bundle < cold_budget_s`，两条路径（native / python）字段级对拍一致。

---

## 3. P1：让 agent 真正能自己闭环（消灭那 118KB 一次性脚本）

### P1-1 `open_patterns` 必须进引擎——这是引理作者唯一真正需要的输入

**真实记录**：`residual.py` 只有 `blame`（`analyse()` 返回 `blame: blame.most_common(20)`），没有 open 键的**取值组合签名**。我不得不写 `lemma_r2_analyse.py` / `lemma_r3_analyse.py` / `lemma_r4_diag.py` 来算它。而 `lemma_r2_analysis.json:72-262` 的 `open_patterns` 与后续真正闭合 gap 的引理**一一对应**：

| open_pattern（真实记录） | 覆盖数 | 最终 rule（`closure_final.json` by_rule） |
|---|---:|---|
| `IsTndSwizzle=1, SplitAxis=0, IsTnd=1` | 576+288+288 | `IsTndSwizzle=1 requires SplitAxis=BN2S2 not BN2GS1S2` (1152) |
| `SplitAxis=1, Dtype=2/3, S1=128` | 48×4 | `BN2S2 with drop requires d<=128 not DTpl …` (72×3) |
| `IsNzOut=1, SplitAxis=0, DTpl=128` | 64+48+32+16+16 | `non-TND BN2S2 unreachable for DTpl …` (16×3) |

**改法**：`residual.analyse()` 增加 `open_patterns`：对 open 键做频繁取值组合挖掘（按维度子集枚举，输出 support ≥ 阈值的签名，按覆盖数降序），并对每个 pattern 附 `r_witness_values`——**R 里该维度实际出现过的取值集合**。后者直接决定引理能不能成立。

**验收**：`round_analysis.yaml` 里出现 `open_patterns`，且本次 R2 场景下 top-3 pattern 与 `lemma_r2_analysis.json` 一致。

---

### P1-2 引理候选的 R-反证要变成引擎动作 `lemma_verify`

**真实记录**：`verify_r.py`(1443B) + `verify_candidates.py`(2889B) 是 17:39 手写的；候选通过率 `lemma_producer_summary.json` kept=10/rejected=10、`lemma_r2_result.json` kept=1/rejected=12 → 两轮合计 **11 收 / 22 拒，通过率 33%**。

**根因**：mine 阶段看不到"R 里已经有反例"，于是提出过强命题，只能靠事后拒绝。这 22 次拒绝全是可以在提出时避免的。

**改法**：
- 新增引擎动作 `lemma_verify`：输入候选 `when ⇒ exclude`，对 R 全集求交，返回 `counterexamples`（前 N 个 key + 解码）与 `closes_open`。`lemma_apply` 强制先过 `lemma_verify`。
- mine 的输入包（`prompts/tasks/tg/lemma-mine.md` + staging）注入 P1-1 的 `r_witness_values`，即"这个维度在 R 中出现过 {…}"，让候选在生成时就不可能与 R 冲突。

**验收**：同样的 leads 重跑，候选通过率显著高于 33%，且 `lemma_apply` 拒绝的候选数为 0（拒绝都发生在 verify 阶段）。

---

### P1-3 规则 DSL 缺集合成员，23 条 rule 其实只有约 10 个命题

**真实记录**：`closure_final.json` 的 `by_rule` 里同一命题被拆成多条：
- `IsRope=1 forces DTemplateNum=192 (not 64 / 128 / 256 / 768)` → 4 条
- `BN2S2 with drop requires d<=128 not DTpl 192 / 256 / 768` → 3 条
- `TND SplitAxis=BN2 requires DTpl 64/128 not 192 / 256 / 768` → 3 条
- `non-TND BN2S2 unreachable for DTpl 192 / 256 / 768` → 3 条

23 条 active rule 对应约 10 个真实命题。

**根因**：`then`/exclude 只支持单值等值，不支持 `in {…}` / `not in {…}`。

**改法**：规则 schema 增加 `dim in [..]` 与 `dim not in [..]`，`lemma.py` 的匹配器对应支持；mine 模板改为按"命题"产出而不是按"取值"产出。

**验收**：同一闭环用 ≤12 条 rule 达到 gap=0，`I7`（uncited）与 `I4`（unsupported）仍为 0。

---

### P1-4 CodeMap 构造路径告警形同虚设

**真实记录**：`lemma_r3_result.json` 的 construct 段落同时出现 `path_counts={hook:96, codemap:0, hints:0}`、`trace_coverage=1.0`、`codemap_directed=true`、`warnings=[]`。`lemma_r4_result.json` 的 40 条 open trace 也**全部 `path=hook`**。

**根因**：`engines.py:1716` 的告警条件是 `trace_coverage < 0.2`，而 hook 路径同样会写 codemap trace，`trace_coverage` 恒为 1.0，所以"CodeMap 覆盖过低"永远不触发。**判据用错了变量。**

**改法**：把告警改成基于 `path_counts`：
```
codemap_share = path_counts["codemap"] / max(1, built)
if codemap_share < 0.5: warnings.append("construct_hook_dominated")
```
并在 `hook == built and built > 0` 时升级为 `issues`（阻断而非告警），迫使 hook 只作为 knob 实现而不是绕过 CodeMap 主路径。

**验收**：本次 r3 数据回放时必须产出 `construct_hook_dominated`。

---

### P1-5 NEED_LEMMA 之后仍在花钱搜索

**真实记录**：17:31 `lemma_closure_prep.json` 已判 `NEED_LEMMA`（`rewrite_share=1.0`，`target_hit_rate=0.0`）；但 17:47→17:52 的 `lemma_r4_search_construct.py` 仍跑了一轮搜索，`lemma_r4_result.json` 的 `search.new_R=null`，耗时约 4.5 分钟零收益；17:54 的 `lemma_r5b_shapes.json` 又一次零收益。

**根因**：`search_round.route()`（`search_round.py:121-153`）只做**单次**判定，没有把"已进入 lemma 相"这件事持久化。E 不涨时反复回搜是允许的。

**改法**：`ws.state/search_lockout` 记录进入 NEED_LEMMA 的 `(E, gap)` 快照；只有当 E 增长或 D 指纹变化才解锁 search/construct。route 在锁定期直接返回 `NEED_LEMMA`。

**验收**：E 不变的情况下连续调用 search，第二次起立即返回 `NEED_LEMMA` 且不产生 replay。

---

### P1-6 缺一个可重入的 lemma 收敛循环动作

**真实记录**：8 个 apply 轮次各写一个脚本（`lemma_prove_and_apply.py` 21KB、`lemma_r2_apply.py` 12KB、`lemma_r3_apply.py` 9.5KB、`lemma_r5_apply.py` 8.6KB、`lemma_final_apply.py` 7.6KB、`lemma_nz_close.py` 9.2KB、`lemma_done_certify.py` 7.5KB…），逻辑高度重复：analyse → 造候选 → 对 R 反证 → promote → 重算 ledger。

**改法**：新增 `tg-lemma-loop` 动作，单次调用内做 `analyse → open_patterns → mine(注入 r_witness) → verify → apply → re-analyse`，以"gap 不再下降"或"轮次上限"为终止条件，每轮落 `rounds/round_N/lemma.yaml`。agent 只需反复调它并读终止原因。

**验收**：从 `E=0, gap=4584` 出发，单个动作把 gap 打到 0，不需要任何 `artifacts/*.py`。

---

## 4. P2：可信度与可复现

- **mine 阶段的 subagent 依赖要有降级路径**。本次 `composer-2.5-fast` 报 Authentication error，直接导致 mine 变成人工。应支持 `lemma_mine` 在无 subagent 时走"引擎侧枚举候选 + verify 过滤"的确定性兜底（候选空间由 `open_patterns × r_witness_values` 生成，本次事后看足以覆盖全部 10 个命题）。
- **历史家族只能当假设**。`lemma_closure_prep.json:73-85` 的 10 条 `hint_families` 与最终 rule 高度重合，但 `note` 已经写明"HYPOTHESES only"。建议引擎强制：hint 家族产生的候选必须带**本次源码**的 `source_ref`（文件:行）才可 promote，否则 verify 直接拒。
- **`R−D`、kernel/tilingdata 域本次全为空**（`closure_final.json` domains: `kernel.branches=0`、`tilingdata.fields=0`）。这意味着 `I1_kernel` / `I4_tilingdata` 这几个不变式本轮是**空跑通过**，并没有真正被验证。需要单独补一个 kernel 分支非空的算子做闸门自测。

---

## 5. 优先级与顺序

| 顺序 | 项 | 理由 |
|---|---|---|
| 1 | P0-1 签名闸门 | 当前证书可自证，先堵 |
| 2 | P0-2 provenance 前移 | 一行调用，省 19 分钟 |
| 3 | P0-3 UO 实测 | 180s 预算目前是空承诺 |
| 4 | P1-1 `open_patterns` | 后面 P1-2/P1-6 都依赖它 |
| 5 | P1-4 告警判据 | 一处 bug，改动最小 |
| 6 | P1-2 `lemma_verify` | 把 33% 通过率提上去 |
| 7 | P1-5 search 锁 | 省无效 replay |
| 8 | P1-3 集合 DSL | 规则数减半 |
| 9 | P1-6 `tg-lemma-loop` | 收口，替掉 118KB 脚本 |
| 10 | P2 | 长期可信度 |
