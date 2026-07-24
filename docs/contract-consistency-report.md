# AscendC-Pilot 前后契约一致性修复 — 综合报告

> 更新日期：2026-07-24  
> 验证：`python scripts/check_contracts.py` → ok；相关 pytest **45 passed**

---

## 1. 修复前的主要矛盾链

1. **双轨完成定义**：`recommended_next_action` 用产物启发式，`advance` 用零散 phase_gates，Host 仍可 `acp advance` 跳过未完成 Action。
2. **Contract fail-open**：未注册 Output Contract 在 finalize 时 `skipped: True` 仍签发收据。
3. **finalize 弱绑定**：prepare 后切阶段 / 切换 active_action 仍可能 finalize。
4. **KEY 假闭合**：triage 收据 + patch 文件可通过 resolution Gate；uo-update 缺 `key_triage`；Agent 可写两方产物。
5. **semantic patch 半提交**：多 patch 逐条落盘，第 N 条失败留下前 N−1；`total_semantic_batches` 按条递增。
6. **resume 误删**：任意 workflow reinit 都 `wipe_uo`；AskQuestion 写死 uo-init；owned map 含无效 `input_derivable`。
7. **多事实源**：pipeline 手写列表、SKILL Actions 表、Prompt `workflow_id`、resume scrub 表与 Spec 漂移。

---

## 2. 各阶段设计决策

| 阶段 | 决策 |
|------|------|
| 一 | Spec `pipelines` 为唯一顺序；完成=当前 run 收据（或显式 N/A）；advance 先查 pipeline；未知 Contract fail-closed |
| 二 | triage/resolution 写权限按 `active_action` 互斥；删 receipt fallback；uo-update 对齐 triage→resolution；prepare 注入有限 target_ids |
| 三 | validate-all-then-commit；每成功 batch `total_semantic_batches += 1`；Gate/Apply 共用校验；stale 无副作用 |
| 四 | Spec `reset_policy`；按 workflow 隔离 wipe；owned artifacts 从 Contract 派生；AskQuestion 用当前 workflow |
| 五 | `consistency.check_all` + `scripts/check_contracts.py`；共享 Prompt 用 `<WORKFLOW_ID>` |

---

## 3. 删除的 fallback / 默认成功 / 宽松兼容

- Output Contract 未知 / 缺失 → 不再 `skipped` 成功
- `pipeline_complete` 时任意 prepare → 改为 `PIPELINE_COMPLETE_ADVANCE_REQUIRED`
- `gate_key_resolve_receipt` 的 `require_action_id=False` 回退
- uo-scope 默认 `action_id=scope_confirmation`
- apply 中 `source_snapshot_stale` 落盘 supersede
- 全局 `wipe_uo_for_reinit` 套用于非 uo-init
- resume 手工 key `input_derivable`
- 产物存在即 `_action_done`（改为收据）
- 共享 Prompt 写死 `uo-init` / `uo-update`

---

## 4. 新关系（控制面）

```
Workflow Spec (pipelines, actions, gates, reset_policy, contracts)
    → recommend / PIPELINE_SKIP / PIPELINE_INCOMPLETE
    → prepare (targets, lease, active_action)
    → actor write scopes (action-narrowed)
    → finalize (session bind + registered contract + gates)
    → HMAC receipt (run_id + action_id)
    → advance / complete (pipeline receipts + phase_gates)
    → resume continue/reinit (reset_policy + contract-owned scrub)
```

Pilot 仍是状态、Action 顺序、收据与完成态的唯一控制面；Prompt/METHOD 不得替代状态机。

---

## 5. 行为变化

| Workflow | 变化 |
|----------|------|
| **uo-init** | prepare 必须有 `prepare_layout` 收据才能 advance；extract/resolve 严格按 Spec pipeline；KEY 边界互斥；semantic batch 原子；reinit 删 `uo/`，默认保留历史 runs |
| **uo-update** | 增加 `key_triage`；resolve pipeline 与 init 同序；reinit **保留**有效 UO KB，只清 update 临时路径 |
| **TG-*** | reinit 只清 `tg/`，**不删** UO；AskQuestion 显示真实 workflow 名 |
| **CE** | reinit 只清 CE 产物；保留 UO/TG |

