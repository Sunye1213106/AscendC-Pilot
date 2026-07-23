# 最终置信度门禁（强制 high）— Harness 权威

`/uo-init` 收工前：凡已闭合交付的 KEY 必须 `confidence: high`。  
完成判定**只认**脚本：`check_final_confidence.py` + `harness validate-key-gates` / `harness complete`。  
Skill/Agent **不得**自行宣布 done。

## 运动员 / 裁判分离

| 角色 | Agent | 职责 |
|---|---|---|
| 运动员 | `uo-key-resolve` | triage/resolve、写 patch、为非 high KEY **撰写** `summary/confidence_report.md` 原因 |
| 裁判 | `uo-confidence-review` | **只审**原因质量；写 `review/confidence_reason_review.yaml`（`agent: uo-confidence-review`） |
| 终审 | `uo-kb-review` | integrity 通过后的产物抽查 |

裁判**禁止**代写/改写报告正文刷 pass。

## 规则

| 情况 | 动作 |
|---|---|
| 图/脚本已闭合且 `confidence: high` | 可交付 |
| `unsolved` 或 confidence≠high | **必须**派 `uo-key-resolve`；并写满中文「原因」 |
| gaps / escalate_keys 非空但无 `ir/key_triage.yaml` | **fail**（禁止父代理直接 accepted） |
| missing_producer 仅 empty 路径 | **不得** final accepted；apply/classify **拒收** |
| LLM 仍无法 high | 写 `summary/confidence_report.md`；**禁止**多 KEY 复制同一套 bit-pack 借口 |
| 非 high 项已写原因 | **必须**派 `uo-confidence-review`；缺裁判产物 → gate fail |
| `closed_high_count=0` 且 KEY 非空 | **默认 fail**（任意 confidence_gate status）；仅 `checks/human_accept_reported.yaml` 可放行 |

## 父代理步骤

1. `tpl_key_triage` → `tpl_key_resolve`；记录 subagent 收据（`.ascendc-agent/runs/<run_id>/subagents/`）。
2. `classify_input_derivable.py`（缺收据 / empty-only 的 KEY patch **被拒收**）。
3. `check_final_confidence.py`。
4. 若 `need_llm_count>0` 或 status=reported → 派 **`uo-confidence-review`**（`tpl_confidence_reason_review.md`）。
5. 门禁与状态：

```powershell
harness validate-key-gates "$PROJECT_ROOT"
harness advance export --project "$PROJECT_ROOT"   # resolve→export 需 phase_gates
# … integrity / kb-review …
harness complete --project "$PROJECT_ROOT"        # 唯一合法 pass
```

6. `status=fail` → 继续 KEY resolve / 补非同文原因 / 再派裁判。

## 产物

- `summary/confidence_report.md` — 运动员
- `review/confidence_reason_review.yaml` — 裁判
- `checks/confidence_gate.yaml` — 脚本
- `checks/harness_key_gates.yaml` — Harness
- `.ascendc-agent/state/workflow.yaml` — 唯一完成态权威
