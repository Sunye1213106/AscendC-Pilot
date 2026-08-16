---
name: code-review
description: >
  基于 CodeMap、源码和变更信息做 AscendC 代码审查。三种入口：快速看风险、文件检视、PR 检视。
  用户要审查算子代码改动、找潜在 bug 时使用。假设检验驱动；证据先 CodeMap 再最小源码窗。
  Spec 轴对照需求，Standards 轴对照仓规范，两轴分开写不合成 LGTM。
  边界：不签发 CE 证书；检视 Cast/DataCopy/切分改动时认出精度或性能场景线索，仍不关闭验证义务。
---

# 代码审查

三种入口（由 `/ce-review` 的 `scope` 阶段判定，不另开 slash）：

| 入口 | 何时 | 产物 |
| --- | --- | --- |
| **快速** | 「有没有问题 / 快速看风险」 | 短 finding；不写长报告 |
| **文件** | 指定文件或全量检视当前算子 | `ce/review/*.yaml` 完整 finding |
| **PR** | 有 diff / change capture | 先有 diff 再检；finding 必须落在变更范围内 |

侧别：`op_kernel/` → Kernel；`op_host/` → Tiling。两侧都动则分侧陈述。

完成条件：每条 FINDING 有 `path:line`；H1 在报告前被尝试推翻。

```text
入口 + 侧别 → CodeMap 邻域 → H0/H1 → 最小源码窗 → 推翻 → FINDING / NO_CONFIRMED_ISSUE / UNRESOLVED
```

## 假设检验

对每个可疑代码段：

1. **H0**：该段安全 / 合同成立。
2. **H1**：存在可观察风险（越界、除零、同步缺失、跨层断裂、精度路径错误）。
3. 判定带 `path:line`。没有行号就不是 finding。
4. 「来源 = TilingData」仍待校验：上游必须能 `locate` 到 `OP_CHECK_IF`（`facts.check_sites`）且保护**同一个变量**。
5. 报告前尝试推翻 H1；partial 索引不能证伪「没有其他调用者」。

证据顺序：**先 `acp uo-query`（impact / locate / field / buffer / kernel_api）**，不够再开最小源码窗。结构事实走 CodeMap，不走全文 Grep。

跨层与 AscendC 检查用本仓库 `references/cross-layer-contracts.md` 与 `references/ascendc-checks.md`。条例级 API 细则不在本 skill。

## `/ce-review` 阶段

```text
scope → review → summary
```

- `scope`：判定 quick / file / pr；Kernel vs Tiling；PR 无 diff 则停并标 UNRESOLVED。
- `review`：假设检验，两轴分开写：Spec → `functional_report.yaml`，Standards → `bug_report.yaml`。禁止合成一个 LGTM。
- `summary`：更新 `index.yaml`。快速入口只写短摘要。

无 intent 时 Spec 轴标明「无需求」，只做 Standards。PR 必须有 diff。

需要范围与证书时走 `/ce-intent`（无 diff 定位）或 `/ce-impact` → `/ce-verify`（有 diff）。本 skill 做只读审查，不签发 CE 证书。`verify-review` 按义务关 V，不是这套双轴。

## Capability routing

- `/ce-review` 只读检视：`capabilities/standalone-review/METHOD.md`
- `ce-verify/code_review` 义务判定：`capabilities/verify-review/METHOD.md`（不是同一套入口 SOP）

## 按需参考

| 条件 | 文件 |
|---|---|
| 跨层契约 | `references/cross-layer-contracts.md` |
| AscendC 检查 | `references/ascendc-checks.md` |
| 并发 | `references/concurrency.md` |
| 通用约束 | `references/domain-checks.md` |
| Finding 形态 | `references/examples.md` |
| 踩坑 | `references/gotchas.md` |
| 共用纪律 | `references/evidence-quality.md` / `references/completeness.md` / `references/artifact-freshness.md` |
| Cast / 搬运 / 切分是否构成精度或性能线索 | `references/precision-perf-findings.md` |
