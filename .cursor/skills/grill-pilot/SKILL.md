---
name: grill-pilot
description: >
  在给 AscendC-Pilot 加 workflow、IR、Engine 能力或改控制面前，把设计树问清楚。
disable-model-invocation: true
---

# Grill Pilot

一次只问一个问题。把设计树问到每个分支都有决定，再动 `specs.py` / skill / engine。

先读 `agents/CONTEXT.md` 和 `docs/development/extending.md`。

## 落点（先定这一刀）

每个新想法必须落在**一个**位置：

```text
确定性计算     → Engine
领域推理方法   → Skill（闭合五个认知 skill 之内，或 references/METHOD）
一次任务说明   → Prompt
状态与迁移     → Workflow Spec
可执行步骤     → Action
独立身份/权限  → Agent
工具合同       → Capability
传输与派发     → Host Session Driver
```

「再加一个 cognitive skill」几乎总是错的。先问：这是事实还是推理？要不要新的 lease / gate？

## 问到闭合

至少覆盖：

1. 权威产物是什么（`.uo` / TG 证书 / CE 账本 / 仅文档）？
2. 谁写、谁读、谁不能写（`write_roots` / `skill_ids` / lease）？
3. 完成条件怎么机器判定（gate、quality.yaml、`Open=∅`）？
4. architecture / project 从哪来？有没有静默默认？
5. 失败时 AskQuestion 的选项原文是什么？
6. 与 UO / TG / CE 哪个同名词会撞车（obligation / fingerprint / kind）？
7. 这是算子主控行为，还是只该留在 `.cursor/skills/` 的维护者纪律？

用户说「先做起来」时，把未闭合分支列出来，问其中风险最高的一个。不要用 `/implement` 绕过 `ce-intent → ce-impact → ce-verify`，也不要在 TG solve 里改 T。

## 收尾

决定写进短 ADR 或更新 `agents/CONTEXT.md`（仅当出现了会跨 session 用错的新词）。然后按 `docs/development/extending.md` 改 Spec / 测试 / compose。
