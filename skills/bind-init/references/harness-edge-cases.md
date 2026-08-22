# Harness 边角

**何时加载**：写 golden / compare / modes / `generate_inputs` 对不上脚本事实时。

## golden

match / mismatch / 缺口分开。设计文件里带预期报错或 Disable 的行不上精度 oracle。`--golden-only`（help 写不调用 pta / 无需 NPU）是造数，不是精度。

## compare

脚本真实怎么比：函数里的阈值写进 compare；argparse 没有的 `atol`/`rtol` 不要编。Host Replay 只关 dispatch / key，不是本路的精度 oracle。

## modes

argparse 同时有精度和性能 mode 就分别写入 `modes.precision` / `modes.perf`。默认值若是性能 mode，不得把默认当精度。设计文件分开写了精度标准与性能标准，照抄事实，不要发明阈值。

## generate_inputs

脚本现在造得出什么、造不出什么。至少核对这些轴（runner 吃不了的标缺口）：空 tensor、标量 tensor、inf / -inf / nan、上/下边界、末维对齐 vs +1、合法 range vs 非法 range。常规 dtype 覆盖和这些特殊值分开计，不要铺进每一组 shape。

## 依赖

reduce 轴必须落在 rank 内；shape 与模板切块尺寸列同理。依赖用 `control.recipe` 从可控列复算；生成器做不到 → `test_harness_gap`。
