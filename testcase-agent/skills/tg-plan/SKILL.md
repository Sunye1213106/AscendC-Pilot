---
name: tg-plan
description: >-
  TG stage-2 after tg-init confirmed. LLM maps human scope to KEY/VAR/branch
  (empty=all input-reachable); default L0+L1; optional L2. Approve only when
  Allow solve:yes.
argument-hint: "<算子仓> --op-name <op> [--focus <vars/keys>] [--level L0,L1|all] [--topic <scope>]"
---

# Skill: tg-plan

## Purpose

`init.status=confirmed` + 定稿 KB → **已批准** coverage plan（`Allow solve:yes`）。

1. **人工输入**（变量 / KEY / 场景）→ LLM 落到稳定 id → `--focus`（+ 可选 `--topic`）出计划  
2. **无输入** → 默认测 **全部输入可达** 面（L0+L1；可选 L2）  
3. 始终剔除核内不可控 / `not_input_derivable`（与 init 合法 skip 一致）

## Trigger

- 用户 `/tg-plan`；init 已 confirm 后生成/审批覆盖义务
- **不适用**：未 confirm（回 `/tg-init`）；已批准后求解（`/tg-solve`）

## Inputs

| 权威 | 说明 |
|---|---|
| `.testcase-generator/<op>/contract/testcase.yaml` | TG 测项合同 |
| confirmed realization | 绑定真值；禁手改 lexicon |
| `$UO_ROOT` 定稿 KB | **只读**覆盖语义 + `input_derivable` |
| 人工范围 | 自然语言或 id 列表；空 = 全部输入可达 |
| `--focus` | LLM 写入的 KEY/VAR/branch 选择 |
| `--level` | 默认 `L0,L1`；可选加 `L2` / `all` |
| `--topic` | 主题裁剪；可与 focus 叠加 |

## Outputs

正式：`plan/review.md`、`plan/levels/<L0|L1|L2>/`、`plan/human_supplement.yaml`。

**禁止**：改 lexicon；写入 `$UO_ROOT/**`；CSV 行；伪造 `Allow solve:yes`；把 UO `contracts/` 当测项权威；把 loopId/blockId 当必须覆盖点。

## Invariants

- Entry 必须 `init.status=confirmed`
- 无人工范围 → 全部 **输入可达**；有范围 → 只覆盖 focus 命中实体
- L0=功能冒烟；L1=范围内 kernel branch；L2=全部可达 TilingKey
- 批准后 plan 为 solve 只读权威
- 缺口大 → 回 `/tg-init`（uo-query 修 TG 绑定，不改 UO 图），勿手改 lexicon
- 语言：简体中文（`prompts/common/language.md`）

## Tool Policy

### MUST

```powershell
# Phase0：问清范围；空则不加 --focus
tg-plan "<算子仓>" --op-name <op>
tg-plan "<算子仓>" --op-name <op> --focus "KEY_Foo KEY_Bar"
# 或：--level L0,L1,L2  /  --topic <scope>
```

- 门禁失败 → 停止 approve（见 `references/approval-gate.md`）
- AskQuestion：`approve` / `reject` / `suggest`；仅 `Allow solve:yes` 可 approve

### MUST NOT

- plan 阶段做 KEY 语义绑定主路径
- 使用已移除的 `L3` / 默认展开 `L1-REJECT`
- 把 `not_input_derivable` / LOOP_LOCAL 实体标成必测

## Workflow

| Phase | Entry | Actions | Exit | Fail |
|---|---|---|---|---|
| 0 Scope | 用户触发 | LLM 解析人工范围 → focus/topic；空=全输入可达 | 范围就绪 | — |
| 1 Gate | 范围定 | `require_init_confirmed` | confirmed | `init_required` |
| 2 Build | gate pass | 生成 L0/L1（±L2）+ input_reachable 过滤 | `plan/levels/*` | `PLAN_BUILD_FAIL` |
| 3 Filter | build ok | reachability / focus / topic | 可达义务集 | Allow solve:no |
| 4 Review | 产物齐 | 人读 review | 决策就绪 | — |
| 5 Approve | Allow solve:yes | AskQuestion | `human_supplement` | `APPROVE_BLOCKED` |

命令块：`prompts/plan/workflow.md`。级别：`references/levels.md`。详文：`docs/tg-plan-workflow.md`。

## Failure Taxonomy

`init_required` · `PLAN_BUILD_FAIL` · `APPROVE_BLOCKED` · `DOMAIN_REVIEW_REQUIRED` ·
`BINDING_REVIEW_REQUIRED` · `KEY_DERIVATION_MISSING` · `INVALID_LEVEL`

## Quality Gate

- [ ] 每请求 level 有 `plan/levels/<level>/`
- [ ] approve 时 `Allow solve:yes`
- [ ] 未修改 lexicon / UO KB
- [ ] 覆盖面无核内不可控 id / not_input_derivable KEY

## Stop Conditions

- init 未 confirm → `/tg-init`
- Allow solve:no → 禁 approve
- 用户 reject → 停
