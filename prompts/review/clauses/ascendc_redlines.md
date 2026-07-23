# Ascend C 精简条例（审查用）

完整规范见本机 `ascendc-code-review` skill；此处只保留审查热路径红线。

## ASCENDC-SAFE-01 缓冲区与越界

- Kernel 侧 DataCopy / LocalTensor 访问必须有明确长度与对齐约束
- 变更若触及 shape/tiling 计算，必须核对对应 UB/L1 分配是否仍覆盖

## ASCENDC-API-02 API 约束

- Ascend C API 参数类型/枚举与头文件一致；禁止凭猜测传魔法数
- 同步 API（PipeBarrier / SetFlag / WaitFlag）配对完整

## ASCENDC-SYNC-03 流水同步

- MTE / Vector / Cube 流水依赖变更时，检查 flag 与 wait 是否遗漏
- 多核/多 block 共享缓冲需明确 ownership

## ASCENDC-TILING-04 Tiling 一致性

- Host tiling 写入字段与 Kernel 读取布局一致
- key 空间/分支变更需同步约束与默认路径

## ASCENDC-PREC-05 精度与类型

- 累加/归一化路径 dtype 提升有依据
- 半精度路径注意溢出与舍入

## 使用规则

- 只对变更相关侧别启用条例
- 无证据不报；红线可疑但证据不足标 severity=info 并写明缺口
