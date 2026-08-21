---
name: spec-review
description: 审查 diff 的 Spec 这一路：改动是不是这次需求要的。有 git/PR diff 且走 Spec 时使用。
---

# Spec 轴

只做 **Spec** 这一路。不要做 Standards。问的是：这次要的行为有没有做完、有没有超范围、看起来做了但实现对不对。Finding 必须有 `path:line`。报告前尝试推翻 H1（「改动实现了声称的意图」）。

禁止「只陈述理解就算完成」。无 span 的「可能有问题」降级或不报。

## 输入 / 输出 / 停

读：`change_capture/index.md` 的 Added identifiers、可选的 `{slug}_plan.md`、查图卡片。不要通读 `diff.md`。无 diff 则停（父步应已拦住）。

写：Task 回复里的 findings。禁止 Write `ce/**`。不得修改 `.uo`。

完成：每条 FINDING 有 `path:line`；未审 `op_kernel` 时不宣称无高风险。每个 changed file：finding / format-only / UNREVIEWED。

## 步骤

1. **意图从哪来。** 有 `{slug}_plan.md` 则对照计划（todo 是否做完、有无超范围）。没有计划时从 PR 标题 + `change_capture/index.md` 的 Added identifiers 推断 3–8 条粗意图并验收完成度。不要只复述 diff 在干什么。
2. **index → 并行查标识符。** 先读 Added identifiers，并行查图。卡片给出 `file:line` 后跟窗口，不要改去 Read 整文件。不要把 format hunk 当第一跳（空卡不是文件未索引）。
3. **报告三类。** (a) 要但缺失或半截；(b) 没要的行为；(c) 看起来做了但实现不对。每个 changed file 必须落成 finding / format-only / UNREVIEWED。
4. **推翻 H1。** 报告前主动找：计划里有但 diff 没有、diff 有但计划没有、同名符号实际不是那条路径。找不到反证才能维持 H1。
5. **snippet 截断。** 截断 + 未覆盖 WRITES 行时继续查字段卡 `write_sites` / readers，不得下「枚举未用」。Kernel 以字段 readers 行为准，不要把 `kernel_call_boundary` 调用点当成定义。

## 常驻判断

跨层契约优先于本地风格，但跨层检查属于 Standards 那一路；本路只在「超范围 / 没做完」时点名，不要把风格 finding 写进来。

UT 不在图里：只读 `tests/**` 搜新字段名；对 test 文件 `--file --line` 空是预期。

建议测试走 `/tg-plan`。本步不落测试 yaml，不合成 LGTM（收齐两路后由主控合并）。

TilingData 来源 ≠ 已校验：必须能 locate 到 `OP_CHECK_IF` 且变量同一，否则最多 UNREVIEWED / 开放，不要当完成。

## 看到这样

| 现象 | 判断 |
| --- | --- |
| 有 `{slug}_plan.md` | 对照 todo 完成度与超范围 |
| 没有计划 | 从标题 + Added identifiers 推断 3–8 条粗意图并验收完成度 |
| 只想复述 diff | 禁止；不算完成 |
| format hunk | 不是第一跳 |
| 卡片有 `file:line` | 跟窗口，不要 Read 整文件 |
| snippet 截断 | 继续查 write_sites / readers |
| 无 `path:line` | 不报 |
| 未审 `op_kernel` | 不宣称无高风险 |

## 完成勾选

- [ ] 报告了 (a) 缺失/半截 (b) 没要的行为 (c) 实现对不对
- [ ] 每个 changed file 是 finding / format-only / UNREVIEWED
- [ ] 尝试推翻过 H1
- [ ] 没有做 Standards，没有写 `ce/**`

禁止「只陈述理解就算完成」。

## 循环

1. 读 index 的 Added identifiers，并行查图。
2. 建立或对照粗意图（有计划用计划，没有就 3–8 条）。
3. 对每个 changed file 判定 finding / format-only / UNREVIEWED。
4. 尝试推翻 H1：缺了什么、多了什么、做了但路径不对。
5. 只交 Spec 这一路的回复。不写 Standards，不合成 LGTM。

## 输出形状

```text
file: <path>
status: finding | format-only | UNREVIEWED
FINDING: <要但缺失 | 没要的行为 | 实现不对>  path:line
```

未审 `op_kernel` 不得写「无高风险」。禁止只陈述理解就算完成。

## 指针

审查易错点：`references/gotchas.md`。精度/性能类发现怎么写：`references/precision-perf-findings.md`。
