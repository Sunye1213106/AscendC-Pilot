# Bug Review（CBM 主，KB 补）

## Goal

发现缺陷、API 误用、同步/安全红线；按冲击面优先审查。

## Inputs

- context_pack.cbm.impact（changed_symbols / callers / priority / impacted_files）为主
- context_pack.kb_graph（entities_in_files、侧别、约束）为补充
- 条例摘要：`prompts/review/clauses/`
- Agent 深挖：MCP `codebase-memory-mcp` 的 `trace_path` / `search_graph` / `get_code_snippet` / `get_architecture`

## Procedure

1. 从 CBM impact 的 `priority` / 高 `inbound_degree` 符号开始
2. KB 补充：变更命中实体、host/tiling/kernel 侧别、约束是否可能被改断
3. 按侧别加载对应条例；假设检验：只对相关条例下结论
4. 每条 finding 必须有 severity、条例 id（若适用）、file:line、证据、建议
5. 写出 `review/bug_report.yaml` + `.md`

可派发 `agents/uo-code-reviewer.md`（≤15 tool calls）。

## YAML shape

```yaml
version: 1
kind: bug_review
op_name: ...
primary_graph: cbm
supplement_graph: kb_graph
risk_score: low|medium|high|critical
findings:
  - id: BUG_1
    severity: high
    clause_id: ASCENDC-SAFE-01
    title: ...
    file_path: ...
    start_line: 0
    evidence: ...
    kb_notes: ...
    recommendation: ...
kb_supplement: {}
summary: ...
```
