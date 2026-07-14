# CBM On-Demand Query Protocol (MCP)

Use CBM only through the connected MCP server `codebase-memory-mcp`. There is
no local CBM CLI fallback in this plugin.

## When To Use MCP

| Scenario | MCP usage |
|---|---|
| `/uo-init` Phase 0 indexing | `index_repository` over resolved scope roots |
| `/uo-update` refresh/change detection | Disabled; rerun `/uo-init` for a new source snapshot |
| Symbol, call, registration, or semantic lookup | `search_graph`, `search_code`, `get_code_snippet`, `trace_path` |
| KB directory creation | `prepare_operator.py` only; it does not create the graph DB |
| Project metadata | `prepare_operator.py --write-index-meta --cbm-project ...` |

## `/uo-init` Phase 0 Order

```text
prepare_operator.py
deterministic scope discovery and dependency closure
MCP index_repository over resolved scope roots
MCP list_projects or index_status confirmation
prepare_operator.py --write-index-meta --cbm-project <name>
```

`cbm/index_meta.json` records the CBM project name, indexed scope roots,
dependency roots, scope hash, and `cbm_status`.

## Evidence Order

1. Use deterministic Phase 0 files for approved scope and run context.
2. Use MCP for symbols, calls, registration semantics, IO semantics, and source
   behavior validation.
3. Use targeted file reads or `rg` only inside approved scope roots.
4. If MCP is unavailable after one retry, record degraded mode and continue only
   when the current phase allows filesystem fallback.

## Degraded MCP Status

Record MCP failures instead of pretending the query succeeded:

```yaml
cbm_status:
  available: false
  retry_count: 2
  fallback: filesystem_scan
  reason: MCP connection closed
```

Semantic enrichment query records may omit confidence when the tool fails, but
they must include the tool name, query or payload, status/error information, and
the fallback decision.
