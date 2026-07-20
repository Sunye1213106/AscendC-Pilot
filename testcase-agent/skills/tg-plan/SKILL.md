---
name: tg-plan
description: >-
  Build L0–L3 coverage plan from 算子仓 + (测试工具|contract产物). Test tools
  auto-run contract. Use when the user runs /tg-plan or asks to plan cases.
argument-hint: "<算子仓|kb> --op-name <op> (--test-script-root <测试工具> | --contract-root <realization>) [--level L0|L1]"
---

# /tg-plan

## 输入门禁（缺一不可，先问再跑）

必须同时具备：

1. **算子仓**（含 `.understand-operator/<op>/`；也可传 KB 路径）
2. **二选一**：
   - **测试工具** `--test-script-root` / `--csv-consumer-root` → **自动执行 contract**，再 plan
   - **contract 产物** `--contract-root` → 复用已有 `realization/`，不再扫测试工具

若用户只说了「做 plan」而缺少上述任一输入：**Stop，用 AskQuestion 索要**，禁止脑补路径、禁止手写 plan。

AskQuestion 选项示例：

- `provide_test_tool` — 用户将给出测试工具路径（自动 contract）
- `provide_contract` — 用户将给出 realization / contract 产物路径
- `cancel`

## MUST — 调真实 CLI

禁止手写 `plan/*.yaml`、`solved_testcases.csv`、自造 `solve.py`。

```powershell
# A) 算子仓 + 测试工具 → 自动 contract + plan
tg-plan "<算子仓>" --op-name <op> --level L0,L1 --test-script-root "<测试工具>"

# B) 算子仓 + 已有 contract 产物
tg-plan "<算子仓>" --op-name <op> --level L0,L1 --contract-root "<.../realization>"
```

完成证明：

| 模式 | JSON 字段 |
|------|-----------|
| 测试工具 | `"input_mode":"build_contract"`, `"contract_embedded":true` |
| contract 产物 | `"input_mode":"reuse_contract"`, `"contract_embedded":false` |
| 共用 | `realization_root` 存在且含 `realization_map.yaml` |

## 对话路径映射

| 用户说法 | CLI |
|---------|-----|
| 算子仓 / 算子包 | positional `project_root` |
| KB / `.understand-operator[/op]` | positional 或 `--kb-root` |
| 测试工具 / 测试脚本 / fag_debug_tools | `--test-script-root` |
| contract / realization 产物 | `--contract-root` |

两者都给时：**优先测试工具**（重建 contract）。

## HARD STOP — human review

CLI 成功后 **stop**。AskQuestion：`approve` / `reject` / `suggest`。  
`approve` → 立刻 `tg-solve`（同一 `project_root` / `--op-name` / `--level`）。

## Notes

- 产物在 `<算子仓>/.testcase-generator/<op>/`，不在测试工具目录下。
- 不要修改 `.understand-operator/`。
