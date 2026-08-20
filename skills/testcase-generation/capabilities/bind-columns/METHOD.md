# TG bind-columns

只写 **一份** `runs/<run_id>/actions/bind_init/parts/bind.yaml`。正式 `tg/init.yaml` 由 `bind_promote` 写入。查图只用 `pilot_cli` `uo-query`。禁止读另一路的 `harness.yaml`。

本步 refs：`references/test-script-repo.md`、`references/construction-gotchas.md`。

## 方法

1. 读 `runs/<run_id>/receipts/repo_scan.yaml`。有脚本仓则打开入口 / argparse；**列值域以 `tables[].profile` 为准**，禁止为填 domains 去 Read 整份 CSV。无仓则列来自 Host API，不要假装 CSV 已绑定。
2. 写 `table_kind` / `entry` / `case_arg`。runner 的 `--case` 与 validator 的 `--validate` 分开写。
3. 为每一列写 `columns` 与 `mapping`：脚本读点（如 `get_case` / `CaseConfig.xxx`）+ UO 标识符 + Host API。`get_case` 读到的列都要进 mapping（profile 列并集），例如 `is_sink`。有仓却 mapping 空则本步失败。禁止发明列。
4. **domains**：抄 profile，不要通读表。
   - shape 列（`D`/`S1`/`B`）→ profile 的 `inferred_type` + `min`/`max`，写成 range。即使 64/128 出现最多也是 range，禁止把 `*TemplateNum` 合法集写成该列 enum。
   - `dim_*` / TilingKey 维 → 先无参数 `uo-query --project <abs>` 看 `dim_names`，再 `Dim=Name` 或单个标识符拿覆盖列表。表头同时有 shape 列和 `dim_*` 时，`dim_*` 是派生见证，值域来自 `uo-query Dim=`，禁止当独立构造旋钮。
   - `mapping.uo_id` 不要把 TemplateNum 挂到 shape 列；`Layout` 不要挂 `SplitAxis`。
   - 枚举跟 Host 标识符走（`PseType` 0–3，`SparseMode` 含 7/8），不要信脚本注释 `# 0 1`。
5. **findings**：本路事实与缺口（脚本读不到、值域不清、xls 损坏）。禁止把某列标成 PR 焦点或本次测试目标；PR 变更范围留给 `/uo-query` → `/tg-plan`。

查图形态见 code-access 不变量。禁止整句 `--query`。

无仓时 `kind=default_input`，按 API 设计控制面。缺生成器另走 CE。算子仓内 `tests/` / `ut` 未经用户确认，不得写成 `kind=script_repo`。

## 禁止

- 写正式 `tg/init.yaml` 或另一路的 `harness.yaml`
- 发明列、空 mapping、空值域
- 为填 domains 去 Read 整份 CSV / 把 `*TemplateNum` 抄到 shape 列 / 把 `dim_*` 当独立构造旋钮
- 把列或 CSV 标成 `PR#### focus` / 本次测试目标
- 无仓时假装脚本仓已就绪
- 语义不得用仓级 Grep 代替 uo-query（Grep 只作定位辅助）
