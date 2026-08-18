# TG construct-cases

按已批准 `plan.md` 构造脚本仓能直接吃的用例行。正式表由 `construct_promote` 写出。

## 方法

1. 读 `init.yaml` 列与 `plan.md` YAML 义务。
2. 每个义务填控制列取值；其余列用 defaults。
3. 行名写入 `Testcase_Name`（若该列存在）。
4. 不要改算子仓。

## 禁止

- 写正式 `tg/cases.csv` / `xls`
- 发明 init.yaml 没有的列（除非 plan `added_columns` 且已 CE 落地）
