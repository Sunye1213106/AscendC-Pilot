# CBM First Rules

Use the tool that matches the question type.

Repository structure, file paths, include/import directives, and build files use deterministic filesystem tools first: `Glob`, `rg --files`, `rg -n`, or line-scoped reads.

Symbol definitions, references, caller/callee relations, registration mappings, template instances, Host/Kernel correspondence, and semantic behavior claims use `codebase-memory-mcp` first.

Precise source text is read only after CBM or deterministic scope resolution identifies a bounded file and line range.

If CBM is incomplete, fall back only to precise `rg` and line-scoped reads inside the Phase 0 approved scope.

If a claim cannot be proven, write it to `unresolved`.

Forbidden:

- Unbounded semantic grep across the whole repository.
- Treating a text hit as a confirmed semantic fact.
- Using local CBM CLI fallback commands instead of the connected MCP server.
- Modifying the CBM database from an agent.
- Automatically admitting out-of-scope files into Phase 1+.

Phase 0 indexing must use the connected `codebase-memory-mcp` MCP server and record `cbm/index_meta.json` with `indexed_via: mcp`.

