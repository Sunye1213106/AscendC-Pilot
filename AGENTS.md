# AscendC-Pilot（开发本仓）

这是 Pilot harness 仓库，不是算子包。算子用户走 compose 后的 UO / TG / CE。

- 共享语言：[`agents/CONTEXT.md`](agents/CONTEXT.md)
- 算子主控认知 skill（闭合 5 个）：`skills/<id>/SKILL.md`
- 写法约束：[`skills/SCHEMA.md`](skills/SCHEMA.md)
- 词表：[`agents/CONTEXT.md`](agents/CONTEXT.md)

不要往 `skill_ids` 加通用 `/implement` 或第二份 `code-review`。改码入口是 `/ce-apply`。
