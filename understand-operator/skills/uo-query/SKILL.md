---
name: uo-query
description: >-
  Answer questions from an existing AscendC operator KB. Query is read-only and
  routes through query/routes.yaml + small layered IR exports (not full graph dumps).
disable-model-invocation: true
argument-hint: "[path] [--op-name <name>] <question>"
---

# uo-query - Read-Only KB Query

Query never creates or modifies a KB and never writes CBM data.

## Resolve KB

1. `$PROJECT_ROOT/.understand-operator/<op_name>/manifest.yaml`
2. Load `query/routes.yaml` and `query/terminology.yaml` when present
3. Else use `references/kb-file-map.md` + `references/question-taxonomy.md`

## Query flow (required)

```text
1. Classify question via question-taxonomy / query/routes.yaml
2. Resolve aliases via query/terminology.yaml
3. Read ONLY the hot files for that route (key_cards / runtime_conditions / ...)
4. If still missing: MCP codebase-memory (`search_graph` / `get_code_snippet`) for ONE symbol
5. Only then open a small real source window at file:line from anchors
6. Never dump ir/operator_graph.yaml by default
7. Never search/read `.understand-operator/**/cbm/index_stage/**` (staging mirror)
```

Read:

- `references/kb-file-map.md`
- `references/question-taxonomy.md`

Optional helper:

```powershell
python -X utf8 "$SCRIPT_DIR/uo_query_readonly.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --entity "<ID_OR_LABEL>" --question-type tiling_key_hit
```

If the KB is missing, tell the user to run `/uo-init`.

## Source Verification

Prefer anchors already on key cards / IR nodes (`file_path`/`start_line`).
Only then query MCP `codebase-memory-mcp` for that symbol.

## Answer Style

Answer in Chinese by default. Include:

- direct conclusion
- routed file + entity/key id
- source anchors when available
- confidence; call out `host_reachable`/`hit_recipe` when still `unknown`

State clearly when the KB lacks the requested fact.
