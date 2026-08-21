# 确定性 Band 调度

## 实现分析

跨层真值来自 uo-query（标识符 `deterBandScheduleMode`），不是 host_view 扫 writer。

- Host 写入：`op_host/arch35/flash_attention_score_grad_tiling_normal_regbase.cpp` `SaveToTilingData` 约 2103 行，把 `fBaseParams.deterBandScheduleMode` 写入 TilingData。
- Kernel 读取：`op_kernel/arch35/flash_attention_score_grad_kernel_deter.h` 的 `CalBandDeterIndex`、`CalDeterMaxLoopNum`。
- 同批字段：`s1SinkOuter` / `s2SinkOuter` / `sinkOptional` / `enableSwizzle` / `isSplitByBlockIdx`。
- 变更文件（10）：
  - host tiling common/normal 的 cpp+h
  - kernel `deter.h`、`flash_attention_score_grad_block_cube.h`、`flash_attention_score_grad_block_vec.h`、`flash_attention_score_grad_kernel_deter.h`、`flash_attention_score_grad_tiling_data_regbase.h`
  - 生成头 `flash_attention_score_grad_template_tiling_key.h`（角色 tilingkey，不要按大 hunk 当语义切片）
- 不要当成这次影响面：`S1TemplateNum` / `DeterType` 等 host_view 误报维。

不改：arch22、op_api、varlen tiling、无关 vector_api。

## 计划

1. Host：在 `FuzzyBaseInfoParamsRegbase` 与 normal tiling 路径计算并下发 `deterBandScheduleMode` 与 sink 相关字段。
2. TilingData：`flash_attention_score_grad_tiling_data_regbase.h` 增加字段与 getter/setter，保持与 host 写入一致。
3. Kernel：`deter.h` / `kernel_deter.h` 按新调度模式计算 band 与 max loop；cube/vec 仅吃到的字段做最小改动。
4. 生成 tiling key 头随模板覆盖更新，不手改语义。

## Todo

- [ ] Host common/normal：参数、SaveToTilingData 写入 deterBand/sink
- [ ] TilingData 头：字段与 set/get
- [ ] Kernel deter 调度：CalBandDeterIndex / CalDeterMaxLoopNum
- [ ] cube/vec 若读取新字段则对齐，否则不扩范围

## 测试内容

- 应覆盖字段：`deterBandScheduleMode`、`s1SinkOuter`、`s2SinkOuter`、`sinkOptional`
- 需要覆盖：确定性 on/off、band 调度启用 vs DISABLED、sink 有无
- 不要扩成全量 TilingKey，不要按误报的 Template 维（`S1TemplateNum`）铺用例
- 进入 /tg-plan 后由 TG 自己把以上内容总结进 tg/plan.md 义务表，root 到测试脚本列
