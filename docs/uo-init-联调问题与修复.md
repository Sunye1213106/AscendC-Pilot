# uo-init / AscendC-Pilot 联调问题与修复记录

> 范围：OpenCode + AscendC Pilot（含早期 Harness / Ascendc-PR-test-agent）在 FASG 等算子上的联调。  
> 更新日期：2026-07-26  
> 证据来源：
> - Cursor 对话（`~/.cursor/projects/d-PR-review/agent-transcripts/`，约 69 条父会话，其中 ~30 条与 Pilot/UO 强相关）
> - Cursor 对话（`d-TEST`）：`67647551-5a41-46a8-901a-c8e0cf140949`（FAG arch35 extract_plan / 证据策略 / Host 越权）
> - OpenCode session：`session-ses_0629` / `ses_06298d…`（子代理），以及更早的 `session-ses_06e5` / `06e3` / `06e2` / `06e0` / `06dc` / `06d8` / `06d6`，`ses_0711` / `070d` / `076d` / `0772` 等

本文按时间线 + 主题汇总**问题 → 根因 → 方案 → 状态**，供回归与复盘。

---

## 0. 对话索引（本目录 Cursor）

| 时段 | 代表 transcript | 主题摘要 |
|---|---|---|
| 07-22 | `ea03e237…` | KEY/CBM 误用、scope 文件计数、KEY triage 分包、tilingkey 接错 |
| 07-23 上午 | `3d464353…` `2aa9b2a6…` `c6751d7d…` | Harness 重构、KEY 门禁、Gate→rework 而非 blocked、迭代说明 |
| 07-23 中午 | `b1b139f6…` `a1d56e45…` | 组合式 Skill/Prompt/Agent；控制面收口；phase0→scope；旧叙事清理 |
| 07-23 晚 | `43f34de7…` `7a18ec14…` | 中文乱码、Todo 展示、Gate fail 后逃逸、refresh 脚本、ses_070d/0711 |
| 07-23 夜 | `0066487b…` | 迁移为 AscendC-Pilot / `acp` CLI |
| 07-24 | `c175ed62…`（及分支会话） | 安装链接、路由/产物对齐、extract 职责串台、Write 围栏、continue/reinit、stub 派发、debug、AskQuestion、语义补丁断档 |
| 07-26 | `67647551…`（d-TEST）+ `session-ses_0629` | 高置信源码比对上收公共策略；lease write⊆read；CBM 工具调用失败；YAML `} else {` 炸 plan；Host 代写 IR / stub 加戏 → RETRY_EXHAUSTED |

引用对话时可用：`[<标题>](<uuid>)`（uuid 为上表 transcript 目录名）。

---

## 1. 总览表（补全后）

| # | 问题 | 主责 | 状态 | 首现证据 |
|---|---|---|---|---|
| A1 | Windows 安装 `VERIFY FAIL: uo-init skill linked`（skills\skills 嵌套） | 安装脚本 | 已修 | 07-24 终端 / [安装失败](c175ed62-e957-4e02-83f7-329e8982daee) |
| A2 | OpenCode 残留旧 agent（Ascendc-agent / plan readme 等） | 安装/清理 | 已清 | 同上 |
| A3 | 口语「建库」路由失败 / 依赖正则 router | 路由设计 | 已改：Agent 自加载 Skill | ses_06e5 |
| A4 | Skill 未同步 / 产物路径与合同不一致 | 同步+合同 | 已修一批 | ses_06e5 / 06e3 |
| A5 | 切到 Build Tab 仍被 Harness 限制 | 兼容模式 | 已设计：无活动工作流则放行 | ses_06e5 |
| A6 | 算子名 / 目录 / op 解析错误 | 控制面 | 已修（全仓排查） | ses_06e3 |
| A7 | Gate fail 后 Agent 逃逸读引擎源码手工修 | 观察/授权 | 已修 Observation+Lease | ses_0711 |
| A8 | CLI 中文乱码（磁盘正常） | 编码 | 已说明/缓解 | ses_0711 |
| A9 | Todo 进主对话 / 右侧面板不全 / 中途消失 | Todo 策略 | 已改原生 todowrite | 07-23 晚 |
| A10 | 废弃 skill/understand-operator 残留导致 prepare 断层 | 清理 | 已修 | 07-23 |
| A11 | prepare 版本 soft vs finalize `consistent=true` 硬卡 | Gate | 已修 | 07-23 |
| A12 | phase0 叙事 / 旧脚本文档 | 文档 | 已清 | 07-23 |
| A13 | KEY 假闭合 / empty-only / 同文 bit-pack / closed_high | KEY 门禁 | 已硬门禁+裁判 | ses_076d 等 |
| A14 | Gate fail 直接 blocked（难用） | 状态机 | 已改为 rework_required | 07-23 计划修订 |
| A15 | CBM 不适合作 KEY/宏表主路径 | 能力边界 | Prompt 收紧 | ses_076d/0772 |
| A16 | KEY 每 key 一个 subagent 过重 | 派发策略 | triage+打包 | ses_0772 |
| A17 | scope 文件计数含 test / 口径不清 | scope 扫描 | 已规范 | ses_0772 |
| A18 | extract 职责串台：把 llm_tasks 塞进 extract_plan | Host/Skill | 已禁+stub | ses_06e0 |
| A19 | 空候选假 ACCEPT；Write 被拒后 bash 绕过 | 子代理/围栏 | 规则+围栏 | ses_06e0 |
| A20 | 超大 candidates 整包塞 Task | Host | stub 只传路径 | 07-24 |
| A21 | Primary 写 IR → PRIMARY_PROTECTED_WRITE | 权限 | 声明 actor 写 | 07-24 |
| A22 | prepare 占位符未填 → Host 补话啰嗦 | prepare | 已填+派发模板 | 07-24 |
| A23 | 中断 run 无 ask continue/reinit | 启动 UX | AskQuestion 可点选 | 07-24 |
| A24 | continue 后 Host 迷茫 / score 虚高污染 | Host/子代理 | stub+边界 | ses_06dc |
| A25 | Debug 误报；todowrite 缺 priority | Debug/Todo | 已修 | ses_06d8 |
| A26 | extract_plan 收据鸡生蛋 | Gate | 已修 | ses_06d8 |
| A27 | 算子/测试路径不明确仍 Glob | Host 规则 | AskQuestion §0.5/11 | 07-24 |
| A28 | apply_semantic_patch 无 patch 入口 | **流程** | adjudicate→apply | ses_06d6 |
| A29 | Host 跳步 / 不跑 acp next | Host+硬拦 | recommended + PIPELINE_SKIP | ses_06d6 |
| A30 | apply rework 不能跑裁决 producer | 控制面 | recovery_actions | 07-24 |
| A31 | extract_plan `non_sink_roots` 写成 unresolved dict；Host rework 加戏+新 session | Prompt/校验/Skill | 合同收紧：字符串列表硬拒 mapping；rework 必须 resume | ses_06cf |
| A32 | Debug export 捞无关 `session-ses_*.md`（如 ses_070d） | Debug | 必须传 session/parent id；禁止 cwd mtime 钓鱼 | ses_06cd |
| A33 | 高置信/`source_verified` 可空口闭合；规则只改个别 skill 易碎片化 | 公共策略+校验 | `evidence`/`code-access`/`source_evidence`；compose 注入全 agent | ses_0629 / 67647551 |
| A34 | Lease 可 Write 产物不可 Read 自检 | Lease | `issue_action_lease` 强制 write⊆read；pilot-control §13 | ses_06298d |
| A35 | CBM「不能用」：模型经 `invalid` 误调；失败后放弃取窗 | Capability | `cbm-navigation` 写清 OpenCode 全名+重试+`acp cbm lookup` | ses_06298d |
| A36 | `evidence_snippet` 含缩进掉级的 `} else {` → YAML 不可解析 → finalize 死循环 | 产品加载/证据载体 | `yaml_literal_sanitize`；优先 `evidence_window_sha256`；apply 按磁盘补 sha | ses_0629 |
| A37 | Host rework：代写 IR、stub 加戏、反复 prepare 换 sha → retry_exhausted | Host/控制面 | 禁 primary 改 IR；rework resume+原样 stub；prepare 只删不可解析 plan；containment 可读失败 IR | ses_0629 |

