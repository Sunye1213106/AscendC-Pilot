# Boundary Human Review (retired gate)

**Phase 1.5 已取消。** 本文件仅保留作参考，workflow **不得**再在 Phase 1 后强制 STOP，也**不得**再向对话倾倒 Boundary/IO 审阅摘要。

Phase 1（Macro Boundary）完成后应：

1. 写好 `operator.yaml`（含 IO / boundary / analysis_plan）等 artifact（含 `human/review.md` Boundary Review 草稿，供日后查阅）
2. TodoWrite：`uo-p1` → completed；更新 `workflow_progress.yaml`
3. **对话里不要输出** IO 列表、边界摘要、open_questions、请确认类文案
4. **直接进入 Phase 2** 并行 `uo-host-extraction` + `uo-flow-extraction`

人工决策（暂停 + 给人判断的信息）**只**允许在：

- Phase 0.5 Macro Scope（探索范围）— 见 `01a_macro_scope_human_review.md`
- Kernel dispatch review 已退役；Phase 3 使用 slice validation 与 Step 3 review。

若用户在对话里主动要求修订边界，可临时写入 `human/review.md` Boundary Review / `archive/runs/boundary_review.yaml`，但默认流水线不经过此闸门，也不主动弹出边界摘要。
