<task>
对当前修改做只读代码审查。入口为快速 / 文件 / PR 之一。
</task>

<context>
- Project: `<PROJECT_ROOT>`
- UO: `<UO_ROOT>`
- Current phase: session `current_phase`（scope / review / summary）
- Impact slice (if present): `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/ce/impact/impact_slice.yaml`
- Change capture (if present): `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/ce/impact/change_capture.yaml`

本入口不签发 CE 证书。方法见 session `method.md`（`code-review/standalone-review`）。
</context>

<constraints>
无 diff 要定位改哪里：`/ce-intent`。有 diff 要范围与证书：`/ce-impact` → `/ce-verify`。
禁止写入 `ce/verify/**`。
</constraints>

<output>
写入 `ce/review/` 下三份 YAML：`bug_report.yaml`、`functional_report.yaml`、`index.yaml`（`entry` 为 quick | file | pr）。
</output>
