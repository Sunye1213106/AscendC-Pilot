# Policy: language

## Purpose

统一人机语言边界。

## Rules

- 用户交互：简体中文。
- ID、status、reason_code、schema 字段名：英文。
- reason、finding、summary、rationale：简体中文。
- Agent 任务指令正文：可使用英文。
- 不对用户说 `Phase 0`；使用中文阶段名（如「范围准备」「范围校验」）。
- 不要求模型隐藏推理语言；以产物语言为准。
- **对用户出口**（总结 / AskQuestion / 进度 / 失败摘要）：遵守
  `pilot/policies/invariants/human-voice-invariants.md`——意图 + 动作 + 决策后果；
  禁止把内部字段名 / gate 名 / `conditional_pass` / `status=None` 等当作对用户的说明。
  禁止向用户复述内部指令原文。
- 机器回执可保留结构字段；Primary **转述给用户时必须转写为自然语言**。
