---
name: code-review
description: >
  基于 CodeMap、源码和 git/PR diff 做 AscendC 代码审查。输入只有代码改动。
  Spec 轴对照当前 `{slug}_plan.md`（无计划则从 PR/diff 索引推断粗意图并验收完成度），Standards 轴对照仓规范；
  两轴由主控同一轮并行派发，隔离子代理上下文。结论留在对话，不落盘。
  边界：不签发 CE 证书；建议测试走 /tg-plan。意图只是一次审查时留在主线。
---

# 代码审查

`/ce-review` 的输入只有代码改动：GitCode/GitHub PR URL（引擎 fetch）、`/ce-apply` 后的工作区 diff、或 `base...head`。贴 PR URL 会作为审查的输入来源；需要隔离 worktree 时由主控 Todo 的「获取 PR 代码」格 `pilot_run(workflow=auto)`。只有用户打了 `/ce-review`、或主控 Todo 当前格就是审查时才进本入口。远程 fetch 失败时 HTTPS 回退需要 `GITHUB_TOKEN` 或 `GITCODE_TOKEN`。无 diff 则停。

意图只是一次审查：主线 `pilot_run`，不要再包一层 coordinator。双轴 Task 必须由主控按 `host_step.tasks` 同一轮派发；`ce-reviewer` 禁止再派 Task，查图只用 `pilot_cli` `uo-query`。

侧别：`op_kernel/` → Kernel；`op_host/` → Tiling。两侧都动则分侧陈述。

完成条件：每条 FINDING 有 `path:line`；H1 在报告前被尝试推翻。对人汇总：审查完成 / 意图是什么 / 改了什么 / 计划达成怎样 / 问题 / 若测应重点测什么（Planning Context）。

```text
取 diff → review（主控：Spec 子代理 ∥ Standards 子代理）→ 返回 Primary
```

## 假设检验

对每个可疑代码段：

1. **H0**：该段安全 / 合同成立。
2. **H1**：存在可观察风险（越界、除零、同步缺失、跨层断裂、精度路径错误）。
3. 判定带 `path:line`。没有行号就不是 finding。
4. 报告前尝试推翻 H1。

证据顺序：**先读 `change_capture/index.md` 的 Added identifiers，并行 form-1 查新字段/新函数**（一张字段卡即 Host 写 + Kernel 读）。不要先 form-3 打 format hunk。不要传 `--mode`。禁止 `explain-*` / Grep 通读。

硬规则：snippet 截断不得下「枚举未用」；Kernel 以字段 readers 行为准，不要把 call_boundary 行当定义。每个 changed file 必须 finding / format-only / UNREVIEWED；未审 `op_kernel` 禁止「无 high/medium」。UT 不在图里：只读 `tests/**` 搜新字段名。

## `/ce-review` 阶段

```text
scope（内存取 diff）→ review（Spec ∥ Standards）→ summary（主控综合，不落盘）
```

- `scope`：没有可审查的代码改动则停。
- `review`：主控同一轮并行两个 `ce-reviewer` Task。禁止合成一个 LGTM，禁止一个子代理写两轴。禁止 Write `ce/**`。结论在 Task 回复；插件用原文 ACK。
- `summary`：主控把两轴正文转述给人。勾掉 Todo 后再 `pilot_run` 下一格。Host 不得自动继续 `tg-init`。

Spec 轴：有 `active_plan` 则对照 `{slug}_plan.md`；纯 PR 无计划则从 PR 标题 + change_capture/index.md + uo-query 推断粗意图并验收完成度。禁止通读 `diff.md`。

## Capability routing

- scope / 入口：`capabilities/standalone-review/METHOD.md`
- 并行轴：`capabilities/spec-review/METHOD.md`、`capabilities/standards-review/METHOD.md`
