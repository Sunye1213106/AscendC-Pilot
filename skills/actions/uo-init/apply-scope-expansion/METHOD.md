# 审核并应用 scope expansion

## Goal

对 LLM 提议的 `scope_expansion_requests.yaml` 做确定性审核（存在、可达、算子/common 根、arch 兼容、预算、去重），写入 `scope_expansion_decisions.yaml` / `scope_expansion_receipt.yaml`，并更新最新 `scope_confirmed`。

**不做**：全仓扫描；按变量名猜语义；放宽 Gate。

## Domain Procedure

1. 前置：`adjudicate_llm_tasks` 产出 `scope_expansion_request` patch（写入 requests）。
2. Pilot `run-action apply_scope_expansion`。
3. 审核通过的文件追加进 confirmed scope；失败写 rejected 原因。
4. 成功后 `acp next` → `detect_score_post`（或按 recovery：`rebuild_from_ledger`）。
5. 预算耗尽 / 无进展 → `human_required`，禁止无限重试。

## Output

- 合同 id：`scope-expansion-v1`
- `ir/scope_expansion_receipt.yaml`
