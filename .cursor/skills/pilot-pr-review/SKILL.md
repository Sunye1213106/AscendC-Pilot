---
name: pilot-pr-review
description: >
  Review AscendC-Pilot repo changes since a fixed point along two axes:
  Standards (SCHEMA, ownership, skill architecture, invariants) and Spec
  (originating issue or stated intent). Use when reviewing a Pilot PR or
  branch. Not /ce-review on an operator.
disable-model-invocation: true
---

# Pilot PR review

审的是 **Pilot 本仓** diff，不是算子 `/ce-review`。两轴分开看，最后并排汇总。

## 1. 钉住比较点

用户给的 commit / branch / `main`。`git rev-parse` 能解析，且 `git diff <base>...HEAD` 非空。空 diff 在这里停。

## 2. Spec 轴

按这个顺序找意图：commit 里的 issue 引用、用户给的路径、`docs/` 或会话里的设计。没有 spec 就标明「无 spec」，只做 Standards 轴。

问：diff 是否忠实实现了那个意图？有没有顺手改控制面（lease / gate / skill_ids / compose）却没改测试？

## 3. Standards 轴

仓库覆盖工具的不再用人审（lint 已抓的跳过）。人工看：

- 认知 skill 是否仍是五个；有没有把维护者流程写进 `skill_ids`
- `SKILL.md` 是否 ≤200 行、有无 harness 泄漏
- `agents/CONTEXT.md` 同名词有没有被并成一个意思
- 新行为是否有 gate / contract 测试
- 文档是否把实现又抄了一遍（权威应留在 Spec / 测试）

Fowler 气味作启发式，不是硬违规：Mysterious Name、Duplicated Code、Feature Envy、Primitive Obsession。仓库已有标准优先。

## 4. 汇总

| 轴 | 发现 | 阻塞？ |
| --- | --- | --- |
| Spec | … | 是/否 |
| Standards | … | 是/否 |

不签发算子 CE 证书。不把「LGTM」写进 `.uo` / TG 账本。
