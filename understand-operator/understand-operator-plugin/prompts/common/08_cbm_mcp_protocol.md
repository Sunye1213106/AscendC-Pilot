# CBM MCP Protocol

Phase 0 indexing must use the connected `codebase-memory-mcp` MCP server. The
orchestrator records the confirmed project in `cbm/index_meta.json`.

Required metadata:

- `repo_root`
- `op_name`
- `cbm_project`
- `indexed_via: mcp`
- `cbm_mode`
- `indexed_at`

`runs/<run_id>/phase0/semantic_enrichment.yaml` records targeted CBM semantic
queries. Each query item must include the MCP tool, query payload, candidate
source file or symbol, result summary, confidence, and whether source fallback
was used.

Use CBM first for symbol definitions, callers/callees, references, inheritance,
template instantiation, registration mapping, Host/Kernel correspondence, and
semantic behavior claims. Filesystem hits from scope scan remain candidate
evidence only.

Do not use `cbm_query.py`, `uo-cbm`, or the `codebase-memory-mcp` CLI for agent
lookups when MCP tools are available. Query and quality tools remain read-only
and must not write CBM data.
