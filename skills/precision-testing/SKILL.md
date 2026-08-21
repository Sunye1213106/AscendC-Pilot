---
name: precision-testing
description: 规划或构造精度义务。意图含精度、golden、atol/rtol、P-*，或 init.yaml 有 modes.precision 时使用。
---

# 精度测试

口径来自脚本事实，不是 Host TilingKey HIT。本步是叠加原语：plan 里出现精度义务、或 construct 要落 `P-*` 行时才读。不要发明 argparse 没有的阈值，不要把性能 mode 的默认值当成精度。

Oracle 是 harness 精度 mode。Host 命中 TilingKey 关不了 `P-*`。

## 输入 / 输出 / 停

读：`init.yaml` 的 compare / golden / `modes.precision`、计划里的精度意图。没有可执行精度入口 → 写 gap，停，不要编 atol/rtol，不要发明 NPU 指标。

`--golden-only`（不调 pta / 无需 NPU）是造数，不是精度。预期报错 / Disable 行不上精度 oracle，也不要写成 Host HIT 失败。

完成：每条精度义务有列、有 mode、有可执行入口。

## 步骤

1. **抄脚本怎么跑、怎么判。** 从 compare / golden / `modes.precision` 写出入口与判据。阈值在脚本函数里而不是 flag 上时，写进 compare。argparse 没有的不要编。
2. **选少量 `P-*`。** id 以 `references/scenario-catalog.md` 为准，不要自造 id。旋钮见 `references/precision-scenarios.md`。
   - `P-DTYPE` / `P-CAST`：受影响 dtype，同 shape；先 FP32 再 FP16/BF16
   - `P-COPY-ALIGN`：末维 32B 对齐 vs +1
   - `P-QUEUE`：最小可复现 shape
   - `P-REDUCE-LONG`：大 reduce 轴，干净数值
   - `P-OPTIONAL`：有/无可选输入，只走合法 shape
   - `P-ILLEGAL`：Disable 或排除；**不上 NPU**
   - `P-TAIL`：`[1]`、零轴；empty ≠ scalar
3. **clean vs stress。** clean（normal / zero / near_zero / all_ones）是必过门。stress（big / neg_big / denormal）是信息性，不得当唯一硬门。
4. **root 到列。** 每条精度义务必须落到 init 的可控列，写可执行入口。root 不到 → `untestable`，不要进表。缺生成器造不出空 tensor / inf / 对齐+1 → `test_harness_gap`。
5. **不要铺进每一组 shape。** L3 特殊值只挂在异常义务上。常规 dtype 覆盖和特殊值分开计。

## 常驻判断

不要把全部合法 Key 当成精度矩阵。全量 tilingkey 是计划意图，不是本原语默认。

缺测试仓或 runner 时精度保持 Open（`harness_missing`）。Crash / not-run 是环境，不是 golden 失败。

P-ILLEGAL 与预期报错行：不上 NPU，不要用精度失败解释它们。

## 看到这样

| 现象 | 判断 |
| --- | --- |
| 没有 `modes.precision` | gap，停 |
| argparse 无 atol/rtol | 不要编；看 compare 函数 |
| `--golden-only` | 造数，不是精度 |
| Disable / 预期报错 | 不上 NPU，不是精度失败 |
| Host HIT | 关不了 `P-*` |
| 只想用 stress 当门 | 不行；clean 才是必过门 |
| 想铺全量 Key | 禁止；本原语是少量 `P-*` |

## 完成勾选

- [ ] 每条精度义务有列、mode、可执行入口
- [ ] id 来自目录，没有自造
- [ ] clean / illegal / tail 没有混用
- [ ] 没有用 Host HIT 关闭精度

## 循环

1. 从 init 抄精度入口与判据。没有入口就 gap。
2. 按意图选少量 `P-*`，不要自造 id。
3. 每条 root 到列。illegal 不上 NPU。clean 当必过门。
4. 特殊值只挂 L3/对应义务，不铺进每一组 shape。
5. 写可执行入口。停。

## 输出形状

每条义务：`P-*` id（来自目录）、root 到的列、`modes.precision` 入口、clean/stress/illegal 哪一类。illegal 明确不上 NPU。缺入口就写 gap，不要编阈值。

## 反模式

- 编 argparse 没有的 atol/rtol
- `--golden-only` 当精度
- Disable 行上 NPU
- stress 当唯一硬门
- 用 Host HIT 关精度
- 自造场景 id / 铺全量 Key

## 指针

场景 id 与预算：`references/scenario-catalog.md`。构造旋钮：`references/precision-scenarios.md`。
