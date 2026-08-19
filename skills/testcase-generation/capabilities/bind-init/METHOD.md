# TG bind-init

写出 **一份** `init.yaml` 草稿。正式文件由 `bind_promote` 写入。测试脚本仓可选。

## 方法

1. 读 `runs/<run_id>/receipts/repo_scan.yaml`。
2. **有脚本仓**（`kind=script_repo`）：为每一列写 `mapping`（脚本读点如 `get_case` / `CaseConfig.xxx` + 算子仓/UO 标识符）。mapping 空则本步失败。写 `modes`、值域、`golden`、比对口径、`generate_inputs`。
3. **无脚本仓**：不要假装已有仓。用 uo-query 读算子 **输入 API**（Host 入参 / dtype / shape），按 API 设计 `init.yaml` 控制面（列/字段、值域、如何造输入）。`kind=default_input`。缺生成器另走 CE，不要伪造 mapping。算子仓内 `tests/` / `ut` 未经用户确认，不得写成 `kind=script_repo`。
4. `uo_digest` 由 promote 写入；草稿可留空。
5. 查语义：本步只用 `pilot_cli` `uo-query`（禁止再派 Task；子代不得嵌套子代理）。多起点在本步串行查完。禁止 Grep 算子仓。

## 禁止

- 写正式 `tg/init.yaml`
- 把精度启发式标成 `--golden-only`
- 无 mapping 却声称 script_repo 已绑定
- 无仓时假装脚本仓已就绪
