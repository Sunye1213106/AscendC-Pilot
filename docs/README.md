# Documentation

本目录是人类说明文档的唯一集中入口，根目录 `README.md` 除外。

Runtime 输入继续留在代码旁边：`SKILL.md`、skill references、task prompts、Pilot policies、generated host instructions、example fixtures 都不是项目说明文档。

## 第一次使用

- [安装](getting-started/installation.md)
- [Quick Start](getting-started/quickstart.md)

## 想理解系统为什么这样设计

- [架构总览](architecture/overview.md)
- [Agent 系统](architecture/agent-system.md)
- [Harness 与权限](architecture/harness-and-permissions.md)
- [Skills、Prompts 与 Policies](architecture/skills-prompts-policies.md)
- [状态与产物](architecture/state-and-artifacts.md)
- [设计原则](architecture/principles.md)

## 想理解某个模块

- [UO - Understand Operator](modules/uo.md)
- [TG - Testcase Generation](modules/tg.md)
- [CE - Code Engineering](modules/ce.md)
- [Pilot Runtime](modules/pilot-runtime.md)
- [Engines](modules/engines.md)
- [Host Adapters](modules/host-adapters.md)

## 想开发 AscendC-Pilot

- [仓库结构](reference/repository-layout.md)
- [CLI 参考](reference/cli.md)
- [产物布局](reference/artifact-layout.md)
- [Agent Matrix](reference/agent-matrix.generated.md)
- [术语表](reference/glossary.md)
- [扩展 Agent](development/extending-agent.md)
- [扩展 Skill](development/extending-skill.md)
- [扩展 Workflow](development/extending-workflow.md)
- [扩展 Engine](development/extending-engine.md)
- [测试与 Evals](development/testing-and-evals.md)
- [文档维护规则](development/documentation.md)

## 历史材料

历史执行记录、benchmark 和 case study 归档在 [history/](history/README.md)。它们用于溯源，不再作为当前架构权威。
