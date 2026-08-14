# Precision scenarios (construct knobs)

**When to load**：已经有合法 `P-*` id，要构造少量 CSV。id 以 CE `scenario-catalog.md` 为准，不要在此再定义何时挂上。

## Knobs

- **P-DTYPE / P-CAST**：受影响 dtype，同 shape；先 FP32 再 FP16/BF16
- **P-COPY-ALIGN**：末维 32B 对齐 vs +1
- **P-QUEUE**：最小可复现 shape
- **P-REDUCE-LONG**：大 reduce 轴，干净数值
- **P-OPTIONAL**：有/无可选输入，只走合法 shape
- **P-ILLEGAL**：Disable 或排除；**不上 NPU**
- **P-TAIL**：`[1]`、零轴；empty ≠ scalar

## Clean vs stress

- **clean**（normal / zero / near_zero / all_ones）：必过门
- **stress**（big / neg_big / denormal）：信息性，不得当唯一硬门

Oracle 是 harness 精度比对（`only_grad`）。Host 命中 TilingKey 关不了 `P-*`。
