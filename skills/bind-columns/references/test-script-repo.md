# 脚本仓（列这一路）

**何时加载**：写 `parts/bind.yaml`、确认脚本怎么读列时。

脚本仓是已有 runner（脚本 + csv/xls/xlsx），不是第二份 CodeMap。本路只确认**列怎么被读**，不写 golden / compare / modes。

## 读什么

1. 打开入口，确认每一列的脚本读点。脚本没读的列不要硬 mapping。
2. 值域用 scan 的 `tables[].profile`，禁止通读 CSV 正文。
3. 多张 csv/xls 以 `tables[]` 为准；用户没点名的表不当本次目标。扫描含 xls/xlsx。

## 规则

- 有仓却 mapping 空 → 本切片失败。
- 不要把某一个算子的列名写进引擎。
- 不要发明 CSV 列名。无仓时列来自 Host API。
- 点了脚本仓却扫不到目录 → 失败，不是改写成 default_input。
