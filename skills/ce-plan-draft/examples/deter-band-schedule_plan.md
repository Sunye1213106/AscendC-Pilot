# arch35 FAG 确定性 Band 调度与 Swizzle

## 实现分析

**当前行为。** arch35 确定性 Band 路径已在。schedule 由 Kernel 根据 S1/S2、sink、Swizzle 等字段猜测。

**目标行为。** Host 形成唯一调度真值，经 TilingData 下发；Kernel 只消费。未命中新调度写 `DISABLED`（合法 default，走修改前 Band 算法）。跨层可观察：有效 logical block 恰好一次；同一 physical block 上 Cube / Vector 身份一致；`DISABLED` 下 index 与改前一致。

```text
Host Band 决策
  → deterBandScheduleMode + sink 参数
  → TilingData
  → CalBandDeterIndex / CalDeterMaxLoopNum
  → Cube / Vector block
```

**侧别：** `mixed`。**依赖：** 先建立 Host / TilingData 合同，再改 Kernel 读者。

**文件与符号**

- Host：`op_host/arch35/flash_attention_score_grad_tiling_normal_regbase.h`、`op_host/arch35/flash_attention_score_grad_tiling_normal_regbase.cpp` — 确定性参数 / Band 计算 / `SaveToTilingData`
- 合同：`op_kernel/arch35/flash_attention_score_grad_tiling_data_regbase.h`
- Kernel：`op_kernel/arch35/deter.h`、`op_kernel/arch35/flash_attention_score_grad_kernel_deter.h` — `CalBandDeterIndex`、`CalDeterMaxLoopNum`
- 消费：`op_kernel/arch35/flash_attention_score_grad_block_cube.h`、`op_kernel/arch35/flash_attention_score_grad_block_vec.h`

下发字段：`deterBandScheduleMode`、`s1SinkOuter`、`s2SinkOuter`、`sinkOptional`。与已有 `enableSwizzle`、`isSplitByBlockIdx` 同一组最终 gate。`s1SinkOuter` / `s2SinkOuter` 是最终 outer 切分。

**不做的范围：** arch22、op_api、varlen 独立 tiling、非 arch35 normal-regbase、与 Band 调度无数据依赖的 vector API、仅因命名或大 diff 被带出的维（如 `S1TemplateNum` / `DeterType`）。`flash_attention_score_grad_template_tiling_key.h` 只随模板生成同步。

**UNRESOLVED。** 非 `DISABLED` 的具体 enum 取值。推荐：`/tg-plan` 从实际定义读取。影响测试枚举，不改变本次文件集。

## 分步计划

1. Host 在已进入确定性 Band 的路径上算出 mode + sink，`SaveToTilingData` 统一下发；未命中则显式 `DISABLED`；与 `enableSwizzle` / `isSplitByBlockIdx` 不互相矛盾。原有 `s1Outer` / `s2Outer` / `blockOuter` 语义不变。
2. TilingData 增加字段与访问接口。类型 / default / `DISABLED` 语义与 Host 写入、Kernel 读取一致。TilingData 不判断调度。
3. `CalBandDeterIndex`：`DISABLED` → 原算法；有效新模式 → sink-aware / swizzle 算法。至少核首 band、中间完整 band、最后完整 / 非完整 band、S1 sink 尾、S2 sink 尾。
4. `CalDeterMaxLoopNum` 与 index 消费同一组 `deterBandScheduleMode` / `s1SinkOuter` / `s2SinkOuter`。maxLoop 覆盖全部有效 block，不因 sink padding 扩大有效计算域。
5. Cube / Vector 消费 deter 层 mapping。只透传现有 index 时做最小接口调整，不把 schedule 再下沉一层。

## Todo

- [ ] 在 `op_host/arch35/flash_attention_score_grad_tiling_normal_regbase.h`、`op_host/arch35/flash_attention_score_grad_tiling_normal_regbase.cpp` 中形成并 `SaveToTilingData` 下发 `deterBandScheduleMode`、`s1SinkOuter`、`s2SinkOuter`、`sinkOptional`；未命中显式 `DISABLED`
- [ ] 在 `op_kernel/arch35/flash_attention_score_grad_tiling_data_regbase.h` 中建立上述字段的 Host→Kernel 合同（字段 + 访问接口；类型 / default / `DISABLED` 与 Host 一致）
- [ ] 在 `op_kernel/arch35/deter.h`、`op_kernel/arch35/flash_attention_score_grad_kernel_deter.h` 中按 mode 改 `CalBandDeterIndex`；有效 logical block 恰好一次；`DISABLED` 保持旧算法
- [ ] 在 `op_kernel/arch35/deter.h`、`op_kernel/arch35/flash_attention_score_grad_kernel_deter.h` 中让 `CalDeterMaxLoopNum` 与 index 使用同一 schedule/sink 合同
- [ ] 在 `op_kernel/arch35/flash_attention_score_grad_block_cube.h`、`op_kernel/arch35/flash_attention_score_grad_block_vec.h` 中统一消费 deter 层 logical block，不各自重算 schedule

## 测试内容

给 `/tg-plan` 的控制变量、边界与预期行为。覆盖轴 = 实际控制本次 schedule 的字段；按可达与互斥裁 case。

- **dispatch / 入口。** `isDeterministic=false` 走旧路径。`true` 再判 deter 类型：正向 `DETER_BAND`；`NO_DETER` / `DETER_DENSE` / `DETER_CAUSAL` 作旧路径回归。
- **coverage / mode。** `DISABLED` 为旧算法基准。每个实际定义的非 `DISABLED` mode 下，`CalBandDeterIndex`、`CalDeterMaxLoopNum`、logical mapping 进入新调度。enum 从定义读。
- **shape / sink。** `sinkOptional` 有/无；`s1SinkOuter` / `s2SinkOuter` 取 0 / 1 / >1。至少 `(0,0)`、`(s1>0,s2=0)`、`(s1=0,s2>0)`；双侧合法再加 `(s1>0,s2>0)`。index 与 maxLoop 响应同一 sink 状态。
- **shape / 已有 split。** `cubeBaseM` 与 `cubeBaseN` 的 = / > / <。`s1Inner` / `s2Inner` / `s1Outer` / `s2Outer` 保持原语义。
- **dispatch / Swizzle gate。** `enableSwizzle`、`isSplitByBlockIdx` 正反。正向至少：`g=1`、`B*N2` 为偶、`S1 >= aicNum*128`、`sparseMode=RIGHT_DOWN_CAUSAL`。每次只翻一个条件，回落到旧路径。
- **dispatch / S1 阈值。** `aicNum*128` 的 -1 / = / +1。
- **coverage / 尾 band。** 最后 band 完整 / 不完整 / 只剩 1 个有效 block / S1 sink 尾 / S2 sink 尾。有效 block 恰好一次；sink 无效区不进入计算；maxLoop 覆盖全部有效 block，计算域止于有效区。
- **precision / 回归。** 非确定性、`DETER_DENSE`、`DETER_CAUSAL`、`DETER_BAND` + `DISABLED`、`enableSwizzle=false`：tiling 参数、block mapping、`dQ`/`dK`/`dV` 精度与确定性重复执行保持改前行为。
- **contract / 跨层。** Host / TilingData 字段与输入条件一致；同一 physical block 上 Cube / Vector 身份一致。
