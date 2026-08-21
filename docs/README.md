# 文档导航

本文档以中文为主，解释项目的设计动机、边界和数据流。实现、schema、workflow 与测试是事实权威；runtime 会消费的 `SKILL.md`、prompt 和 policy 保留在其代码位置。

## 使用 AscendC-Pilot

```text
安装
  -> Quick Start（自然语言说目标，或 Slash 专家命令）
    -> Host 工具（pilot_run auto / 显式 workflow；插件 pilot_cli）
    -> UO：建立并查询 CodeMap
    -> TG：建立覆盖闭环
    -> CE：审查改动影响
```

- [安装](getting-started/installation.md)
- [Quick Start](getting-started/quickstart.md)（自然语言 `pilot_run(auto)` 与 `/uo-*` `/tg-*` `/ce-*` 双路径）
- [Host 工具使用](getting-started/acp-tools.md)（`pilot_run` / 插件 `pilot_cli`）
- [PR → 定向 cases 手工 E2E](test/golden-e2e-pr-cases.md)（真仓清单，不进默认 pytest）
- [UO - Understand Operator](modules/uo.md)
- [当前版本 UO benchmark（FAG arch35 冷启动 119s、查询与未闭合项）](benchmark.md)
- [TG - Testcase Generation](modules/tg.md)
- [CE - Code Engineering](modules/ce.md)
- 执行 Skill：平铺在 `skills/<id>/SKILL.md`（当前 Action 配方；不是五个封闭领域）
- Agent 词表：[`agents/CONTEXT.md`](../agents/CONTEXT.md)

## 开发 AscendC-Pilot

```text
架构总览
  -> Agent Runtime（ACP / Harness / Host Session Driver）
  -> UO / TG 的数据模型
  -> 产物与权威
  -> 扩展与测试
  -> 精确 Reference
```

- [架构总览](architecture/overview.md)
- [工作流流程图](architecture/workflows.md)
- [Agent Runtime](architecture/agent-runtime.md)（含 `pilot_run`、`host_step`、Bundle 读闭合）
- [Agent 内容整理规范](architecture/agent-content-rules.md)（Policy / Skill / Prompt / Agent 属主）
- [产物与权威](architecture/artifacts-and-authority.md)
- UO 查询产品地图：[`skills/uo-query/references/uo-product-map.md`](../skills/uo-query/references/uo-product-map.md)（progressive；域文档按需）
- [扩展指南](development/extending.md)
- [测试与评估](development/testing.md)
- [文档维护](development/documentation.md)
- 抽检记录（WIP，不当产品质量入口）：[docs/test/](test/README.md)

## Reference

- [Workflow Reference](reference/workflows.generated.md)
- [Agent Matrix](reference/agent-matrix.generated.md)
- [CLI Reference](reference/cli.generated.md)（清单；用法见 [ACP 工具使用](getting-started/acp-tools.md)）
- [产物布局 Reference](reference/artifact-layout.generated.md)
- [仓库结构](reference/repository-layout.md)
- [术语表](reference/glossary.md)

历史执行记录和 case study 位于 [history/](history/README.md)，只用于溯源，不是当前架构权威。
