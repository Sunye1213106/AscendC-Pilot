# AscendC-Pilot 文档索引

## design（架构与原则）

| 文档 | 说明 |
| --- | --- |
| [design/architecture.md](./design/architecture.md) | **现状架构**（UO / TG / Pilot / 三域） |
| [design/tilingkey-closure-agent.md](./design/tilingkey-closure-agent.md) | TilingKey 闭环可执行 SOP |
| [design/system-design.md](./design/system-design.md) | 系统数据流 |
| [design/skill-prompt.md](./design/skill-prompt.md) | 组合式 Skill / Prompt 原则 |
| [design/principles.md](./design/principles.md) | 产品修改口诀 |
| [design/control-closure.md](./design/control-closure.md) | UO 控制来源闭合（短注） |

## fag（校准样本）

| 文档 | 说明 |
| --- | --- |
| [fag/tilingkey-closure-report.md](./fag/tilingkey-closure-report.md) | FAG arch35 闭合报告（历史校准） |
| [fag/fag-arch35-wsl-full-tilingkey-run.md](./fag/fag-arch35-wsl-full-tilingkey-run.md) | WSL 工程跑记 |
| [fag/fag-arch35-static-blocker-execution-20260806.md](./fag/fag-arch35-static-blocker-execution-20260806.md) | 静态 blocker 执行日志 |
| [fag/data/](./fag/data/) | 可达用例 CSV 等交付物 |

## debug

| 文档 | 说明 |
| --- | --- |
| [debug/open-problems.md](./debug/open-problems.md) | 未决问题 |
| [debug/handoff.md](./debug/handoff.md) | 交接笔记 |
| [debug/bug_report_fag_fp32_rope_undeclared_key.md](./debug/bug_report_fag_fp32_rope_undeclared_key.md) | fp32+rope 未声明 Key |

## 归档

`[_archive/](./_archive/)` 存放已废弃的计划、探针快照与历史决策记录，**不是契约**。

## Skill 原则（权威位置）

组合式分层与写作原则以 [design/skill-prompt.md](./design/skill-prompt.md) 为准（旧名 `skill-and-prompt-principles.md` 已并入此处）。产品修改口诀见 [design/principles.md](./design/principles.md) 与 `.cursor/rules/product-change-principles.mdc`。
