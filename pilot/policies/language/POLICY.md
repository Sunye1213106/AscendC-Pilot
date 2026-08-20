# Policy: language

## Purpose

统一人机语言边界。

## Rules

- 用户交互：简体中文。
- ID、status、reason_code、schema 字段名、工具名：英文。
- reason、finding、summary、rationale：简体中文。
- Agent 任务指令与描述（yaml `description`、invariants、SKILL.md、CONTEXT、slash 入口）：简体中文。
- 不对用户说 `Phase 0`；使用中文阶段名（如「范围准备」「范围校验」）。
- 不要求模型隐藏推理语言；以产物语言为准。
- 对用户出口：意图 + 动作 + 决策后果。模型面见 `invariants/language.md`；人/CI 细则见 `invariants/human-voice-invariants.md`。
- 机器回执可保留结构字段；Primary 转述给用户时必须转写为自然语言。