---

## 2. 安装与运行时环境

### 2.1 `VERIFY FAIL: uo-init skill linked`

**现象**：`install`/`refresh` 看似成功，校验报 uo-init 未链接。  

**根因**：`install.ps1` 先拷源码 `skills/`，再拷 `generated/.../skills`；PowerShell 在目标已存在时嵌套成 `skills\skills\`，junction 静默跳过。  

**方案**：拷生成树前删除冲突 `skills/agents/prompts`；缺失改为硬失败。提供 `refresh-opencode.ps1`：退出 OpenCode → 卸载重装 → SHA 校验。

### 2.2 残留 Agent / 错误 Tab 内容

**现象**：OpenCode 出现 Build README、旧 Ascendc-agent、plan readme 等。  

**方案**：清理旧插件与 agents；正式入口为 `ascendc-pilot` primary Tab。

### 2.3 harness → acp / 项目迁移

**现象**：CLI/文档仍混用 harness 命名。  

**方案**：迁移为 **AscendC-Pilot**，CLI **`acp`**，产物目录 `.ascendc-pilot/`。

---

## 3. 路由、Skill 同步与 Harness 兼容

### 3.1 口语建库「路由失败」

**现象**：提示非常像 uo-init，但脚本正则 router 匹配失败；refresh 后仍 skill 对不上。  

**方案**：

- **取消强依赖正则 router**；与其它 OpenCode skill 一样，由 Agent 按 description 自行加载
- `acp route` 仅作 slash 可选辅助
- 强调：改 skill 后须 compose + refresh + **重启 OpenCode**

### 3.2 产物路径 / 合同前后不一

**现象**：ses_06e5 等：产物位置不对、合同与引擎不一致、算子名/目录错。  

**方案**：全仓对齐 `OUTPUT_CONTRACT_PATHS`、gates、METHOD、生成 skill；修 op_name/project 解析；中低优问题一并收口（ses_06e3 清单）。

### 3.3 切到 Build 仍被 Harness 卡住

**现象**：用户切走 primary 后仍像被授权围栏限制。  

**方案**：有活动工作流 / 识别到对应 skill → 严格 Harness；否则与普通 OpenCode/Plan 兼容（不误伤）。

---

## 4. 控制面：失败、逃逸、状态机

### 4.1 Gate fail 后 Agent 逃逸（ses_0711）

**现象**：`uo-scope finalize` / `run-action --finalize` 失败后只返回 `{ok:false}`，**不更新** workflow；`next` 仍给正常 Action；Agent 继续 Glob/Read 引擎源码「手工修」。  

**方案**：Observation + 失败分类 + Lease；失败 → `rework_required` / `human_required`；authorize 收紧 read/bash；恢复命令白名单。

### 4.2 Gate fail ≠ 立刻 blocked

**现象**：早期设计 advance 失败就 blocked，极难用。  

**方案**：Gate fail → 保持 phase → `rework_required`；仅无进展预算耗尽 / 不可恢复才 `blocked`（POLICY §4）。

### 4.3 中文乱码

**现象**：session 里 `phase_label_zh` 乱码，磁盘 `workflow.yaml` 正常。  

**根因**：Windows 控制台/管道编码，不是 YAML 写坏。  

**方案**：以磁盘产物为准；CLI 输出侧尽量 UTF-8。

---

## 5. Todo 体验

### 5.1 主对话刷状态面板

**现象**：左侧大段 `Workflow TODO`、当前阶段、下一步 Action；右侧原生 Todo 不全或中途丢项。  

**方案**：

- 进度只进 OpenCode **原生 todowrite**
- 禁止主对话复述状态面板（POLICY）
- `todo_sync.items` 全量（含 id）；禁止子集覆盖导致其它阶段消失

### 5.2 todowrite 缺 `priority`（ses_06d8）

**现象**：SchemaError。  

**方案**：items 按状态注入 priority；POLICY 要求全量含 priority；插件可自动补。

### 5.3 Host 纠结「要不要再同步」

**现象**：prepare_layout 时 Host 长篇思考是否 todowrite（冗余）。  

**方案**：规则改为「有变化才同步；无变化跳过；禁止讨论要不要同步」。

---

## 6. 文档 / 废弃物 / 命名

| 问题 | 方案 |
|---|---|
| 文档仍写 Skill 管阶段/门禁 | 一律改为 Pilot 唯一控制面 |
| `understand-operator` 删除后 prepare 仍查 | 改检查目标，保证 layout 写全 |
| prepare soft warning vs finalize `consistent=true` | 对齐判定 |
| phase0 / cbm_query.py 陈年脚本 | 改为 scope；只走 MCP |
| 「已废弃」「断边」「旧逻辑」字样 | 删除（会误导无记忆的 Agent） |
| harness-迭代说明 | 合并计划差异到 docs |

---

## 7. KEY / CBM / confidence（领域质量）

### 7.1 tilingkey「接错」与假不可解（ses_076d）

**现象**：empty 旁路归因；confidence 统一借口 bit-pack；gate 虚报；父代理跳过 key-resolve。  

**方案**：KEY 硬门禁（triage / empty-only 拒收 / closed_high / 同文 bit-pack）；integrity 内嵌 key gates；运动员 `uo-key-resolve` vs 裁判 `uo-confidence-review`。

### 7.2 CBM 能力边界

**适合**：具名函数/类定位。  
**不适合当主路径**：`ASCENDC_TPL_*` 宏表、工厂注册、shape 决定的 KEY 谓词、empty 旁路。  
Prompt 改为 MUST/MUST NOT 合同结构。

### 7.3 KEY 派发过重（ses_0772）

**方案**：先 `key_triage`；complex 一 KEY 一 Task；simple（empty_tensor/regbase）打包；并行 cap。

### 7.4 scope 文件计数口径

**方案**：明确含/不含（test 不应计入 op_host 等）；cpp+头文件都算；表格化展示。

---

## 8. extract_plan 职责与写权限（ses_06e0 一带）

### 8.1 「丢了 7 个 mask」实为 7×mark_missing

**现象**：Host 把 1×bind + 7×mark_missing 糊成「8 call_edge」塞进 extract_plan；子代理半对半过激；空候选全 ACCEPT；写错 YAML；Write 被拒后想 bash 绕过；`extract_plan.yaml` 未落地。  

**方案**：

| 规则 | 内容 |
|---|---|
| 职责 | extract_plan **只**确认 candidates→writers/receivers/aliases |
| 禁止 | 裁决 llm_tasks / 假闭合空候选 |
| 派发 | **仅** `task_prompt_stub`；禁止整包 llm_tasks/candidates |
| 写入 | 声明 actor + action_id；Primary 禁写 `uo/ir/**` |
| 后续 | 边裁决走 `adjudicate_llm_tasks`→`apply_semantic_patch`（见 §10） |

### 8.2 prepare 占位符与派发啰嗦

**现象**：`<UO_ROOT>` 等未替换 → Host 自己编长 prompt。  

**方案**：prepare 填齐占位符；Skill 钉死「只粘 stub」；agent 卡要求先读 session `prompt.md`。

### 8.3 中断 run：continue / reinit

**现象**：目录已有半成品 run，静默复用或乱删。  

**方案**：`needs_human_decision` + AskQuestion 可点选；摘要上次完整点/中断点；continue 先 scrub 残缺再从最近正确状态 resume；reinit 清 uo 重来。

### 8.4 ses_06dc：污染 / 虚高 score / continue 迷茫

**现象**：子代理像被前文污染、少读源码却 score 0.9；finalize 回退失败；Host 不知下一步。  

**方案**：强化 stub 边界 + finalize 前置产物检查；continue 路径与推荐下一步（后续又用 recommended_next 加固）。

---

## 9. Debug 与收据鸡生蛋（ses_06d8）

### 9.1 Debug 模式

**需求**：自动捕捉工具失败、过长非逻辑思考；子代理结束导出 session。  

**方案**：`acp debug enable|status|export-session`；hooks 写 `anomalies.jsonl`；Task 结束导出 `debug/exports/`。  

**后续修**：成功 Read/`ok:true` 不再误报；todowrite priority 见 §5.2。

### 9.1.1 Debug transcript 绑错会话（ses_06cd / A32）

**现象**：`subagent_stop` 导出包里出现无关的 `transcript_session-ses_070d.md`；同一次 run 堆很多 export。

**根因**：`export_session_bundle` 在无 `session_id` 时用 cwd 下最新 `session-ses_*.md` 兜底；插件未传 Host/Task session id。

**方案**：
- 导出只接受 `--session-id` / `--parent-session-id` / `--transcript`；**禁止** cwd mtime 钓鱼
- OpenCode 插件 Task after：解析 `<task id="ses_…">` + hook `sessionID` 传入
- 找不到匹配文件 → 不拷 transcript（仍导出 run state），DEBUG_REPORT 标明原因

### 9.2 extract_plan finalize 收据鸡生蛋

Gate 不再要求先有收据；校验 plan/candidates/hash/边界；收据由 finalize 成功后签发。

---

## 10. 语义补丁断档与跳步（ses_06d6，主因）

### 10.1 流程缺环

`detect_score_pre` 产出 blocking llm_tasks → extract_plan 禁止处理 → `apply_semantic_patch` 却是确定性且要 `ctx.patch` → 空 patch → `unknown_task_id` + 无 ledger。

### 10.2 方案

```text
detect_score_pre → extract_plan → detect_score_post
→ adjudicate_llm_tasks   # 新 producer → semantic_patches.yaml
→ apply_semantic_patch   # 读 patches 或 auto mark_missing
→ rebuild_from_ledger → recheck_closure
```

- `acp next` 返回 **`recommended_next_action`**；跳步 → `PIPELINE_SKIP_DENIED`
- apply 缺 LLM patch → `SEMANTIC_PATCHES_REQUIRED`；rework 允许 `adjudicate_llm_tasks`
- 收紧 detect_score_pre/post gates

**责任（ses_06d6）**：子代理 extract_plan 过关；主因流程；Host 跳步+漏问测试路径次要。

---

## 11. AskQuestion 关键参数（07-24）

| 参数 | 行为 |
|---|---|
| 算子目录 `--project` | 歧义 → 立刻 question，禁止 Glob 考古 |
| architecture | 未说且不能默认 → 问 |
| 测试脚本 `--test-script-root` | **uo-init 不要求**；仅 `tg-init` 等测例契约缺则问 |
| continue/reinit | 可点选框，禁止口头含糊 |

---

## 12. 回归清单（精简）

1. 退出 OpenCode → `refresh-opencode.ps1`（或等价）→ 重启 → Tab `ascendc-pilot`  
2. 参数齐：project + arch35（**勿**因缺 test-script-root 停；那是 tg-init 的事）  
3. `acp start` → 若已有 run → AskQuestion continue/reinit  
4. 循环：`acp next` → **只跑 recommended** →（语义则 stub 派发 → finalize）→ 再 `next`  
5. 跳步应被拒绝；有候选 llm_tasks 必须 adjudicate→apply  
6. extract_plan：证据优先 `evidence_window_sha256`；故意塞缩进掉级的 `} else {` 进 snippet 仍应能被 sanitize 加载（见 `test_yaml_literal_sanitize`）  
7. 可选：`acp debug enable`（重装后一般仍 enabled）

相关单测：`test_semantic_patch_pipeline.py`、`test_prepare_placeholders.py`、`test_uo_output_contracts.py`、`test_yaml_literal_sanitize.py`、`test_extract_plan.py`、`test_lease_read_session_pack.py` 等。

---

## 13. 变更落点速查

| 主题 | 落点 |
|---|---|
| 安装/嵌套 skills | `install.ps1`、`refresh-opencode.ps1` |
| 路由/Skill | `skills/workflows/*`、compose、去掉强正则 route |
| Observation/Lease | `pilot/ascendc_pilot/observation/`、`authorize/` |
| Todo | `todo.py`、POLICY 原生 Todo |
| KEY 门禁 | engines + gates + confidence_review |
| extract 边界 | extract-plan METHOD/prompt、runtime stub、围栏 |
| continue/reinit | `run_resume.py`、uo-init SKILL |
| Debug | `pilot/ascendc_pilot/debug/` + hooks |
| 语义补丁 | `adjudicate-llm-tasks`、`llm_tasks.py`、`pipeline.py`、`engines.py` |
| 跳步 | `describe_next` recommended、`PIPELINE_SKIP_DENIED` |
| non_sink schema / rework resume | `extract_plan_io.py`、`prompts/tasks/uo/extract-plan.md`、uo-init SKILL、pilot-control |
| 高置信源码比对（公共） | `skills/policies/evidence`、`code-access`、`source-authority`；`uo/scripts/source_evidence.py`；compose 注入 |
| Lease write⊆read | `authorize/lease.py`、`pilot-control` POLICY、`actions/runtime.py` prepare |
| YAML literal sanitize / window sha | `uo/scripts/yaml_literal_sanitize.py`、`_ir_io.read_yaml`、`apply_extract_plan`、gates `_load` |
| CBM 全名+回退 | `skills/capabilities/cbm-navigation/METHOD.md` |
| containment 读失败 IR | `authorize/__init__.py` MODE_CONTAINMENT 读例外 |

---

## 13.1 A31：non_sink_roots unresolved dict（ses_06cf）

**现象**：子代理把 30 个 non_sink 写成 `{name, adjudication: unresolved, …}`；校验 `str(dict)` 报假 “not in candidates”；Host 误诊为身份规则 → omit，并新开第二个 session + stub 前夹 REWORK 长文。

**根因**：prompt “leave unresolved” 被套用到 `non_sink_roots`；该字段合同是**字符串列表**，无 writers 身份规则；校验未硬拒 mapping。

**方案（开发期·无兼容补丁）**：
- 校验：mapping → `must be a string name, got mapping`；字符串不在候选 → `not in candidates: <name>`
- prompt/METHOD/参考：显式 schema + 示例；证据不足对 writers/receivers 用 omit；non_sink 确认短名或 omit
- Skill：rework 必须 resume；禁止 stub 加戏；finalize 分层构建可能数分钟

---

## 13.2 A33–A37：高置信源码比对 / Lease / YAML 证据 / Host 越权（2026-07-26 · FAG arch35）

**场景**：`flash_attention_score_grad`（仅 arch35）`uo-init` → `extract_plan`。  
**证据**：OpenCode `session-ses_0629`（primary）+ 子代理 `ses_06298d…`；Cursor `67647551-5a41-46a8-901a-c8e0cf140949`。

### 现象摘要

1. 子代理能窗口 Read `op_host`，写出 writers/receivers 大体对齐源码，但 **`evidence_snippet` 内 `} else {` 缩进掉级** → `extract_plan.yaml` PyYAML 解析失败 → finalize `ACTION_FINALIZE_FAILED_EXTRACT_PLAN`。  
2. Host（primary）**直接 Edit `uo/ir/extract_plan.yaml`**、往 stub 后拼 `CRITICAL YAML RULE`、lease 过期后 **再 prepare**（candidates sha 变更）→ 子代理重写仍炸 → **`RETRY_EXHAUSTED` / `human_required`**。  
3. 子代理误以为 CBM 不可用：实际 MCP 工具在 available 列表中，但经 **`invalid` / 错误调用** 失败后放弃，未重试 / 未 `acp cbm lookup`。  
4. Lease **允许 Write `extract_plan.yaml` 却不允许 Read**，自检被拒。  
5. 规则若只改 `extract-plan` prompt/METHOD，系统再次碎片化。

### 根因分层

| 层 | 根因 |
|---|---|
| 证据合同 | 高置信依赖易碎 YAML 内嵌 C++；缺少「磁盘窗口 sha」主路径 |
| Lease | write 未自动并入 read（签发层无全局不变量） |
| Capability | CBM 未写清 OpenCode 工具全名与失败回退 |
| Host 行为 | Gate fail 后代写 IR / stub 加戏 / 无故 re-prepare，违反 producer 合同 |
| 加载层 | 无 literal-block sanitize，一次缩进错误整文件不可用 |

### 产品方案（公共层 · 禁止只改个别 skill）

| 主题 | 落点 | 要点 |
|---|---|---|
| 高置信=源码比对 | `skills/policies/evidence/POLICY.md`、`code-access`、`source-authority` | `confidence:high` / `source_verified:true` ⇒ 磁盘可核验；search 不算比对 |
| 共享校验 | `uo/scripts/source_evidence.py`；`extract_plan_io` 复用 | snippet **且** **`evidence_window_sha256`**（AND，禁止 OR）；去缩进比对 |
| YAML 韧性 | `uo/scripts/yaml_literal_sanitize.py`；`_ir_io.read_yaml` / gate `_load` | `|` 块内容行缩进 pad 到首行；加载后仍可 parse |
| 证据优先序 | `evidence` POLICY + `apply_extract_plan._enrich_evidence_window_sha` | 优先 files/lines + window sha（可从候选 `source_window.sha256` 或磁盘计算）；少塞大段 C++ |
| Lease write⊆read | `authorize/lease.py` `issue_action_lease`；`pilot-control` §13；runtime prepare 双保险 | **所有 Action** 签发时 write 路径可读 |
| CBM 路径 | `skills/capabilities/cbm-navigation/METHOD.md` | `codebase-memory-mcp_search_graph` → `_get_code_snippet`；失败重试 / `acp cbm lookup` / 窗口 Read |
| Compose 注入 | `scripts/compose_runtime.py` | 全 agent / skill 注入 evidence、code-access、source-authority（不只 extract-plan） |
| prepare | `actions/runtime.py` | 仅删除**不可解析**的旧 plan；可解析则保留，减轻 sha  churn |
| containment 读失败产物 | `authorize/__init__.py` | `human_required` 下允许 Read `extract_plan.yaml` 等失败 IR + 该 Action session pack |
| extract-plan prompt | `prompts/tasks/uo/extract-plan.md` | **引用**公共策略/能力，不另立证据例外；推荐 window sha |

### Host / 子代理行为约束（仍有效）

- Gate fail → **resume 原 Task + 原样 stub**；禁止 primary `Edit/Write uo/ir/**`；禁止 stub 加戏。  
- 子代理不得把 `GetTilingKey` 等 `key_writer` 推给下游 adjudicate（本步合同内应确认或 omit 并写清）。  
- 改完：`compose_runtime.py --host opencode` → `refresh-opencode.ps1` → 重启 OpenCode。

### 回归单测

- `engines/understand-operator/tests/test_yaml_literal_sanitize.py`  
- `engines/understand-operator/tests/test_extract_plan.py`  
- `pilot/tests/test_lease_read_session_pack.py`（含 `test_lease_write_paths_are_always_readable`）

---

## 13.3 A38–A42：证据 AND / 空 sinks / summary / Gate 同源 / 空 Task（2026-07-26）

**场景**：`flash_attention_score_grad`（arch35）`uo-init` → `extract_plan`（继 13.2）。  
**证据**：OpenCode primary `session-ses_0625`；子代理 `ses_0624edc4…`；run `RUN_20260726_090703_0b49bd65`。  
**状态**：A38–A42 已落地；A43+（ses_0625）产品韧性 / rework 复用 candidates / failure 分桶 **已落地（2026-07-26）**。待 `compose` + `refresh-opencode.ps1` 后 FAG 再测（建议清坏 plan 或从 `human_required` 合法恢复后再 prepare）。

### 现象摘要（问题）

1. 子代理已能 CBM，writers/receivers/GetTilingKey 结构大体对，但 snippet 含 `...` / 非连续；receiver 错贴 sha；alias 缺 `tdf_leaf`；non_sink 发明名。  
2. Host 首次派发 stub **合规**（含 summary）；finalize 正确失败。  
3. Rework 时 Host **无故再 prepare** → `candidates_sha256` 从 `5ba163…` 变为 `a28a24…`；子代理 resume 后**只改 sha 头**声称「源码未变」→ Host **明知未修证据仍二次 finalize** → 同 fingerprint ×2 → 预算耗尽。

### 根因分层

| 层 | 根因 |
|---|---|
| 证据合同 | 已收紧为 sha **AND** 连续 snippet（拒拼贴）——校验对；缺「可核验则回填连续窗」韧性 |
| Action 合同 | alias/non_sink 合同正确拒；summary 未列合法 alias 对 |
| Rework / prepare | **校验失败不应重跑 propose**；重 prepare 制造 sha churn，掩盖真修复 |
| Host | resume+原 stub 合规，但 **盲信「只改 sha」摘要仍 finalize**；failure_card 142 条重复噪声，stub 无结构化修复信号 |
| 观测 | 同 reason 双计（high+promote）；整包 reject 塞进一条 finding |

### 产品方案（公共优先 · 禁止只改 extract-plan skill）

| 项 | 层级 | 落点 | 要点 |
|---|---|---|---|
| 高置信 = sha **且** 连续 snippet | **公共**（已做） | `require_disk_window_proof` | 保持拒拼贴 |
| **可核验则回填连续 snippet** | **公共**（下一刀） | `apply_extract_plan` / `source_evidence`（对齐 `_enrich_evidence_window_sha`） | files/lines 齐 → 从磁盘或候选 `source_window.text` 写入连续 snippet；禁省略号 |
| **校验失败禁止无故 re-propose** | **公共控制面** | extract prepare / runtime rework | 已有可解析 plan + 仅 checker 失败 → **保留 candidates + 原 sha**，只换 lease/stub |
| 压缩 failure + 可选 rework hints | **公共模式** | Observation / failure_card；lease 可读 `*.rework_hints.yaml` | 分桶：collage/sha/alias/non_sink；禁止 142 条重复 |
| Host：子代理称「未改证据」禁止 finalize | **公共** `pilot-control` | 一句硬规则 | 先 `check`/再 resume；禁止「先 finalize 试试」 |
| summary 列 alias 对；空 sinks/GetTilingKey | **挂 extract**（部分已做） | summary + `_validate_extract_plan_contracts` | 字段合同不进公共 evidence |

### 回归单测 / 交付

- [x] A38–A42 单测 + compose  
- [ ] 回填 snippet + rework 不 churn sha 单测  
- [ ] FAG：同 fingerprint 不再因「只改 sha」烧尽预算

---

## 13.4 A43+：Host rework 空转 / 证据回填 / 禁 sha churn（ses_0625 · 2026-07-26）

**证据**：[`session-ses_0625.md`](../session-ses_0625.md) — finalize 失败 → 再 prepare → resume 只改 sha → 再 finalize → `RETRY_EXHAUSTED`。

### 已落地（公共优先）

| 项 | 落点 | 状态 |
|---|---|---|
| 拼贴 snippet → 磁盘/候选窗回填 | `source_evidence.enrich_item_evidence_from_disk`；`apply_extract_plan` | 已做 |
| rework 复用 candidates+sha（禁无故 re-propose） | `engines._run_extract_plan`（plan 存在或 status=rework/human） | 已做 |
| failure 分桶去重 + `extract_plan.rework_hints.yaml` | `bucket_extract_plan_errors`；lease 可读 hints | 已做 |
| Host 禁盲 finalize（只改 sha） | `pilot-control` §9 | 已做 |
| summary 列 alias `local/tdf_leaf` | `build_extract_plan_candidates_summary` | 已做 |
| 校验错误去重（high+promote） | `extract_plan_io._validate_decision_evidence` | 已做 |

### 回归单测

- `test_apply_backfills_collage_snippet` / `test_bucket_extract_plan_errors_dedupes`  
- `pilot/tests/test_extract_plan_reuse_candidates.py`

### 联调恢复建议

1. `compose_runtime.py --host opencode` → `refresh-opencode.ps1` → 重启 OpenCode。  
2. 当前 `human_required`：按 Pilot 合法恢复路径重试 extract_plan（prepare 应 `reused_candidates:true`）。  
3. Host：子代理若只改 sha → 禁止 finalize；读 `extract_plan.rework_hints.yaml`。

### A44：summary 硬约束 + 只读 grep（2026-07-26）

| 项 | 落点 | 状态 |
|---|---|---|
| summary 含 `section_lines` / `must` | `scan_candidates_section_lines` + summary builder | 已做 |
| stub `MUST_READ_ORDER` 禁先扫全量 candidates | `runtime._build_task_prompt_stub`；prompt/METHOD | 已做 |
| bash 只读 `grep\|rg\|Select-String\|findstr` | `authorize._ALLOW_BASH_READONLY_HEAD`；`code-access`/`pilot-control` | 已做 |
| Grep 仍非 high 证据 | 公共 policy | 已写清 |

### A45：大 IR summary 上收公共层（2026-07-26）

| 项 | 落点 | 状态 |
|---|---|---|
| YAML `section_lines` / `attach_large_ir_meta` | `uo.scripts.ir_summary`；extract_plan 薄封装 | 已做 |
| stub 见 `*.summary.yaml` 即注入 `MUST_READ_ORDER` | `ascendc_pilot.ir_summary` + runtime（不按 action 特判） | 已做 |
| policy / 原则文档 | `code-access`；`skill-and-prompt-principles` | 已做 |
| 仍留本步 | sinks / key_writer / alias 字段合同 + evidence_tools stub | 正当例外 |

### A46：OpenCode permission 拦 bash grep（2026-07-26）

| 项 | 说明 | 状态 |
|---|---|---|
| 现象 | `Bash Grep …` → `Permission denied by OpenCode permissions` | 已确认 |
| 根因 | primary frontmatter `bash: *:deny` 只放行 `acp *`；**先于** Pilot authorize | — |
| 修复 | `compose_runtime._opencode_bash_permission`：只读定位 + `acp`；`grep` 工具 allow；subagent 同 fence | 已做 |

### A47：adjudicate `candidate_set_hash` 字段错位（ses_0622 · 2026-07-26）

| 项 | 说明 | 状态 |
|---|---|---|
| 现象 | finalize 20× `patch_candidate_set_hash_missing` → FIX ONLY 改 session → `RETRY_EXHAUSTED` | 已确认 |
| 根因 | Gate 读 `candidate_set_hash`，错误码却叫 `patch_candidate_set_hash_missing`；Host 指挥写错字段；re-prepare 导致 session 漂移 | — |
| 修复 | 权威字段 `candidate_set_hash` + 别名兼容；错误码 `candidate_set_hash_missing_on_patch`；prompt/METHOD 补字段；禁 FIX ONLY 只改 session | 已做 |
| 文档 | 证据 snippet **AND** sha（非 OR） | 已改 |

### A48：uo-init 修复计划落地（W0–W2 · 2026-07-26）

| 波次 | 内容 | 状态 |
|---|---|---|
| W0 | hash 合同 + 文档 AND + Host session 纪律 | 已做 |
| W1 | `environment_capabilities.yaml`；`allowed_source_*`；adjudicate no-op；compose-drift CI；identity/format 不烧 semantic budget | 已做 |
| W2 | containment 合同读；FORBIDDEN 单源；sanitize 下沉 Pilot；Task identity 仅 env；删假 `tool_budget` | 已做 |
| W3 自动化 | `test_uo_init_plan_hardening.py` + hash 别名单测 + compose drift | 见门禁 |
| W3 手工 | FAG `flash_attention_score_grad`：`acp start --force-new` → `acp complete` | **未跑** |

### A49：只读定位误拒 + sha256 导航缺失（2026-07-26）

| 现象 | 根因 | 落点 | 状态 |
|---|---|---|---|
| `findstr /n "A\|B\|C" …` → non-acp / ask | authorize 裸拆 `|`，把引号内 `\|` 当成管道 | `authorize._split_shell_segments` + readonly 单测 | 已做 |
| 子代理「找不到」`evidence_window_sha256`，Grep/findstr 扫全量 candidates | summary 无 `source_window_sha256` / `candidates_line` / `end_line` 导航 | `extract_plan_io.build_extract_plan_candidates_summary` + `must` | 已做 |
| 邻项 sha 复用（如 GetWorkspaceSize hash 套 DoPreTiling） | 导航缺失 + 误判须自算；合同未写明邻项 hash=编造 | `policies/evidence`；stub `evidence_sha_rule`；enrich 覆盖错 sha（既有）+ 单测锁定 | 已做 |

**交付**：`compose_runtime.py --host opencode` 已跑；安装侧需 `refresh-opencode.ps1` 后 **重启 OpenCode**。扫算子根 Grep 仍由 confirmed source scope 拒绝（正确围栏，不放宽）。

### A50：non_sink 宽召回 + 编造名返工（2026-07-26）

| 现象 | 根因 | 落点 | 状态 |
|---|---|---|---|
| candidates 有 ~648 个 `non_sink_root_candidates` | 确定性 propose：writer 函数体内 `ident =` 赋值 LHS − sink receiver（`assign_lhs_only`）；**不是** 648 个函数 | `propose_extract_plan`（召回语义保留） | 已说明 |
| finalize `NON_SINK_INVENTED_47` → rework | 子代理从 snippet 发明 `fBaseParams`/`batchSize` 等；summary 仅有 count 无名字清单 | summary `non_sink_root_names`；stub `non_sink_rule`（默认 `[]`）；`drop_invented_non_sink_roots` apply 韧性 | 已做 |
| 返工时 findstr / Grep 空转很久 | Windows `findstr` 正斜杠路径误解析；大 IR 扫名单 | `code-access` 注明 `\` 路径；summary 名单避免扫全量 | 已做 |
| Host resume 塞大段 `REWORK: …` | 违反「Task 只粘原 stub」 | 纪律：resume **原样 stub**；细节只进 `rework_hints.yaml` | 文档强调 |

**覆盖口径**：plan 默认 omit / 自动丢编造名 **不削弱** writers/sinks/aliases 主链；不硬砍 648 候选池。propose 仅滤单字符/`Begin` 级 LHS 噪声。

**产品宣称口径（未变）**：在 W3 手工 FAG 回归通过前，状态维持 **功能候选完成**，不宣称「生产可稳定跑完」。

**手工回归记录模板（跑完后填）**

| 字段 | 值 |
|---|---|
| 算子 | `flash_attention_score_grad` |
| run_id | |
| 结果 | `acp complete` / 失败点 |
| 产物摘要 | |
| 备注 | 需 `compose` → `refresh-opencode.ps1` → **重启 OpenCode** 后再测 |

**Compose 纪律**：改 `policies` / `actions` / `prompts` / `agents` 后必须 `python scripts/compose_runtime.py --host opencode` 并提交 `generated/opencode`；CI `compose-drift.yml` 会 `git diff --exit-code`。

### A51：宏注册链未物化 + 伪 mark_missing + 零增量仍全量 rebuild（2026-07-26）

| 现象 | 根因 | 落点 | 状态 |
|---|---|---|---|
| 20× `REGISTER_*` / `REG_OP` → LLM 全员 `mark_missing`（理由 score=0） | 宏节点 `confidence=None` 被当成 score 0；无公共宏合同物化；`mark_missing` 无否定证据 Gate | `ascendc_macro_contracts.yaml` + `macro_semantic_materializer`（挂 `build_layered_kb`）+ `score_entrypoint_node` 修 + `validate_mark_missing_patch` | 已做 |
| pre 任务进入 adjudicate | `detect_score_pre` 任务被当最终任务源 | pre=`provisional` / `eligible_for_adjudication=false`；post 重算入口图并关闭已 auto_accept 目标 | 已做 |
| KEY gap 挡 extract → 死锁 | `semantic_closure` 把所有 blocking 当 extract 阻塞 | triage `blocks_extract_advance`；KEY → `blocking_phase=resolve` | 已做 |
| 0 物化仍全量 `build_layered_kb` | rebuild 无 effective-delta / fingerprint 短路 | `should_skip_layered_rebuild` + `rebuild_input_fingerprint`；先 delta 后 `NO_SEMANTIC_PROGRESS` | 已做 |

**流水线**：`detect_score_pre`(provisional) → `extract_plan`/`build_layered_kb`(+macro) → `detect_score_post`(canonical+triage) → adjudicate 仅 `post_semantic`+`route=uo-semantic-resolve` → apply → rebuild(可 skip) → recheck。

**夹具**：`engines/understand-operator/tests/fixtures/fag_macro_semantic_failure/`（RUN_20260726_121719_0d48474d 脱敏最小集）。

**Host 纪律**：Gate fail / `NO_SEMANTIC_PROGRESS` → **resume 原 stub**，禁止 REWORK 长文。

**交付**：改 policies/engines 后跑 `compose_runtime.py --host opencode`；安装侧 `refresh-opencode.ps1` 后重启 OpenCode。

### A53：确定性流水线性能 — structural/publish 分离 + 并行提取 + IO 缓存（2026-07-27）

| 现象 | 根因 | 落点 | 状态 |
|---|---|---|---|
| `extract_plan` finalize / rebuild 重复 export sqlite + human views | `build_layered_kb` 混合结构构建与 publish；`export_integrity` 再跑一遍 | `mode=structural|full` + 共享 `publish_kb_products`（仅 `export_integrity` 调用） | 已做 |
| `bridge.yaml` 双写 | `reconcile_bridge` 内部 persist + caller 再写 | `persist=False` + 父流程单次 `write_yaml_if_changed` | 已做 |
| host/kernel 串行 | `build_layered_kb` 顺序调用 | `parallel_layer_extract.extract_host_kernel_parallel`（ProcessPool max_workers=2，失败回退串行） | 已做 |
| TG consumer 重复读盘/AST | `consumer_evidence` 每步全量扫描 | 共享 `consumer_index.json`（`load_or_build_consumer_index`） | 已做 |
| closure 误跑 integrity | `_run_recheck_closure` 慢路径调 `check_kb_integrity` | integrity 仅 `export_integrity`；`recheck_closure` 读 `closure_summary` | 已做 |

**性能文档**：`docs/performance/baseline.md`、`docs/performance/after.md`；探针 `scripts/profile_uo_pipeline.py`。

**交付**：共享模块单测见 `test_structural_publish_split.py` 等；禁止在 skill/prompt 复制性能规则。


| 目标 | 落点 | 状态 |
|---|---|---|
| Host→KEY `input_derivable` 闭环 | `semantic_severity.input_derivable_closure`；`gate_input_derivable_closed`；confidence_report 先 `classify_and_write` | 已做 |
| UO blocking / TG-resolvable / degraded | `resolution_class`（triage+severity）；extract `semantic_closure` 不挡 `tg_resolvable` | 已做 |
| family→path→obligation Gate | `family_path_obligation.py` + `tg_adapters.gate_family_path_obligation`；tg-init nest/gate | 已做 |
| 分层 hash 增量重建 | `compute_layer_input_fingerprints` / `select_layers_for_rebuild`；`rebuild_derived_graphs` 选择性 `layers=` | 已做 |
| SQLite canonical **query** | 保持 YAML SoT；`SQLITE_STALE` + `uo_ready` 要求 `index_status=fresh` | 已做 |
| 强化 `uo_ready` | integrity pass ∧ sqlite fresh ∧ input_derivable closed ∧ family/path（无导出则 skip pass） | 已做 |

**不做**：把 sqlite 改成写权威 SoT（与 `ownership.yaml` / `kb_layout` 冲突）。

**单测**：`tests/test_phase_bc_semantic_closure.py`；夹具仍用 A51 FAG macro failure 集。完整 FAG `acp complete` 仍属手工 W3。

---

### A54：uo-init 语义闭合 — 假 N/A 死循环 / boundary / typed bridge / KEY / quality 分层（2026-07-27）

| 现象 | 根因 | 落点 | 状态 |
|---|---|---|---|
| recheck→adjudicate N/A→空 apply 死循环 | `blocking_gap_tasks` 与 `open_blocking_tasks` 不一致时仍写 `semantic_patch_not_applicable` | `runtime.prepare` → `ADJUDICATION_ROUTED_NON_LLM` + `recoveries_for_task_routes` | 已做 |
| 空候选假 mark_missing | `can_auto_mark_missing` 只看 type/空候选 | 禁 triage 类别；要求 `effective_task_type==mark_missing` + 完整 `negative_evidence`；auto patch validate-only | 已做 |
| operator_boundary 空/路径静默失败 | 相对路径带 op 前缀时读不到；空 IO 当成功 | `source_path_resolve` + `OPERATOR_BOUNDARY_EMPTY` fail-closed | 已做 |
| rework 无 resume | 仅 debug registry，无 prepare 回写 | `action_dispatch`：`dispatch.yaml`/`handoff.yaml`；`resume_session_id`；无 lineage→`fork_with_context` | 已做 |
| incomplete_scope 死循环 adjudicate | recovery 一律 `adjudicate_llm_tasks` | route-aware：`SCOPE_EXPANSION_REWORK`→`apply_scope_expansion`→`detect_score_post`；同指纹→`human_required` | 已做 |
| typed bridge≈0 / UnknownType verified | leaf fallback 当 verified；缺 metrics | UnknownType 不当 typed；`bridge_metrics`；integrity/quality 分层 | 已做 |
| KEY 全 unsolved 当成功 | 缺 compile/platform→false | `classify_input_derivable` 写 `false`+`non_input_reason`；consumer_ready 禁全 unresolved | 已做 |

**共享层**：`source_path_resolve`、`semantic_task_triage.effective_task_type`、`scope_expansion`、`recoveries_for_task_routes`、`action_dispatch`。

**单测**：`tests/test_operator_boundary_path_resolve.py`、`tests/test_semantic_closure_p0_p2.py`；compose `apply-scope-expansion` METHOD。

**FAG arch35 局部回归**：boundary `inputs=27/outputs=7`，readable_source_count=confirmed；报告 `docs/performance/fag_arch35_semantic_closure_report.json`。完整 `acp complete` 仍需 Host LLM（W3）。

### A55：性能优化 P0/P1 缺口修复 — TG evidence 漂移 + update integrity 顺序（2026-07-27）

| 现象 | 根因 | 落点 | 状态 |
|---|---|---|---|
| TG `required_read`/`optional_read` evidence 丢失或混入 field_accesses | `ConsumerIndex` 把 `required_optional_evidence` 塞进 `field_accesses`；消费端用永不存在的 `kind=="required_optional"` 反推 | 共享 `consumer_index.required_optional_evidence`；`consumer_evidence` 只消费 index；stat/sha256 fingerprint | 已做 |
| `uo-update` apply 因 stale sqlite 失败 | `update_operator` structural 后先 `check_kb_integrity` 再 export | apply 只做 structural+receipt；gates/export 留给 `confidence_report`/`export_integrity`→`publish_kb_products` | 已做 |
| human views 双导出 | publish 与 integrity 各 export 一次 | `check_kb_integrity(refresh_human_views=False)`；publish 末尾单次 `export_human_views` | 已做 |
| update Action 重复 detect/plan | plan/apply/diff 各自重跑 | 共享 `update_artifact_io.load_*_if_fresh`；engines 只调用 | 已做 |
| kernel 文件级并行未接入 / 测试是 fake | worker 脚手架未挂 extract；monkeypatch 假并行 | `kernel_file_worker` + `extract_kernel_subgraph`；真实多文件串并等价测试；fallback 可观测 | 已做 |
| SQLite skip 太晚 / YAML 仍全量 dump | skip 在 entity 物化后；无 content-hash sidecar | `export_kb_graph` 前移 skip；`_ir_io.write_yaml_if_changed` sidecar | 已做 |

**不做**：不在 skill/METHOD/prompt 写性能例外；不改 scoring 阈值；不硬编码 FAG。

**性能文档**：`docs/performance/after.md`；探针 `scripts/profile_uo_pipeline.py`（有效 run_id、rebuild error、可选 TG 双跑）。

**A55 审查补丁**：`load_change_set_if_fresh` 校验 `head_revision==git HEAD` 与 `base_revision==manifest.source.revision`；`update_operator` 生产路径 `allow_empty_plan=False`；`write_yaml`/`atomic_write_yaml`/`commit_semantic_artifacts` 失效 `.content-hash` sidecar；consumer cache 纳入 `ctime_ns` + 可选 `TG_CONSUMER_CACHE_VERIFY_HASH`；Host/Kernel ProcessPool 内层 `file_parallel=False` 防嵌套；删除误提交 `session-ses_*.md`。

### A56：uo-init 正确性闭环 — task canonicalize / session / scope / bridge / freshness / IO（2026-07-27）

| 现象 | 根因 | 落点 | 状态 |
|---|---|---|---|
| 低分空候选 → mark_missing → contract conflict | upsert 先锁 `mark_missing`，空候选不规范化 | `llm_tasks.upsert_tasks_from_score_items`；contract 只看 `effective_task_type` | 已做 |
| Debug-off after-hook 无法 patch child | `patch_child_session_id` 先查 debug registry | 控制面 `patch_external_session_id` 优先；debug 仅 mirror | 已做 |
| request consumed 但 scope 未应用 | 先 consumed 再写 scope；缺文件仍推进 | `SCOPE_CONFIRMED_MISSING` fail-closed；写后重读校验 | 已做 |
| 预算静默丢 accepted 文件 | `break` / `newly[:budget]` | 全文件 disposition；deferred ≠ consumed | 已做 |
| evidence / basename include 假匹配 | 本地 OR 校验；`include_edge_name` | 上收 `source_evidence` + `source_include_closure.classify_include_resolution` | 已做 |
| include closure 多文件 SSOT 碎 | writer/reader 路径不一致 | 统一 `ir/include_closure.yaml` SSOT | 已做 |
| CBM 只 staged 当完成 | 覆写 `index_meta` + 直跳 `detect_score_post` | `pending_index` + `cbm_reindex_request`；receipt 前禁 score | 已做 |
| update 复用忽略 scope 变更 | freshness 缺 fingerprint / skip-when-missing | `update_artifact_io` 强制 scope/change_set/plan fingerprints | 已做 |
| bridge blocking 无 llm_task | `detect_score_post` 不扫 unresolved | `score_bridge_blocking_gaps` → upsert | 已做 |
| typed 元数据丢 / `id:null` | `_collect_typed_fields` 丢字段 | determinant 传播 + `mint_field_identity` 稳定 ID | 已做 |
| external registry 并发丢失 | YAML RMW 无锁 | SQLite `registrations` 事务 + CAS | 已做 |
| content-hash 崩溃窗口 | 先写 YAML 再写 sidecar；skip 不验文件 SHA | invalidate → temp+fsync+replace；`actual_yaml_sha256` | 已做 |

**共享层**：`source_evidence`、`source_include_closure`、`semantic_task_triage`、`external_session_registry`、`update_artifact_io`、`_ir_io`。未改个别 skill METHOD 例外；未跑 compose（Policy 无 diff）。

**单测**：`test_semantic_task_canonicalize`、`test_external_session_lineage`、`test_scope_expansion_correctness`、`test_update_artifact_freshness`、`test_bridge_gap_tasks`、`test_yaml_write_if_changed`。

**未做**：完整 OpenCode hook / MCP reindex / 全量 FAG `acp complete`（依赖外部环境）；性能自适应调度独立提交。


### A57（第二轮 P0/P1 正确性补丁，相对 A56）

静态审查发现 5 个主流程 P0 仍阻塞 `integration_verified`。本轮只修正确性断点：

| # | 问题 | 落点 | 状态 |
|---|---|---|---|
| P0-1 | `detect_kb_changes` 不读 `confirmed_source_files` | `_extract_file_list` 与 scope expansion 同 key | 已做 |
| P0-2 | include missing 仍标 `complete` | `write_include_closure_ssot` blocking kinds → `partial` | 已做 |
| P0-3 | 无 snippet/SHA 的 lines-only evidence 假通过 | `verify_scope_symbol_evidence` fail-closed | 已做 |
| P0-4 | Bridge 零候选进 generic candidate_generation | triage 优先 `tilingdata_type_unknown`；`_infer_patch_type` bridge 优先 | 已做 |
| P0-5 | 非 Host determinant 仍留 missing_producer blocking | 分类后过滤 unresolved/diagnostics | 已做 |
| P1 | engines 覆盖 `next_actions`→`detect_score_post` | 保留 `uo_scope_record_index` / `pending_index` | 已做 |
| P1 | record-index 不解除 pending | `complete_cbm_index_receipt` + prepare `--write-index-meta` | 已做 |
| P1 | freshness 信任过期 snapshot fp | `current_scope_identity` 始终重算；比 revision/hash | 已做 |
| P1 | patch orphan 自动 register | 默认 `no_pending_registration`；SQLite `lookup_registration` | 已做 |

**判定**：`unit_fix_direction: mostly_correct`；**仍非** `integration_verified` / `full_fag_verified`（未跑 OpenCode hook + MCP + FAG）。


## 14. 一句话原则（沉淀）

1. **Pilot 独占状态**；Skill/Prompt 不推进阶段。  
2. **歧义就问**（路径/arch/continue；**tg-init** 才问测试脚本），禁止 Glob 考古。  
3. **只跑 recommended_next**；finalize 后立刻再 `acp next`。  
4. **LLM 产物必须有 producer 合同**；deterministic 只应用。  
5. **Gate fail → rework**，不是一上来 blocked；失败要落 Observation，禁止逃逸手工修 / **禁止 primary 代写 IR**。  
6. **extract ≠ 边裁决**；空候选禁止假 ACCEPT；`non_sink_roots` 只认字符串名。  
7. **CBM 不做 KEY/宏表主路径**；语义结论须取窗（MCP 全名 / `acp cbm lookup` / 窗口 Read）。  
8. **同 Action rework 必须 resume**；Task 正文只粘**原样 stub**（禁止塞 `REWORK:` 长文；细节只进 `rework_hints.yaml`）。  
9. **高置信规则进公共 Policy/Capability/共享校验**，禁止只改个别 skill。  
10. **Lease：write ⊆ read**；高置信 = **窗口 sha AND 连续 snippet**（禁止 OR / 拼贴）；大 IR 可有 `*.summary.yaml`。  
11. **改完要 compose + refresh + 重启 OpenCode** 才测的是新代码。  
12. **Gate 与 apply 同源 validate**；Host 禁盲信「无候选」；禁空 Task prompt。

---

## 15. 附录：如何自己翻 Cursor 记录

```text
C:\Users\sunye\.cursor\projects\d-PR-review\agent-transcripts\<uuid>\<uuid>.jsonl
```

- 每个 `<uuid>` 目录是一次 Cursor 父会话；`subagents/` 为子代理。  
- 可用标题引用：`[短标题](uuid)`。  
- OpenCode 侧 session 常在工作区根或算子目录：`session-ses_*.md`。
