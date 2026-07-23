# plan_approve (migrated domain method)

> Domain content migrated from skills/tg-plan/references/approval-gate.md. Do not advance Pilot state from this file.

# Approve 门禁（tg-plan）

## Allow solve:yes 前提

- `init.status=confirmed`
- 无开放 `DOMAIN_REVIEW_REQUIRED` / `BINDING_REVIEW_REQUIRED`（回 `/tg-init`）
- L1 无阻塞性 `KEY_DERIVATION_MISSING`
- L2 未因 exhaustive KEY 空间不可用而 `blocked`

## AskQuestion

`approve` | `reject` | `suggest`

- approve：**仅**当 review 标明 Allow solve:yes
- reject：停
- suggest：只改 plan 草案，禁改 lexicon

## MUST NOT

- 手改 lexicon「凑」Allow solve
- 未闭合 KEY 强行批准
