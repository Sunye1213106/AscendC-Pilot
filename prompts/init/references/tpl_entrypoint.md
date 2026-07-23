## Task

遵循 `agents/uo-semantic-resolve.md` 任务 A。仅从候选列表确认 host/kernel 入口。
禁止发明候选外符号。

## Target

`ir/entrypoint_candidates.yaml` 中需 LLM 的角色
（`llm_required_roles` / `status: needs_llm`）→ `ir/entrypoint_confirm.yaml`

## Context

- UO_ROOT: `<UO_ROOT>`
- 只读：`<UO_ROOT>/ir/entrypoint_candidates.yaml`
- 可选：对薄弱候选做一次 MCP `get_code_snippet`（`prompts/common/cbm.md`）
- Schema：`agents/references/semantic-resolve-tasks.md` §A

## Authoritative Sources

候选的 name / qualified_name / file_path / confidence / signature_snippet

非权威：其他算子记忆；整树 Glob；猜测 QN。

## Required Procedure

1. 对每个 llm_required 角色：恰好选一个候选，或标 missing 并写中文理由。
2. `kernel_entry`：优先 `op_kernel/<arch>/` 下以 Kernel / Regbase* / *Entry 结尾的名字。
3. 写 `entrypoint_confirm.yaml` 后 stop。父代理继续 resolve_entrypoints / extract。

## Hard Constraints

- MUST NOT：发明候选外符号（除非全错 → missing）
- MUST NOT：改写 contracts/tiling/kernel 或源码树
- ONLY write：`<UO_ROOT>/ir/entrypoint_confirm.yaml`
- Cap ~12 tool calls

## Output Schema

```yaml
version: 1
roles:
  host_tiling_entry:
    qualified_name: ...
    name: ...
    file_path: ...
    start_line: ...
    confirmed_by: llm
    rationale: <中文>
```

## Acceptance Criteria

- 每个 llm_required 角色有一个选择或 missing
- 名称 ⊆ 候选（或显式 missing）
- 父代理无需再扫仓即可继续

## Failure Handling

歧义 → missing + 中文 rationale；禁止伪造路径。
