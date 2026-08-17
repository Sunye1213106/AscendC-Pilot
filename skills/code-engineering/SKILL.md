---
name: code-engineering
description: >
  Plan, scope, and verify AscendC code changes with UO slices, evidence tiers,
  risk classes, and a persistent verification-obligation ledger.
  Use when locating a change, grilling 需求范围与验收再分解特性, applying a
  confirmed intent 已确认意图按 plan.md / todo.md 改算子源码, slicing a diff, or closing
  obligations with measurement receipts. Boundary: not readonly code review;
  not TilingKey search. 不签发证书.
---

# Code Engineering

Use this skill for `/ce-intent`, `/ce-apply`, `/ce-impact`, `/ce-verify`, and `/ce-handoff`.
Precision/perf daily work infers a ScenarioSet (not all legal keys).

对齐 Issue 改码：无 diff 先问清再定位并冻结 `ce/intent/plan.md`，已 confirm 后按 plan / `ce/apply/todo.md` 一次一个切片改码并自动双轴并行审查刷图，有 diff 再切片挂义务，验证只收可审计的测量/测试收据。

完成条件：`Open = O - V - X` 中的 `V` 只来自本仓库可审计收据；`X` 只来自 referee。

```text
intent (grill → locate) -> plan.md -> apply (todo.md 一切片 + 双轴并行审查 + CodeMap) -> impact -> verify
Open = O - V - X
```

## When to use which

| 场景 | 入口 |
| --- | --- |
| Issue / 需求还没问清 | `/ce-intent`：grill 问清范围与验收，再分解、定位锚点 |
| 已 confirm，要按 spec 改码 | `/ce-apply`：读 `ce/intent/plan.md` 与 `ce/apply/todo.md`，一次一个切片，自动双轴并行审查并刷新 CodeMap |
| 已有改动 / diff | `/ce-impact`：切片 + 按 kind 挂义务 + 精度/性能场景 |
| 要关闭义务、出证书 | `/ce-verify`：V 只收本仓库可审计的测量/测试收据 |
| 换窗口 / 上下文满 / 交给同事 | `/ce-handoff`：只引用产物路径，写明后续 slash 命令 |
| 静态「该测哪些精度/性能」 | 同 `/ce-intent` 扫描，产出 ScenarioSet |

Git 写操作、fork、PR 文案走维护者流程，不在本 skill。只读审查走 `/ce-review`。

## Non-negotiable rules

1. Preserve evidence tier: Tier A is direct authoritative evidence, Tier B is
   deterministic derivation from Tier A, and Tier C is a hypothesis or lead.
2. Maintain `Open = O - V - X`, where `O` is all obligations, `V` is verified,
   and `X` is referee-approved exclusions.
3. Tier C evidence can discover or refine obligations; only A/B can place an
   obligation in `V` or `X`.
4. A truncated slice or stale UO product is a disclosed boundary, never proof
   that impact is absent.
5. Precision and performance claims require declared external measurements.
6. External V receipts use schema `ce-external-evidence/v1`. Accept UT / ST /
   precision compare / profiling / retest-pass artifacts. A review narrative is
   not a measurement. Precision/perf runners come from the operator's optional
   test-script repo (`--test-script-root`); CE PRs may patch those scripts from
   TG `findings`. Test-script repo contract is owned by testcase-generation;
   this Action materializes it via the Context Profile, not by inlining that skill.

## Risk language (developer → CE class)

| 开发者看到的失败 | UO `impact` 分桶 | CE `risk_class` | 典型 V |
| --- | --- | --- | --- |
| Tiling 失败 / Kernel 找不到 | dispatch | dispatch | 复测 / 合法 Key 跑通 |
| 字段公式 / 布局 | layout | contract / shape | 静态源码证明或 UT |
| 越界 / Buffer | memory | sync / shape | sanitizer 或边界 UT |
| 同步缺失 / 卡死 | sync | sync | 复测通过；UO 不证明配对 |
| 精度 | precision | precision | 精度对比收据（`P-*` 场景） |
| 性能 | perf | perf | profiling 收据（`F-*` 场景） |

## Capability routing

- Impact completeness and obligation audit:
  `capabilities/ce-impact-audit/METHOD.md`
- Exclusion review:
  `capabilities/ce-exclusion-review/METHOD.md`
- Evidence and slicing:
  `references/evidence-tiers.md`, `references/slice-primitives.md`,
  `references/evidence-discipline.md`
- Risk classification:
  `references/risk-classes.md`
- Scenario ids (catalog is the source of truth):
  `references/scenario-catalog.md`
- Scenario infer (engine writes skeleton):
  `references/scenario-infer.md`
- Scenario knobs (agent overlay, Host merges before confirm):
  `capabilities/ce-scenario-knobs/METHOD.md`
- Feature decompose / plan review:
  `capabilities/ce-feature-decompose/METHOD.md`,
  `capabilities/ce-plan-review/METHOD.md`
- Intent grill / apply / session handoff:
  `capabilities/ce-intent-grill/METHOD.md`,
  `capabilities/ce-apply/METHOD.md`,
  `capabilities/ce-handoff/METHOD.md`
- Harness evidence check (verify, deterministic engine):
  `capabilities/ce-harness-evidence/METHOD.md`
