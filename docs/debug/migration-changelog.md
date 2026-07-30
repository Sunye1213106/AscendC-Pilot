# 单引擎迁移 changelog

- 删除 `engines/understand-operator-old`、`engines/codebase-memory-mcp`
- `uo-update` → `uo_init.update`；`uo-query` / `uo-scope` / CBM client 迁入 Pilot + `uo_init`
- 安装 / doctor 只认 `pip install -e ./engines/understand-operator`（`uo_init`）
- 废弃 uo-init Action（extract-plan、detect-score-*、semantic patch 链等）与对应 prompts
- 文档四夹：`design` / `workflows` / `fag` / `debug`
