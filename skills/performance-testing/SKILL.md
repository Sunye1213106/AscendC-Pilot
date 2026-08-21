---
name: performance-testing
description: 规划或构造性能义务。意图含性能/profiling，或 init.yaml 暴露 modes.perf 时使用。
---

# 性能测试

没有可执行性能入口就写 gap，不发明 NPU 指标。Oracle 是 harness profiler。Host HIT 不能关闭 `F-*`。关 `V` 仍要 profiling 收据。本步是叠加原语：plan 或 construct 碰到性能意图时才读。

默认 argparse 若是性能 mode，那是「默认跑性能」，仍要有 `modes.perf` 入口；不要把默认性能当成精度，也不要反过来用精度 golden 关性能义务。

## 输入 / 输出 / 停

读：`init.yaml` 的 `modes.perf`、切分 / Buffer / dtype 相关意图。没有 `modes.perf` → 缺口，停。

完成：每条性能义务有脚本入口。

## 步骤

1. **确认入口。** 写出怎么跑 profiler、脚本吃哪一列选 case。没有入口不要编 msprof 字段。
2. **基线 shape。** 挂上任一性能场景时带上 `F-SHAPE-TYPICAL`（网络常用 shape）。切片里有 tail / 切不整再加 `F-SHAPE-TAIL`。
3. **按结构加少量 `F-*`。** id 以 `references/scenario-catalog.md` 为准。旋钮见 `references/perf-scenarios.md`。
   - 切分字段 / 核数 → `F-SPLIT`、`F-BALANCE`
   - Buffer / 队列方向 → `F-BUFFER`
   - 计算 dtype 路径 → `F-DTYPE`
4. **预算 3–8 条。** 禁止枚举全部 legal key。不要把性能义务铺成全量 tilingkey 矩阵。
5. **root 到列。** 每条义务落到 init 可控列。root 不到 → `untestable`。生成器造不出切不整形 → `test_harness_gap`。

## 常驻判断

性能不是 Host Replay。Replay 无 NPU，只看 tiling key / TD / 分支；它关不了 `F-*`。

`--golden-only` 不是性能。预期报错 / Disable 行不上 profiler。

缺测试仓或 runner 时性能保持 Open（`harness_missing`）。Crash / not-run 是环境，不是「核占不满」的证明。

全量 tilingkey 只在计划意图点名时做，不是本原语默认。禁止默认 T=D。

## 看到这样

| 现象 | 判断 |
| --- | --- |
| 没有 `modes.perf` | 缺口，停 |
| 挂了任一 `F-*` | 必须带 `F-SHAPE-TYPICAL` |
| 切不整 / tail | 再加 `F-SHAPE-TAIL` |
| 切分字段变了 | `F-SPLIT` |
| 核数 / usedCoreNum | `F-BALANCE` |
| Buffer / 队列 | `F-BUFFER` |
| Host HIT / 关 V | 仍要 profiler 收据 |
| 想枚举全部 legal key | 禁止；3–8 条 |

## 完成勾选

- [ ] 每条性能义务有脚本入口
- [ ] 基线 typical 已带；需要才加 tail
- [ ] 没有发明 NPU 指标
- [ ] 没有用 Host HIT 关 `F-*`

## 循环

1. 确认 `modes.perf`。没有就 gap。
2. 先挂 `F-SHAPE-TYPICAL`。有 tail 再挂 `F-SHAPE-TAIL`。
3. 按切分 / Buffer / dtype / 核数加少量 `F-*`，预算 3–8。
4. 每条 root 到列，写 profiler 入口。
5. 停。不要用 Host HIT 勾掉性能义务。

## 输出形状

每条义务：`F-*` id、root 列、profiler 入口。集合里必须有 `F-SHAPE-TYPICAL`（有性能场景时）。总数 3–8，不要全量 Key。

## 反模式

- 没有 `modes.perf` 却发明 NPU 指标
- 漏掉 `F-SHAPE-TYPICAL`
- 用 Host HIT 或关 V 代替 profiler 收据
- 枚举全部 legal key
- `--golden-only` / Disable 行当性能 case

## 指针

场景 id 与预算：`references/scenario-catalog.md`。选 case 看什么：`references/perf-scenarios.md`。
