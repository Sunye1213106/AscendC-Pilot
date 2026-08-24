# 脚本仓

**何时加载**：确认现有 runner 是否存在、入口在哪、表从哪来时。

脚本仓是已有 runner（脚本 + csv/xls/xlsx），不是第二份 CodeMap。

## 必须打开

1. `kind=script_repo` 才读测试仓；`kind=default_input` 不要假装已有仓。
2. 点了脚本仓却扫不到目录 → 本切片失败，不是改写成 default_input。
3. 扫描含 xls/xlsx；用户没点名的表不当本次目标。表能不能读看 receipt `tables[].error`，不要凭后缀判。
4. `entry` / `case_arg` 抄 receipt 与草稿。能 `python <entry>` 直接跑的才是入口；包相对 import 的模块即使写了 argparse 也不是可执行入口。
5. 不要把某一个测试框架的设计字段名写进引擎。runner 吃 CSV/XLS 就填表；吃 JSON/设计文件就按它的入口写 `entry` / `case_arg`。

本文件只确认仓还在、入口能打开。本轴要写进草稿的字段，以当前轴 playbook 为准。
