# AscendC-Pilot 文档索引

## design（架构与原则）

| 文档 | 说明 |
| --- | --- |
| [design/architecture.md](./design/architecture.md) | **现状架构**（UO / TG / Pilot / 三域） |
| [design/system-design.md](./design/system-design.md) | 系统数据流 |
| [design/skill-prompt.md](./design/skill-prompt.md) | Domain / Prompt / Harness 原则 |
| [design/where-does-this-go.md](./design/where-does-this-go.md) | **分层决策表**：这句话该写哪一层 |
| [design/principles.md](./design/principles.md) | 产品修改口诀 |
| [design/control-closure.md](./design/control-closure.md) | UO 控制来源闭合（短注） |

**Agent 认知权威**：`skills/operator-analysis`、`skills/testcase-generation`、`skills/source-proof`、`skills/code-review`（共用 `skills/_shared`），不是本目录下的长篇 SOP。

## fag（校准样本，非 Skill）

| 文档 | 说明 |
| --- | --- |
| [fag/tilingkey-closure-report.md](./fag/tilingkey-closure-report.md) | 历史校准闭合报告 |
| [fag/fag-arch35-wsl-full-tilingkey-run.md](./fag/fag-arch35-wsl-full-tilingkey-run.md) | WSL 工程跑记 |
| [fag/fag-arch35-static-blocker-execution-20260806.md](./fag/fag-arch35-static-blocker-execution-20260806.md) | 静态 blocker 执行日志 |
| [fag/data/](./fag/data/) | 可达用例 CSV 等 |

## case-studies（人类溯源，Agent 默认不读）

| 文档 | 说明 |
| --- | --- |
| [case-studies/](./case-studies/) | 从实战提炼的命名案例（如跨层契约） |

## Skill 原则

组合式分层以 [design/skill-prompt.md](./design/skill-prompt.md) 为准。产品修改口诀见 [design/principles.md](./design/principles.md)。
