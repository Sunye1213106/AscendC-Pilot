# uo-init / AscendC-Pilot 联调问题与修复记录

> 范围：OpenCode + AscendC Pilot（含早期 Harness / Ascendc-PR-test-agent）在 FASG 等算子上的联调。  
> 更新日期：2026-07-24  
> 证据来源：
> - Cursor 对话（`~/.cursor/projects/d-PR-review/agent-transcripts/`，约 69 条父会话，其中 ~30 条与 Pilot/UO 强相关）
> - OpenCode session：`session-ses_06e5` / `06e3` / `06e2` / `06e0` / `06dc` / `06d8` / `06d6`，以及更早的 `ses_0711` / `070d` / `076d` / `0772` 等

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
6. 可选：`acp debug enable`（重装后一般仍 enabled）

相关单测：`test_semantic_patch_pipeline.py`、`test_prepare_placeholders.py`、`test_uo_output_contracts.py` 等。

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

---

## 14. 一句话原则（沉淀）

1. **Pilot 独占状态**；Skill/Prompt 不推进阶段。  
2. **歧义就问**（路径/arch/continue；**tg-init** 才问测试脚本），禁止 Glob 考古。  
3. **只跑 recommended_next**；finalize 后立刻再 `acp next`。  
4. **LLM 产物必须有 producer 合同**；deterministic 只应用。  
5. **Gate fail → rework**，不是一上来 blocked；失败要落 Observation，禁止逃逸手工修。  
6. **extract ≠ 边裁决**；空候选禁止假 ACCEPT。  
7. **CBM 不做 KEY/宏表主路径**。  
8. **改完要 compose + refresh + 重启 OpenCode** 才测的是新代码。

---

## 15. 附录：如何自己翻 Cursor 记录

```text
C:\Users\sunye\.cursor\projects\d-PR-review\agent-transcripts\<uuid>\<uuid>.jsonl
```

- 每个 `<uuid>` 目录是一次 Cursor 父会话；`subagents/` 为子代理。  
- 可用标题引用：`[短标题](uuid)`。  
- OpenCode 侧 session 常在工作区根或算子目录：`session-ses_*.md`。
