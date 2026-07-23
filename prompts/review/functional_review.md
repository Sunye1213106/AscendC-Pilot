# 功能 / 语义审查（KB 主，CBM 补）

## Task

判断需求是否落地，或（无外部需求时）KB 语义义务/shape 在变更下是否完整。
写出 `review/functional_report.*`。

## Authoritative Sources

- `runs/*/review/context_pack.yaml`（必有 `kb_graph` + `cbm`）
- 可选 requirements 文件/URL/粘贴文本
- `diff/impact.yaml`、contracts / tiling / kernel（经 kb_graph `detail_ref`）
- CBM 补充冲击：`prompts/common/cbm.md`

Non-authoritative：未映射到实体的需求空话。

## Required Procedure

1. **清单**
   - 有外部需求：拆成可判定条目（id, description, acceptance）
   - 无外部需求：从 `affected_shapes`、`entities_in_files`、`diff.impact`、coverage
     生成语义完整性清单；`input_type=kb_semantic_completeness`
2. **KB 主映射**：`uo_kb_query` / context_pack：`entity_of`、`neighbors_of`、
   `affected_shapes`、`branches_for_key`
3. **CBM 补充**：未覆盖 callers、impacted_files
4. **取证**：CBM MCP / 源码锚点 → `pass|partial|missing|not_applicable`
5. 写出 `review/functional_report.yaml` + `.md`

可派发 `agents/uo-code-reviewer.md`（mode=functional）。

## Hard Constraints

- MUST NOT：只靠 CBM 调用图下功能结论；写 `diff/**`
- MUST：每条 item 有终态与证据

## Output Schema

```yaml
version: 1
kind: functional_semantic_review
op_name: ...
input_type: external_requirements|kb_semantic_completeness
primary_graph: kb_graph
supplement_graph: cbm
items:
  - id: REQ_1
    description: ...
    status: pass|partial|missing|not_applicable
    kb_entities: []
    affected_shapes: []
    evidence: [{file_path, start_line, note}]
    cbm_notes: ...
affected_shapes: []
cbm_supplement: {}
summary: ...
```

## Acceptance

清单条目全覆盖；missing/partial 有可定位证据或明确缺口说明。
