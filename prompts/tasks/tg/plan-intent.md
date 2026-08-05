## Task

Confirm the coverage plan intent for this operator. Default is full TilingKey closure.

Follow the assigned role contract and loaded capabilities.
Do not manage workflow state or declare completion.

## Mode

- mode: `task`
- task_id: `plan-intent`
- workflow_id: `tg-plan`
- action_id: `plan_intent`
- run_id: `<RUN_ID>`

## Required Procedure

1. AskQuestion（同一轮，可点选）三选一：
   - **A. 默认全量 TilingKey 闭环**（`mode=tilingkey_full_coverage`）——未指定时选这项
   - **B. 用户描述**——粘贴目标维度 / 场景说明 → `source=user`
   - **C. PR / diff**——粘贴 PR 链接或路径 → `source=pr`
2. 写出 `.ascendc-pilot/tg/plan/plan_intent.yaml`（或通过 `acp run-action plan_intent --finalize` 落盘）：

```yaml
schema: tg-plan-intent/v1
mode: tilingkey_full_coverage   # 或 csv_consumer
source: default                 # default | user | pr | init_intent
description: ""
pr_ref: ""
op_name: <from context>
```

3. 默认路径禁止再追问 CSV / test-script-root。
4. Stop after the artifact exists.

## Hard Constraints

- MUST NOT: modify Pilot state or declare workflow passed.
- MUST NOT: invent obligations (那是 `plan_build` 的事).
- MUST NOT: skip AskQuestion when the user gave neither description nor PR and did not say "default".
- When the user already said "全量 / tilingkey / 默认"，直接写 default，勿重复确认.

## Output Contract

Contract id: `plan-intent-v1`

## Acceptance Criteria

- `tg/plan/plan_intent.yaml` exists with `mode` set.
- Default mode is `tilingkey_full_coverage` unless the user chose otherwise.
