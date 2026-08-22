# 绑定 harness

只写 `parts/harness.yaml`。本路回答「现有 runner 怎么跑、怎么比、精度/性能入口在哪、现在造得出什么」。本路写完应能单独回答：现有 runner 能否执行计划稍后会点名的精度/性能义务。

引擎不懂 runner。要打开入口脚本和 argparse，仓内若有用例设计 YAML（接口、dtype、range、精度/性能标准）一并打开。

## 输入 / 输出 / 停

读：`repo_scan.yaml`。`kind=script_repo` 才读测试仓；`kind=default_input` 把缺口写进 findings，写明没有脚本路径。

点了脚本仓却扫不到目录 → 本切片失败，不是改写成 default_input。

完成：一份自洽的 harness 草稿，口径来自脚本事实。本路交卷即停。

## 步骤

1. **打开入口。** 常见 `run_*.py`。确认 `--case` 或等价选行方式；哪些 flag 是精度、哪些是性能。扫描含 xls/xlsx，只认 csv 会漏真实跑测表。用户没点名的表不当本次目标。
2. **写 golden。** match / mismatch / 缺口分开。设计文件里带预期报错或 Disable 的行不上精度 oracle。`--golden-only`（help 写不调用 pta / 无需 NPU）是造数，不是精度。
3. **写 compare。** 脚本真实怎么比：函数里的阈值写进 compare；argparse 没有的 `atol`/`rtol` 不要编。Host replay 只关 dispatch / key，不是本路的精度 oracle。
4. **写 `modes.precision` / `modes.perf`。** argparse 同时有两种 mode 就分别写。默认值若是性能 mode，不得把默认当精度。设计文件分开写了精度标准与性能标准，照抄事实，不要发明阈值。怎么跑只抄当前脚本与 `tg/init.yaml` 将要记录的事实。在 golden/modes 之外记下同一 `call.kind`（pta / aclnn / mixed）。
5. **写 `generate_inputs` 缺口。** 脚本现在造得出什么、造不出什么。至少核对这些轴（runner 吃不了的标缺口，不要假装已覆盖）：空 tensor、标量 tensor、inf / -inf / nan、上/下边界、末维对齐 vs +1、合法 range vs 非法 range。常规 dtype 覆盖和这些特殊值分开计，不要铺进每一组 shape。
6. **参数依赖。** reduce 轴必须落在 rank 内，shape 列与 `*TemplateNum` / `dim_*` 同理。依赖用 `control.recipe` 从可控列复算；生成器做不到 → `test_harness_gap`。记进 findings，不要当成两列独立可填。

## 常驻判断

正式产物只有将来的 `init.yaml`。不要再写 inventory / audit / fingerprint / contract YAML。

不要把某一个测试框架的设计字段名写进引擎或草稿 schema。runner 吃 CSV/XLS 就填表；runner 吃 JSON/设计文件就按它的入口写 `entry` / `case_arg`。

缺列或缺 `generate_inputs` → `test_harness_gap`，由 `/ce-apply` 改测试脚本仓，不要在本步改算子仓。查语义优先查图；Grep 只作定位辅助。

无仓时：写明没有 compare / 没有精度入口，不要抄一份假 argparse。

## 看到这样

| 现象 | 判断 |
| --- | --- |
| argparse 同时有精度和性能 mode | 分别写入 `modes.precision` / `modes.perf` |
| 默认值是性能 mode | 不得把默认当精度 |
| help 写「不调 pta / 无需 NPU」 | 造数，不是精度 |
| 阈值在函数里不在 flag 上 | 写进 compare，不要编 argparse |
| 设计 YAML 有精度标准 | 照抄，不要发明 |
| runner 造不出空 tensor / inf / 对齐+1 | 标 `generate_inputs` 缺口 |
| 无仓 | 写缺口，不要假入口 |

## 完成勾选

- [ ] golden / compare / modes / generate_inputs / call.kind / findings 都有着落（无仓则明确缺失）
- [ ] 精度口径能在脚本里指到 flag 或函数，没有编 atol/rtol
- [ ] 特殊值没有假装已覆盖
- [ ] 没有写 mapping，没有读 bind.yaml

## 循环

1. 打开 scan 指出的入口与 argparse，设计 YAML 一并打开。
2. 先写怎么选 case、怎么比、精度/性能分别怎么跑。写不出就标缺口，不要抄别的算子。
3. 再写 `generate_inputs`：造得出的列清单，造不出的轴（空 tensor、inf、对齐+1、非法 range…）。
4. 对照脚本核对默认 mode 是不是性能；是则不要标成精度。
5. 停。本路只交 harness 草稿。

输出是一份草稿 YAML：`golden`、`compare`、`modes`、`generate_inputs`、`findings`。无仓时前三项可以是明确缺失，不能是编造入口。

## 输出形状

```yaml
golden: {match: ..., mismatch: ..., gaps: ...}
compare: {how: ..., atol_rtol: script-or-absent}
modes:
  precision: {flag: ..., not_golden_only: true}
  perf: {flag: ...}
generate_inputs:
  can: [...]
  cannot: [empty_tensor, inf_nan, align_plus_1, illegal_range, ...]
findings: [...]
```

无仓时 `modes` / `compare` 写明缺失。不要编 argparse。
