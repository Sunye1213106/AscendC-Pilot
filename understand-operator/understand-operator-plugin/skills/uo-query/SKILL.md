---
name: uo-query
description: >-
  Answer questions from an existing AscendC operator KB. Query is read-only and
  resolves the KB through manifest.yaml, op_name, and aliases/terminology.
disable-model-invocation: true
argument-hint: "[path] [--op-name <name>] <question>"
---

# uo-query - Read-Only KB Query

Query never creates or modifies a KB and never writes CBM data.

## Resolve KB

Locate an existing KB by:

1. `$PROJECT_ROOT/.understand-operator/<op_name>/manifest.yaml`
2. `manifest.yaml.op_name`
3. aliases from `indexes/terminology.yaml`, `query/terminology.yaml`, or
   `registry/aliases.yaml`

Use only the current KB manifest, terminology/indexes, raw and derived graphs,
formal facts, and recorded source anchors.

## Read Order

For every answer:

```text
1. indexes/terminology.yaml and indexes/symbol_index.yaml
2. graphs/derived/**
3. graphs/raw/**
4. source YAML facts under facts/**
5. source anchors referenced by those facts
```

Use:

```powershell
python "$SCRIPT_DIR/uo_query_readonly.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --entity "<ID_OR_LABEL>"
```

If the KB is missing, tell the user to run `/uo-init`; do not scan source trees
or create an empty `.understand-operator/<token>/` directory.

## Source Verification

Only use source anchors already present in YAML or indexes. If more source proof
is needed, query MCP `codebase-memory-mcp`; do not run local shell CLI
fallbacks, or broad source grep.

## Answer Style

Answer in Chinese by default. Include:

- direct conclusion
- KB graph/YAML references used
- source anchor references when available
- confidence and unresolved items

State clearly when the KB lacks the requested fact.

# Query backend

`uo_query_readonly.py` uses `indexes/operator_kb.sqlite` first (aliases/FTS,
derived entities, raw entities, then the small set of `detail_ref` documents).
It refuses a stale index and reports `index_status: stale`; YAML graph fallback
is used only when the SQLite index is absent and is labelled
`query_backend: yaml_fallback`.

Supported limits are `--depth 0..2`, `--relation-type`, and `--limit`.
