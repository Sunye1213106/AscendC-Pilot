# 绑定 harness

只 Edit 引擎已写出的 `parts/harness.yaml` 语义格。不要新建空白 YAML，不要改 `schema`、`run_id`、`artifact_identity`、mode candidates。

本路回答：现有 runner 怎么跑、怎么比、精度/性能入口在哪、现在造得出什么。

## 输入 / 输出 / 停

读：`repo_scan.yaml`。`kind=script_repo` 才读测试仓；`kind=default_input` 把缺口写进 findings。点了仓却扫不到目录 → 本切片失败，不是改写成 default_input。

**完成判据：** receipt 的 entry/case_arg/modes.candidates/表清单，加上三处源码窗（compare 函数、golden 产生/加载、`--pta_mode` 默认）。`generate_inputs` 只根据这三处 + receipt 作答。草稿 `call` 已按 `repo_scan.canonical_call` 预填；对照 `--pta_mode` 窗口确认 `kind` / `api` / `site`。

完成：口径来自脚本事实。`pilot_cli inspect yaml --rel <草稿相对 .ascendc-pilot 的路径>` 返回 ok 再停。

## 步骤

一次并行打开三处源码窗（compare 函数、golden 产生/加载、`--pta_mode` 默认），加上 receipt。

1. **认入口。** `entry` / `case_arg` 抄草稿与 receipt。包相对 import 的模块不是可执行入口。把 `modes.candidates` 分成精度 / 性能。表是否可读看 receipt `tables[].error`，不要凭后缀判失败。
2. **写 golden。** match / mismatch / 缺口分开。Disable / 预期报错行不上精度 oracle。`--golden-only`（help 写不调 pta / 无需 NPU）是造数，不是精度；记 `golden_only_is_not_precision`。
3. **写 compare。** 脚本真实怎么比。`compare.how` 必须出现 compare 函数体里**每一个**写成字面量的数字（比率、地板、失败门槛都算），并记 `threshold_in_function_not_argparse`。argparse 没有的 `atol`/`rtol` 填 `absent`。Host replay 不是本路精度 oracle。
4. **写 `modes.precision` / `modes.perf`。** 默认值若是性能 mode，记 `findings.code: default_mode_is_perf`。记下 `call.kind`（pta / aclnn / mixed），并记 `call_kind_pta`（或对应 kind）。
5. **写 `generate_inputs`。** 造得出什么、造不出什么。至少核对这些轴：空 tensor、标量 tensor、inf / -inf / nan、上/下边界、末维对齐 vs +1、合法 vs 非法 range。
6. **参数依赖。** 生成器做不到 → `test_harness_gap`。记进 findings，不要当成两列独立可填。

窗口里看到的稳定事实用这些 `findings.code`：`default_mode_is_perf`、`golden_only_is_not_precision`、`threshold_in_function_not_argparse`、`call_kind_pta`、`deterministic_mode`（checksum / `.bin` / md5 写进该条 detail）。

## 常驻判断

正式产物只有将来的 `init.yaml`。缺列或缺 `generate_inputs` → `test_harness_gap`，由 `/ce-apply` 改测试脚本仓。无仓时写明没有 compare / 没有精度入口，不要编 argparse。

## 看到这样

| 现象 | 判断 |
| --- | --- |
| argparse 同时有精度和性能 mode | 分别写入 `modes.precision` / `modes.perf` |
| 默认值是性能 mode | 不得把默认当精度 |
| help 写「不调 pta / 无需 NPU」 | 造数，不是精度 |
| 阈值在函数里不在 flag 上 | 写进 compare，不要编 argparse |
| runner 造不出空 tensor / inf / 对齐+1 | 标 `generate_inputs` 缺口 |
| receipt 表没有 error | 不要写读失败 |
| 无仓 | 写缺口，不要假入口 |

## 完成勾选

- [ ] golden / compare / modes / generate_inputs / call.kind / findings 都有着落（无仓则明确缺失）
- [ ] 精度口径能指到 flag 或函数，没有编 atol/rtol
- [ ] 特殊值没有假装已覆盖
- [ ] 没有写 mapping，没有读 bind.yaml
- [ ] `inspect yaml` 返回 ok

## 输出形状

```yaml
call: {kind: pta, api: torch_npu.<fn>, site: path.py:LINE}
golden: {match: ..., mismatch: ..., gaps: ...}
compare: {how: ..., atol_rtol: absent}
modes:
  precision: {flag: --pta_mode, value: <precision>}
  perf: {flag: --pta_mode, value: <perf>}
generate_inputs:
  can: [...]
  cannot:
    empty_tensor: ...
    scalar: ...
    inf_nan: ...
    align_plus_1: ...
    illegal_range: ...
findings:
  - {code: default_mode_is_perf, detail: ...}
```
