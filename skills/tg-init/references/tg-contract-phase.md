# Thin contract 阶段（内嵌于 `/tg-init` Phase 1）

确定性 AST 扫描测试工具，**不算子语义**。用户勿单独依赖 `/tg-contract`。

## 脚本职责

- 发现 CSV 列、`VAR_CSV_*`、consumer evidence
- 写 `realization/binding_inventory.yaml`、`consumer_*.yaml`、脚手架 `realization_map` / 弱 lexicon
- 列出 `unresolved.yaml` gaps（`needs_binding_keys` 等）

## MUST NOT（本阶段）

- 发明算子语义 / 硬编码第二套算子表
- 调用 Z3 或生成 CSV 行
- 把 medium/low 标成 resolved

## 下一步

gaps → `/tg-init` Phase 2+（uo-query Tasks + merge）。  
兼容 CLI：`tg-contract`（内部；主路径仍是 `tg-init`）。
