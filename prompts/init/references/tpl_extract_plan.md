## Task

遵循 `agents/uo-semantic-resolve.md` 任务 C。仅从候选确认 extract_plan。
禁止发明候选列表外的 writers/receivers/aliases。

## Target

`ir/extract_plan_candidates.yaml` → `ir/extract_plan.yaml`

## Context

- UO_ROOT: `<UO_ROOT>`
- 只读：`<UO_ROOT>/ir/extract_plan_candidates.yaml`
- 可选：对薄弱候选做一次 MCP `get_code_snippet`（`prompts/common/cbm.md`）
- Schema：`agents/references/semantic-resolve-tasks.md` §C

## Authoritative Sources

候选列表 · 一次 MCP snippet · 下方角色规则

非权威：其他算子记忆；整树 Glob。

## Required Procedure

1. 从候选确认真实 tiling writers / sinks / aliases。
2. 指定 role ∈ `tiling_writer|key_writer|workspace_writer|provenance_helper|ignore`
   - 证据含 `has_set_field|recv_set_call|sink_set_writer` → 必须 `tiling_writer`
   - `provenance_helper`：链上助手且无 sink 写入（有 set_field 证据时勿用）
3. 写 `extract_plan.yaml` 后 stop。父代理：`apply_extract_plan.py --check`。

## Hard Constraints

- MUST NOT：发明候选外名字
- MUST NOT：改写 contracts/tiling/kernel
- ONLY write：`<UO_ROOT>/ir/extract_plan.yaml`
- Cap ~12 tool calls

## Output Schema

```yaml
version: 1
confirmed_by: llm
writers: [{name, file_path, start_line, role}]
receivers: [{name, is_tiling_sink}]
aliases: [{local, tdf_leaf}]
non_sink_roots: []
extra_host_entries: []
derived_roots: []
```

## Acceptance Criteria

- 每个名字 ⊆ 候选
- 角色与 evidence flags 一致
- 父代理 check 通过或返回可操作 rejects

## Failure Handling

候选歧义 → 宁可 missing/ignore + 理由，勿发明。
若全部 kernel 候选错误 → missing 式说明；禁止伪造路径。
