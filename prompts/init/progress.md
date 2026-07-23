# init 进度 Todo（唯一清单 · 中文）

父代理必须用下列 **7** 条 Todo，禁止拆成脚本名级微任务，禁止英文 Todo。

| # | Todo 文案 | 进入条件 | 完成条件 |
|---|---|---|---|
| 1 | 创建知识库目录 | 用户触发 | `prepare_operator` 成功，`UO_ROOT` 存在 |
| 2 | 扫描并提案分析范围（含向上发现 common） | #1 | `scope_proposal.yaml` 可读；stdout 含 INCLUDE/EXCLUDE 计数表 |
| 3 | 等待确认分析范围（硬门禁） | #2 | 用户 `continue` 且 checkpoint 写入；**禁自动 continue**；须转述脚本计数表 |
| 4 | 索引代码图并完成范围收尾 | #3 已确认 | `index_stage` 已 MCP 索引 + `index_meta` + `finalize_phase0` |
| 5 | Extract：按 `references/extract.md` Step 1–5 完成入口/plan/分层抽取 | #4 | `entrypoints.yaml` + `extract_plan.yaml` + layered IR；gaps 文件存在 |
| 6 | Resolve：按 `references/resolve.md`（残留 + KEY triage/resolve + 原因裁判 + 门禁 + 导出 + integrity） | #5 | unresolved 清空；confidence_gate pass/reported；`confidence_reason_review`（若 need_llm）；integrity pass；`harness advance` 成功 |
| 7 | KB 产物审查（uo-kb-review）→ `harness complete` | #6 | `kb_product_review.yaml` verdict=pass → human_views → **`harness complete` pass** |

## 硬规则

- 内部预检 / 路径解析 **不**单独占 Todo
- #3 未确认 **不得**进入 #4（索引）；Phase0 **禁** explore 预扫
- #6 含 `uo-key-resolve` triage→分流、非 high 原因、`uo-confidence-review` 裁判、`check_final_confidence` 与 `harness validate-key-gates`；不得跳过 gaps open
- 完成态只认 **`harness complete`**，禁止 Agent 自报 done
- Todo #1–7 对应编排 Phase **0–3**（见 `workflow.md`），勿再拆出额外 Phase 编号
- 语言：`common/language.md`；编排：`workflow.md`；派发：`dispatch.md`

## 失败时 Todo 状态

- 用户 `stop` → 取消后续 Todo，保留已完成记录
- `rework_stage` 返工 → 回到对应 #5/#6，不新开平行 Todo 树
- 工具失败 → 当前条标失败并报告路径，禁止假装完成
