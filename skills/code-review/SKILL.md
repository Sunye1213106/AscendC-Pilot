---
name: code-review
description: >
  基于 CodeMap、源码和 git/PR diff 做 AscendC 代码审查。输入只有代码改动。
  Spec 轴对照当前 `{slug}_plan.md`（无计划则从 PR/diff 索引推断粗意图并验收完成度），Standards 轴对照仓规范；
  review 阶段并行两个子代理隔离上下文。结论留在对话，不落盘。
  边界：不签发 CE 证书；建议测试走 /tg-plan。
---

# 代码审查

`/ce-review` 的输入只有代码改动：GitCode/GitHub PR URL（引擎 fetch）、`/ce-apply` 后的工作区 diff、或 `base...head`。贴 PR URL 会作为审查的输入来源；自然语言第一次 `pilot_run(workflow=auto)`。`auto` 有进行中的 TaskPlan 就推进当前格，审查双轴 ACK 完 Host 继续 `tg-init`。只有用户打了 `/ce-review` 才直达本入口。远程 fetch 失败时 HTTPS 回退需要 `GITHUB_TOKEN` 或 `GITCODE_TOKEN`。无 diff 则停。

侧别：`op_kernel/` → Kernel；`op_host/` → Tiling。两侧都动则分侧陈述。

完成条件：每条 FINDING 有 `path:line`；H1 在报告前被尝试推翻。

```text
取 diff → review（Spec 子代理 ∥ Standards 子代理）→ 建议修改或建议测试
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
scope（内存取 diff）→ review（Spec ∥ Standards）→ summary
```

- `scope`：没有可审查的代码改动则停。
- `review`：Host 同一轮并行两个 `ce-reviewer` Task。禁止合成一个 LGTM，禁止一个子代理写两轴。禁止 Write `ce/**`。结论在 Task 回复；插件用原文 ACK。
- `summary`：目标已含生成测例时 Host 跳过「审查下一步？」并继续 `tg-init`。单独 `/ce-review` 才问建议修改或建议测试。

Spec 轴：有 `active_plan` 则对照 `{slug}_plan.md`；纯 PR 无计划则从 PR 标题 + change_capture/index.md + uo-query 推断粗意图并验收完成度。禁止通读 `diff.md`。

## Capability routing

- scope / 入口：`capabilities/standalone-review/METHOD.md`
- 并行轴：`capabilities/spec-review/METHOD.md`、`capabilities/standards-review/METHOD.md`
