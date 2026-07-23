# confidence_review (migrated domain method)

> Domain content migrated from skills/uo-init/references/confidence-gate.md. Do not advance Pilot state from this file.

# 最终置信度门禁（强制 high）— Pilot 权威

`/uo-init` 收工前：凡已闭合交付的 KEY 必须 `confidence: high`。  
完成判定**只认** Pilot：`acp run-action confidence_report` + `acp validate-key-gates` / `acp complete`。  
**禁止**直调 `check_final_confidence.py` / `classify_input_derivable.py`。  
Skill/Agent **不得**自行宣布 done。

## 运动员 / 裁判分离

| 角色 | Agent | 职责 |
|---|---|---|
| 运动员 | `uo-key-resolve` | triage/resolve、写 patch 原因字段（非 high KEY） |
| 确定性引擎 | `deterministic-uo-engine` / `acp emit-confidence-report` | 组装 `summary/confidence_report.md` + `checks/confidence_gate.yaml` |
| 裁判 | `uo-confidence-review` | 只审报告与门禁；写 `review/confidence_reason_review.yaml` |

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

1. 按 `acp next` 完成 `key_triage` / `key_resolution`（写 patch；勿直调 .py）。
2. `acp run-action confidence_report`（确定性 classify + confidence gate）。
3. 若 `need_llm_count>0` 或 status=reported → 派 **`uo-confidence-review`**。
4. 门禁与状态：

```powershell
acp validate-key-gates "$PROJECT_ROOT"
acp advance export --project "$PROJECT_ROOT"   # resolve→export 需 phase_gates
# … export_integrity / kb-review …
acp complete --project "$PROJECT_ROOT"        # 唯一合法 pass
```

6. `status=fail` → 继续 KEY resolve / 补非同文原因 / 再派裁判。

## 产物

- `summary/confidence_report.md` — 运动员
- `review/confidence_reason_review.yaml` — 裁判
- `checks/confidence_gate.yaml` — 脚本
- `checks/pilot_key_gates.yaml` — Pilot
- `.ascendc-pilot/state/workflow.yaml` — 唯一完成态权威
