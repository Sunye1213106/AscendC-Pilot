<task>
对当前修改做只读代码审查。入口为快速 / 文件 / PR 之一。
</task>

<context>
- Project: `<PROJECT_ROOT>`
- UO: `<UO_ROOT>`
- Current phase: session `current_phase`（scope / review）
- Plan (if present): `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/ce/intent/plan.md`
- Diff (if present): change capture under `ce/impact/` 或 `ce/apply/`

本入口不签发 CE 证书。方法见 session `method.md`（`code-review/standalone-review`）。
</context>

<constraints>
无 diff 要定位改哪里：`/ce-intent`。有 diff 要范围与证书：`/ce-impact` → `/ce-verify`。
Spec / Standards 由并行隔离子代理做。结论写在 Task 回复（`path:line`），不要填 `ce/review/*.yaml`。不要合成 LGTM，不要一个子代理写两轴。
禁止写入 `ce/verify/**`。不要读 intent.yaml / feature_decomposition / impact_slice。
</constraints>

<output>
在 Task 回复中给出入口与 `path:line` 结论。不要写 `ce/review/` 下的 YAML。
</output>
