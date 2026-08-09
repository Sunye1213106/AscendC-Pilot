# `_archive` — superseded UO code (read-only)

This tree holds UO modules and packages that are **no longer part of the live
CodeMap compiler**. Keep it for archaeology; do **not** import from here in:

- `uo_init.pilot_engines`
- Pilot `ENGINE_REGISTRY` / gates
- skills / agents / prompts

## Layout

| Path | Contents |
|------|----------|
| `legacy_uo_package/` | Former `engines/understand-operator/uo/` shell (`scripts` / `_core` / `_operator`). Source was already removed; only `__pycache__` remained. |
| `pipeline_v1/` | YAML-pipeline / multi-artifact modules superseded by unified CodeMap + `.uo` store. |

Live implementation lives under `src/uo_init/`.
