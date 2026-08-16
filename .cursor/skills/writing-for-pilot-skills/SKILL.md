---
name: writing-for-pilot-skills
description: >
  撰写或修改 AscendC-Pilot 给 agent 读的文档：认知 SKILL.md、agents/CONTEXT.md、
  AGENTS.md、SCHEMA.md、workflow entry description。Use when creating or editing
  skills, CONTEXT.md, or agent-facing pointers.
---

# Writing for Pilot agents

写的是**过程**（每次跑同一条路），不是同一段输出。改认知 skill 前先读 `agents/CONTEXT.md` 和 `skills/SCHEMA.md`。

## 两笔预算

- **Context load**：常驻窗口——`AGENTS.md` 一行、skill `description`、invariant pack。每个词每回合都在烧。
- **Cognitive load**：人要记得有哪些文档。人是索引；该花在需要判断的地方。

指针（description / AGENTS 里的一行）同时做两件事：材料是什么，以及哪些 **branch** 该去读它。

- 把触发词放在最前面。
- 一个 branch 只留一个触发；同义词合并。
- 正文已经有的身份句，不要在指针里再写一遍。

## 信息层级

1. 文内步骤（按顺序做）
2. 文内参考（按需查阅的扁平规则）
3. 披露参考（`references/`、`capabilities/*/METHOD.md`，指针命中才读）

每个 branch 都需要的留在 SKILL.md；只有部分 branch 才读的推进 `references/`。概念的定义、规则、caveat 放在同一标题下。

## 完成条件

每一步以可判定的完成条件结尾：短问 = 一次 `acp uo-query` stdout；深问 = 同一轮 Task 全文综合；建库结束 = Read `quality.yaml` 再对人总结。模糊的「理解了」会诱使提前收工。

## Leading words

优先用 `agents/CONTEXT.md` 已有的词（短问、深问、CodeMap、digest、Open、Tier A/B/C、R/E/T/D）。自造词要付定义税。

先写要做什么，再配 hard guardrail。否定会把禁止行为拉进上下文；只有无法正向表达的红线才保留「禁止」，并紧跟正向目标。

## Pilot 硬约束

- 认知 skill 仍是闭合的五个。新方法先判断 Engine / Skill / Prompt / Workflow / Agent，见 `docs/development/extending.md`。
- `SKILL.md` ≤ 200 行；harness 词（`finalize`、`acp start`、`run_id`）不进认知 skill。
- 不要复活 `skills/_shared/`。
- 每个认知 skill ≥2 个 `examples/<case>/`。
- 路由 eval 吃的是 `description` 关键词：改指针后跑 `python evals/skills/run_skill_eval.py` 与 `python evals/routing/run_routing_eval.py`。
- 查询路由启发式留在 `capabilities/uo-query-router/METHOD.md`：可见 LLM 路由指针可留在 `operator-analysis` SKILL，算法正文不进 Policy。
