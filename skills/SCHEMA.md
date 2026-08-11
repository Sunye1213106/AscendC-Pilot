# Skills layout

| Kind | Path | Notes |
|------|------|-------|
| Cognitive skills | `skills/<id>/` | Self-contained `SKILL.md` + `references/` + `examples/` |
| Templates | `skills/testcase-generation/templates/` | Structure-only snippets (not worked examples) |
| Shared (deprecated) | `skills/_shared/` | Do not add files; content copied into each skill `references/` |

Each cognitive skill must ship ≥2 worked example case directories under `examples/<case>/` with `README.md`, `input/`, `expected/`.
