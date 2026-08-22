# 精度邻域取值

**何时加载**：`plan.md` 的 `oracle` 已点精度，并且该变量已经 `TARGET_HIT`。本步不决定测哪些变量，只给命中后的取值邻域。

怎么跑、atol/rtol、golden 以当前仓 `tg/init.yaml` 为准。

## 邻域

- dtype：同 shape 换受影响 dtype；先 FP32 再 FP16/BF16
- 末维：32B 对齐 vs +1
- 最小可复现 shape
- 大 reduce 轴，干净数值
- 有 / 无可选输入，只走合法 shape
- Disable / 排除行不上 NPU
- tail：`[1]`、零轴；empty ≠ scalar

## clean 与 stress

- **clean**（normal / zero / near_zero / all_ones）：必过门
- **stress**（big / neg_big / denormal）：信息性，不得当唯一硬门

Oracle 是 harness 精度 mode。Host TilingKey `HIT` 不是精度 PASS。
