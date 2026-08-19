# TG construct-cases

按已批准 `plan.md` 构造脚本仓能直接吃的用例行。正式表由 `construct_promote` 写出。

## 方法

1. 读 `init.yaml` 列与 `plan.md` YAML 义务。
2. 按义务**定向构造**控制列（或已声明代码变量）取值；其余列用 defaults。
3. 行名写入 `Testcase_Name`（若该列存在）。
4. Host 动态回放与引理闭合不在本步改码；本步只出 cases 草稿。不要改算子仓。

## 禁止

- 写正式 `tg/cases.csv` / `xls`
- 发明 init.yaml 没有的列（除非 plan `added_columns` 且已 CE 落地）