---

## 6. 新增/修改的测试

- `pilot/tests/test_control_plane_closure.py`（阶段一）
- `pilot/tests/test_key_action_boundaries.py`（阶段二）
- `engines/understand-operator/tests/test_semantic_batch_tx.py`（阶段三）
- `pilot/tests/test_run_resume.py` 扩展（阶段四）
- `pilot/tests/test_consistency_ssot.py`（阶段五）
- 连带更新：`test_pilot_core.py`、`test_semantic_patch_pipeline.py`

---

## 7. 完整测试结果（关键集）

```text
python scripts/check_contracts.py
→ {'ok': True, 'errors': []}

python -m pytest pilot/tests/test_consistency_ssot.py \
  pilot/tests/test_control_plane_closure.py \
  pilot/tests/test_key_action_boundaries.py \
  engines/understand-operator/tests/test_semantic_batch_tx.py \
  pilot/tests/test_run_resume.py -q
→ 45 passed
```

另：`test_score_resolve_loop.py` + `test_semantic_batch_tx.py` + `test_semantic_patch_pipeline.py` → 27 passed（阶段三验收）。

---

## 8. 仍未解决的问题与风险

- `authorize` 仍依赖宿主 hook，非 OS 级隔离；旁路终端仍可能绕过写围栏（需运维纪律）。
- `extract_plan_subagent` Gate 仍以产物为主（收据为诊断）；与 finalize 鸡生蛋约束有意保留。
- `generated/` 必须在改 skill/prompt 后 compose；CI 应固定跑 `check_contracts.py`。
- 部分引擎合并产物（如 TG semantic_bind）的写权限交叉检查使用例外规则，需新增 Action 时人工确认。

---

## 9. 旧 `.ascendc-pilot` 产物迁移

- **需要**：缺当前 run 收据的旧产物不能再过 advance；半提交 ledger/tasks 需 `continue` scrub 或 workflow 级 `reinit`。
- **uo-update 中断**：勿用旧的全局 wipe 心智；使用新策略保留 KB。
- **KEY**：仅有 triage 收据 + patch 文件不再过 resolution Gate；须补跑 `key_resolution` finalize。

---

## 10. 兼容与升级建议

1. 升级 Pilot 包后执行 `python scripts/check_contracts.py`。
2. 对进行中的 uo-init：优先 `acp start …` → AskQuestion **继续**（scrub 半成品）而非盲目删除。
3. TG/CE 项目确认 reinit 不再误删 UO。
4. 宿主侧 refresh OpenCode/Cursor 插件并重启，使 generated skill/agent 与 Spec 一致。
5. 新增 Workflow/Action：**只改 `specs.py` + METHOD/prompt/contract 注册**，然后跑 `check_contracts.py`；禁止再手写第二套 pipeline/resume 表。

---

## 主要改动模块索引

- `pilot/ascendc_pilot/workflows/specs.py` — pipelines、reset_policy、uo-update key_triage
- `pilot/ascendc_pilot/workflows/pipeline.py` — 收据完成定义
- `pilot/ascendc_pilot/workflows/consistency.py` — SSOT 检查
- `pilot/ascendc_pilot/state/machine.py` — advance PIPELINE_INCOMPLETE
- `pilot/ascendc_pilot/actions/runtime.py` — contract fail-closed、finalize 绑定、KEY targets
- `pilot/ascendc_pilot/gates/__init__.py` — prepare_layout_receipt、KEY 严格收据、apply_semantic_patch
- `pilot/ascendc_pilot/agents_registry.py` — KEY write scope 收窄
- `pilot/ascendc_pilot/run_resume.py` — workflow-scoped resume
- `pilot/ascendc_pilot/uo_scope.py` — 无 active 则失败
- `engines/understand-operator/uo/scripts/llm_tasks.py` — 事务化 batch
- `scripts/check_contracts.py` — 统一校验入口
