---
name: tg-plan
description: >-
  Build L0–L3 coverage plan after contract + LLM binding review are ready.
  Test tools auto-run thin contract; plan still requires confirmed domains/lexicon for solve.
argument-hint: "<算子仓|kb> --op-name <op> (--test-script-root <测试工具> | --contract-root <realization>) [--level L0|L1]"
---

# /tg-plan

## 输入门禁（缺一不可，先问再跑）

必须同时具备：

1. **算子仓**（含 `.understand-operator/<op>/`；也可传 KB 路径）
2. **二选一**：
   - **测试工具** `--test-script-root` → **自动执行 thin contract**，再 plan
   - **contract 产物** `--contract-root` → 复用已有 `realization/`

若用户只说了「做 plan」而缺少上述任一输入：**Stop，用 AskQuestion 索要**。

## Contract → LLM 绑定（嵌入路径）

若刚跑完 contract 且存在：

- `realization/unresolved.yaml` 含 `binding_gaps` / `needs_binding_keys`，或
- `domain_review.status=pending`

则 **Stop**：先跑 `/tg-csv-contract` 或 `tg-domain-review`，AskQuestion 确认后再继续 plan。
**禁止**为单个算子往 AST 插件里加特化规则。

## MUST — 调真实 CLI

```powershell
tg-plan "<算子仓>" --op-name <op> --level L0,L1 --test-script-root "<测试工具>"
# 或
tg-plan "<算子仓>" --op-name <op> --level L0,L1 --contract-root "<.../realization>"
```

## HARD STOP — human review

CLI 成功后 **stop**。AskQuestion：`approve` / `reject` / `suggest`。  
`approve` → 立刻 `tg-solve`（同一 `project_root` / `--op-name` / `--level`）。

## Notes

- 产物在 `<算子仓>/.testcase-generator/<op>/`。
- 不要修改 `.understand-operator/`（除非用户确认写回 `supplements/human_facts.yaml`）。
