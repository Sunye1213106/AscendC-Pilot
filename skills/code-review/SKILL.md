---
name: code-review
description: >
  基于 CodeMap、源码和 git/PR diff 做 AscendC 代码审查。输入只有代码改动。
  Spec 轴对照当前 `{slug}_plan.md`（无计划则只陈述变更），Standards 轴对照仓规范；
  review 阶段并行两个子代理隔离上下文。结论留在对话，不落盘。
  边界：不签发 CE 证书；建议测试走 /tg-plan。
---

# 代码审查

`/ce-review` 的输入只有代码改动：GitCode/GitHub PR URL（引擎 fetch）、`/ce-apply` 后的工作区 diff、或 `base...head`。贴 PR URL 会作为审查的输入来源，但自然语言一律走 `workflow=auto`；只有用户打了 `/ce-review` 才直达本入口。远程 fetch 失败时 HTTPS 回退需要 `GITHUB_TOKEN` 或 `GITCODE_TOKEN`。无 diff 则停。

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

证据顺序：**先插件 `pilot_cli` `uo-query`（形态 3 `--file --line`，再形态 1 跟 FOCUS 名）**，不够再开最小源码窗。不要传 `--mode`。禁止 `explain-*` / Grep 通读。

## `/ce-review` 阶段

```text
scope（内存取 diff）→ review（Spec ∥ Standards）→ summary（AskQuestion）
```

- `scope`：没有可审查的代码改动则停。
- `review`：Host 同一轮并行两个 `ce-reviewer` Task。禁止合成一个 LGTM，禁止一个子代理写两轴。禁止 Write `ce/**`。
- `summary`：建议修改（`/ce-plan` 或 `/ce-apply`）或建议测试（`/tg-plan`）。

Spec 轴：有 `active_plan` 则对照 `{slug}_plan.md`；纯 PR 无计划则只陈述变更理解。

## Capability routing

- scope / 入口：`capabilities/standalone-review/METHOD.md`
- 并行轴：`capabilities/spec-review/METHOD.md`、`capabilities/standards-review/METHOD.md`
