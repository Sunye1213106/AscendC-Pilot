<task>
对当前绑定的 git/PR diff 做只读审查。只做本轴（见 session method）。
</task>

<context>
- Project: `<PROJECT_ROOT>`
- UO: `<UO_ROOT>`
- Plan (if present): `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/ce/plan/*_plan.md`
- Change index: `runs/<RUN_ID>/actions/change_capture/index.md`
- Optional UO hints: `runs/<RUN_ID>/actions/change_capture/uo_hints.md`
- Optional hunk windows: `runs/<RUN_ID>/actions/change_capture/hunks/`
</context>

<output>
在 Task 回复中给出 `path:line` findings。不要写 yaml 或新的 CE 正式产品。
</output>
