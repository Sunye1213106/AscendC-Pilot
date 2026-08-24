# Harness 边角

**何时加载**：写 golden / compare / modes / `generate_inputs` 对不上脚本事实时。

## 入口与表

`entry` / `case_arg` / 表清单抄 receipt 与草稿。receipt 里某表没有 `error` 就不要写读失败。findings 按 `code`+`column` 去重。

确定性路径若落盘 checksum / `.bin`，写进 `deterministic_mode` 或 `result_writeback` 的 detail。

## golden / compare / modes

Disable / 预期报错行不上精度 oracle。`--golden-only` 是造数。阈值在函数里就写进 compare，不要编 `--atol`/`--rtol`。默认值是性能 mode 时不得把默认当精度。

## 依赖

reduce 轴必须落在 rank 内。生成器做不到 → `test_harness_gap`。
