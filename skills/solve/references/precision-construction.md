# 精度构造旋钮

已经有合法 `P-*` id 之后才读。本步不重新判断该不该挂场景，只把已批准 id 落成列。

怎么跑精度、atol/rtol、golden 以当前仓 `tg/init.yaml` 为准，不要编 argparse 没有的阈值。

## 旋钮

- **P-DTYPE / P-CAST**：受影响 dtype，同 shape；先 FP32 再 FP16/BF16
- **P-COPY-ALIGN**：末维 32B 对齐 vs +1
- **P-QUEUE**：最小可复现 shape
- **P-REDUCE-LONG**：大 reduce 轴，干净数值
- **P-OPTIONAL**：有/无可选输入，只走合法 shape
- **P-ILLEGAL**：Disable 或排除；**不上 NPU**
- **P-TAIL**：`[1]`、零轴；empty ≠ scalar

## clean 与 stress

- **clean**（normal / zero / near_zero / all_ones）：必过门
- **stress**（big / neg_big / denormal）：信息性，不得当唯一硬门

Oracle 是 harness 精度 mode，不是 Host TilingKey HIT。Host 命中 TilingKey 关不了 `P-*`。
