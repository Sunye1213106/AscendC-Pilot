# Bug 审查（CBM 主，KB 补）

## Task

发现缺陷、API 误用、同步/安全红线；按冲击面优先审查。写出 `review/bug_report.*`。

## Authoritative Sources

- 主：`context_pack.cbm.impact`（changed_symbols / callers / priority / impacted_files）
- 补：`context_pack.kb_graph`（entities_in_files、侧别、约束）
- 条例：`prompts/review/clauses/`
- 深挖：MCP（`prompts/common/cbm.md`：`trace_path` / `search_graph` / `get_code_snippet`）

Non-authoritative：无 file:line 的「常见坑」记忆。

## Required Procedure

1. 从 CBM impact 的 `priority` / 高 `inbound_degree` 符号开始
2. KB 补充：变更命中实体、host/tiling/kernel 侧别、约束是否可能被改断
3. 按侧别加载对应条例；只对相关条例下结论
4. 每条 finding：severity、条例 id（若适用）、file:line、证据、建议
5. 写出 `review/bug_report.yaml` + `.md`

可派发 `agents/uo-code-reviewer.md`（mode=bug，≤15 tool calls）。

## Hard Constraints

- MUST NOT：只靠 KB 定 Bug；dump 大 YAML；写 `diff/**`
- MUST：证据可定位；summary 中文

## Output Schema

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

## Acceptance

每条 finding 有 file:line；未改 ir/diff。证据不足 → 降级或标需人工，禁无依据 critical。
