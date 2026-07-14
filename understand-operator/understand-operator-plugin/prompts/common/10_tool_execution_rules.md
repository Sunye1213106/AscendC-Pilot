# Tool Execution Rules

Use the frozen Phase 0 scope before opening source files. Read
`runs/<run_id>/phase0/receipt.yaml`, `scope_scan.yaml`,
`semantic_enrichment.yaml`, and `cbm/index_meta.json`; do not rediscover the
repository shape with broad recursive scans.

Prefer tools in this order:

1. Phase 0 facts and approved scope.
2. Targeted `Read`, `Glob`, and `Grep`/`rg` inside approved include paths.
3. MCP `codebase-memory-mcp` for symbols, calls, registration semantics, IO
   semantics, and behavior checks.

Forbidden tool patterns:

- Full repository or whole-disk recursive scans unless Phase 0 is currently
  creating the scope.
- Counting all source lines or listing all files when the Phase 0 scope already
  has the needed files.
- In Windows PowerShell, do not call nested `powershell -Command`. Run the
  command directly in the current shell.
- Repeating the same failing tool call more than once. After one retry, record
  an `unresolved` item or stop at the owning agent repair boundary.

Windows execution:

- Set UTF-8 output/input when needed with `$OutputEncoding = [Console]::OutputEncoding = [Text.UTF8Encoding]::UTF8`.
- Run Python as `python -X utf8 ...`.
- Quote paths with `-LiteralPath` in PowerShell when operating on files.
