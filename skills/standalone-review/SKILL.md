---
name: standalone-review
description: 确认有可审 diff 并说明两路各交什么。有 git/PR 改动、要开双轴审查时使用。
---

# 审查入口

本文件是路由。无 diff 则停。两路分头做，本步不合成 LGTM。禁止只陈述变更理解。

先读 `change_capture/index.md`。不要通读 `diff.md`。对人汇总由主控做。

## 两路各交什么

- Spec → 这次要的有没有做完、有没有超范围、实现对不对。结论在 Task 回复（path:line）。
- Standards → 跨层契约与仓规范。结论在 Task 回复（path:line）。

## 输入 / 输出 / 停

读：index（Added identifiers、changed files）。无 diff / 无 index → 停。

写：本步不写 `ce/**`，不改 `.uo`。两路结论在各自 Task 回复。

完成：两路都有带 `path:line` 的回复，或明确无 diff。

## 常驻判断

`/ce-plan` 不以 PR 为输入；`/ce-review` 审已有 diff。本步不落测试 yaml；建议测试走 `/tg-plan`。

禁止：只陈述变更理解就算完成；通读 diff.md；本步做任一路实质审查；无 span 的「可能有问题」；修改 `.uo`。

## 指针

- Spec 轴：`references/spec.md`；边角：`references/spec-gotchas.md`、`references/precision-perf-findings.md`
- Standards 轴：`references/standards.md`；边角：`references/standards-gotchas.md`、`references/ascendc-checks.md`、`references/cross-layer-contracts.md`、`references/concurrency.md`
- 入口边角：`references/gotchas.md`
