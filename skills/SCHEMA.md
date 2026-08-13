# Skills layout

Cognitive skills（五个，缺一不可）：

| # | id | 用途 |
| --- | --- | --- |
| 1 | `operator-analysis` | UO CodeMap 查询 / 调查 |
| 2 | `testcase-generation` | TG 覆盖规划与闭环 |
| 3 | `source-proof` | 源码引理 / 不可达证明 |
| 4 | `code-review` | `/ce-review` 只读检视 |
| 5 | `code-engineering` | `/ce-intent` `/ce-impact` `/ce-verify` 变更闭环 |

| Kind | Path | Notes |
|------|------|-------|
| Cognitive skills | `skills/<id>/` | Self-contained `SKILL.md` + `references/` + `examples/` |
| Templates | `skills/testcase-generation/templates/` | Structure-only snippets (not worked examples) |
| Shared | `skills/_shared/` | **已删除，勿再添加。** 内容已迁入各 skill 的 `references/` |

Each cognitive skill must ship ≥2 worked example case directories under `examples/<case>/` with `README.md`, `input/`, `expected/`.
