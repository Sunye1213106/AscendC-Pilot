# 识别白盒目标与候选覆盖轴

把用户测试要求编译成 Target、Guard、candidate Dimension。不写 partition、不写 L0–L3、不造 case、**不写磁盘**。最终消息交回 YAML。

## 输入 / 输出 / 停

读：`tg/init.yaml`、改动包、对话 / `--intent`、可选 `ce/plan/*_plan.md` / session 注入的 Planning Context。

交回：YAML（Host finalize 捕获）。禁止 Write `parts/`、`targets.yaml`、`plan.md`。

完成：`requirement.text` 已填；`targets` 非空；每个 Target 可判定。缺捕获时 fuse 失败并回到本步。

## 步骤

1. **读 init。** 列、encoding、mapping。原始 B/N/S/D 默认只是 Control。
2. **用户点名的实现状态优先成为 Target。** 没点方向 → Target = Host 接受的 dispatch（`tiling_key` 可观测）；candidate dimensions = UO 已声明且通过 RCPO 的 TilingKey 维。
3. **PR 意图：** 从 changed behavior 提 Target，不按 diff 行提 Target。
4. **Dimension vs Guard：** 改这个条件后 Target 还应成立 → Dimension candidate；Target 应消失 → Guard。
5. **B/N/S/D 等原始输入默认只是 controls。** 只有代码直接按其语义分区且不可进一步归并时，才允许成为 Dimension。
6. **无 deterministic evidence：不能成为正式 Target。**

## 常驻判断

```text
Relevant → Controllable → Partitionable → Observable
```

否则不能进 candidate Dimension。从 Target 周围只抽决策结构：branch / threshold / remainder / dispatch / resource regime / dtype-layout / parallel regime。

## 看到这样

| 现象 | 判断 |
| --- | --- |
| 对话没指定方向 | Target = dispatch；candidate dims = TilingKey 维 |
| 用户说按 PR 出 case | changed behavior → Target，不按 diff 行 |
| 用户说「给我一个 kvMerge=true」 | 只有 Target，不必凑 Dimension |
| 「充分测试」 | Target + candidate dims + Guards |
| 想写 partition / L0–L3 | 交给 fuse |
| 想 Write 文件 | 禁止 |

## 完成勾选

- [ ] `requirement.text` 写清
- [ ] `targets` 非空、可判定
- [ ] 没有写 partition / L0–L3 / case
- [ ] 没有 Write 磁盘

## 输出形状

```yaml
requirement:
  text: "kvMerge 的 TND 场景充分覆盖，并验证不满足 merge 条件不能误进"
targets:
  - id: T-kvmerge
    symbol: kvMerge
    expected: true
guards:
  - id: G-v-null
    target: T-kvmerge
    predicate: "v == nullptr"
candidate_dimensions:
  - id: D-dtype
    reason: "kernel specialization"
  - id: D-tail
    reason: "tail path"
```

## 反模式

- 有 diff 就按 Changed Targets 铺开（用户没点 PR）
- 把 B/N/S/D 直接当 Dimension
- 本步写 partition 或 L0–L3
- Write `targets.yaml` / `plan.md`

## 停

YAML 交回即停。下一状态是 fuse。
