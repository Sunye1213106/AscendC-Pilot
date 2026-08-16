# AscendC-Pilot（开发本仓）

这是 Pilot harness 仓库，不是算子包。算子用户走 compose 后的 UO / TG / CE。

- 共享语言：[`agents/CONTEXT.md`](agents/CONTEXT.md)
- 算子主控认知 skill（闭合 5 个）：`skills/<id>/SKILL.md`
- 改那些 skill：`.cursor/skills/writing-for-pilot-skills`
- 引擎 / Clang / quality.yaml 变红：`.cursor/skills/diagnosing-pilot`
- 新 workflow / IR：`.cursor/skills/grill-pilot`
- 给引擎写测试：`.cursor/skills/tdd-engines`
- 审 Pilot PR：`.cursor/skills/pilot-pr-review`

不要往 `skill_ids` 加通用 `/implement` 或第二份 `code-review`。维护者 overlay 不进 host compose。
