# 单引擎迁移 changelog

- 删除 `engines/understand-operator-old`、`engines/codebase-memory-mcp`
- `uo-update` → `uo_init.update`；`uo-query` / `uo-scope` / CBM client 迁入 Pilot + `uo_init`
- 安装 / doctor 只认 `pip install -e ./engines/understand-operator`（`uo_init`）
- 废弃 uo-init Action（extract-plan、detect-score-*、semantic patch 链等）与对应 prompts
- 文档四夹：`design` / `workflows` / `fag` / `debug`

## 新增 `engines/common`（2026-07-30）

- 新引擎 `acp_common`：`constraint_ir`（通用子集）+ `z3_backend`（编译/求解核心，另加 `prove_implies` / `prove_equivalent`）
- TG 的 `constraint_ir.py` / `z3_backend.py` 改为薄封装与子类；TG 专有的 obligation 模型留在 TG，两处变量名前缀约定改为类属性而非字面量
- 动机：UO 判 key 可达性必须与 TG 实现输入用**同一套语义**，否则一边「证明可达」的 key 另一边可能造不出来
- 安装：`pip install -e ./engines/common`（已加入 `install.ps1` / `install.sh` / `requirements.txt`，并列入两个引擎的依赖）
