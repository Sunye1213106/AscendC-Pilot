# 脚本仓（harness 这一路）

**何时加载**：写 `parts/harness.yaml`、确认现有 runner 怎么跑时。

脚本仓是已有 runner，不是第二份 CodeMap。本路只回答怎么跑、怎么比、精度/性能入口在哪、现在造得出什么。不要写列 mapping。

## 必须打开

1. 入口脚本和 argparse（常见 `run_*.py`）。确认 `--case` 或等价选行；哪些 flag 是精度、哪些是性能。
2. 仓内若有用例设计 YAML（接口、dtype、range、精度/性能标准），一并打开。
3. `kind=script_repo` 才读测试仓；`kind=default_input` 不要假装已有仓。

## 规则

- 点了脚本仓却扫不到目录 → 本切片失败，不是改写成 default_input。
- 不要把某一个测试框架的设计字段名写进引擎。runner 吃 CSV/XLS 就填表；吃 JSON/设计文件就按它的入口写 `entry` / `case_arg`。
- 无仓时写明没有 compare / 没有精度入口，不要编 argparse。
