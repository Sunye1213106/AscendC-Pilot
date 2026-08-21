---
name: standalone-review
description: 入口审查：确认有可审 diff，并说明两路各自要交什么。执行 /ce-review 的 code_review 父步时使用。
---

# 审查入口

输入只有代码改动。无 diff 则停。本步只确认有可审 diff、说明两路各交什么，然后停。两路分头做：Spec 读 `skills/spec-review/SKILL.md`，Standards 读 `skills/standards-review/SKILL.md`。本步不合成 LGTM。禁止只陈述变更理解。

先读 `change_capture/index.md`。不要通读 `diff.md` 当小说。查图用现有 uo-query 工具。对人汇总由主控做。

## 输入 / 输出 / 停

读：index（Added identifiers、changed files）。无 diff / 无 index → 停，不要编 3–8 条意图假装在审。

写：本步不写 `ce/**`，不改 `.uo`。两路结论在各自 Task 回复。

完成：两路都有带 `path:line` 的回复，或明确无 diff。

## 步骤

1. **确认有 diff。** PR / 工作区没有可审查的代码改动则停。贴 URL 但当前仓对不上、没有 `.uo` → 停并说明，不要开始审。
2. **读 index，不读长 diff。** Added identifiers 是两路的第一跳。format-only 文件标出来，不要当第一跳查图。
3. **分路，不要混。** Spec：这次要的有没有做完、有没有超范围、实现对不对。Standards：跨层契约与仓规范。本步不代替任一路，不把两路 finding 提前合并。
4. **声明完成条件给切片。** 每个 changed file 必须是 finding / format-only / UNREVIEWED。未审 `op_kernel` 禁止「无高风险」。无 `path:line` 不报。
5. **停。** 收齐两路后由主控用字段卡裁定矛盾、写 `parts/merged.md`；禁止再派相同 spec/standards。本步不写 merged。

## 常驻判断

`/ce-plan` 不以 PR 为输入；`/ce-review` 审已有 diff。两条不要混。本步不落测试 yaml；建议测试走 `/tg-plan`，TG 自己从审查对话总结。

禁止：

- 只陈述变更理解就算完成
- 通读 diff.md
- 本步做 Spec 或 Standards 的实质审查
- 无 span 的「可能有问题」
- 修改 `.uo`

index 空卡不是文件未索引。UT 不在图里。

## 看到这样

| 现象 | 判断 |
| --- | --- |
| 无 diff / 无 index | 停 |
| 仓对不上 / 无 `.uo` | 停并说明 |
| 想通读 `diff.md` | 禁止；读 index |
| 想本步写 findings | 禁止；交给两路 |
| 想合成 LGTM | 禁止；主控收齐后再合 |
| 只陈述变更理解 | 禁止；不算完成 |

两路完成条件（写给切片，本步不代做）：每个 changed file → finding / format-only / UNREVIEWED；FINDING 必须 `path:line`；未审 `op_kernel` 禁止「无高风险」。

## 完成勾选

- [ ] 确认有可审 diff，或明确停
- [ ] 已读 `index.md`，两路边界已说清
- [ ] 本步没有混路、没有写 `ce/**`、没有改 `.uo`

禁止只陈述变更理解。

## 循环

1. 确认有 diff 与 `index.md`。没有就停。
2. 读 Added identifiers，标明 format-only 文件。
3. 写清两路边界与完成条件，然后停。
4. 不要自己审、不要合并、不要写 LGTM。
5. 主控收齐两路后再裁定矛盾。

## 输出形状

父步回复只确认：有 diff / 已读 index / 两路已派。不要在本步列出 Spec findings。禁止只陈述变更理解。

## 反模式

- 无 diff 仍开始审
- 通读 `diff.md`
- 本步做 Spec 或 Standards 实质审查
- 合成 LGTM
- 无 span 的「可能有问题」
- 修改 `.uo` 或写 `ce/**`

## 指针

两路易错点（本步只用来对齐完成条件）：`references/gotchas.md`。两路：`skills/spec-review/SKILL.md`、`skills/standards-review/SKILL.md`。
