# CBM-First Code Lookup Rule (mandatory)

This is the **global underlying rule** for every `uo-*` command and every subagent.

## Rule

When looking up **source code** (find symbol, read implementation, trace calls, verify a code claim):

1. **CBM MCP first** — call the `codebase-memory-mcp` MCP server tools:
   - `search_graph`
   - `search_code`
   - `get_code_snippet`
   - `trace_path` (alias: `trace_call_path`)
   - `query_graph` / `get_architecture` / `detect_changes` when needed
2. **Only if CBM MCP fails** (tool missing, empty result, error, or incomplete macro/template/string coverage) may you fall back to reading source files.
3. Fallback order after CBM failure:
   - Prefer **line-scoped** `Read` when CBM already returned a file+line.
   - If CBM returned nothing useful, you may **read the whole file** as last resort.
4. **Never** open source files before attempting CBM MCP for a code lookup.
5. **Never** `Grep` / ripgrep operator `*.cpp` / `*.h` before CBM MCP. Grep is a fallback after CBM failure, not a substitute for `search_code` / `search_graph`.
6. **Do not** use `cbm_query.py` / `uo-cbm` / `codebase-memory-mcp cli` for indexing or lookups. `/uo-init` Phase 0 must call MCP `index_repository` to build the graph DB. Interactive `/uo-*` must use the MCP server.

## Not covered by this rule

- Reading existing KB artifacts under `.understand-operator/<op_name>/` (YAML/MD) — these are **not** source lookups; read them freely.
- Reading prompt/contract files inside the plugin.

## Anti-patterns (seen in bad /uo-query runs)

- Glob `*tiling*.cpp` → Read whole file → Grep headers for constants — **forbidden** without prior CBM MCP.
- Using Grep because CBM “might be slow” — **forbidden**.
- Shelling out to `python .../cbm_query.py` when MCP tools are available — **forbidden** (slower cold-start path).
- KB shows `medium` / `needs_alignment` / Caveat naming a symbol, then answer with `源码查找: KB-only` — **forbidden**. Must CBM-verify that symbol before final answer.
- Skipping CBM verification to “save steps” when confidence is not high — **forbidden**.

## /uo-query intent

KB is for **fast draft**. CBM MCP is for **targeted verification** when the draft is uncertain. Whole-file Read is last resort after CBM failure — not the verification method.

## MCP tool cheat sheet

| Goal | MCP tool | Typical args |
|---|---|---|
| Find function/class | `search_graph` | `name_pattern`, optional `label` (`Function`) |
| Find string/macro | `search_code` | `pattern` |
| Read function body | `get_code_snippet` | qualified `symbol` (discover via `search_graph` first) |
| Call chain | `trace_path` | `function_name`, `direction`, `depth` |
| Index status | `index_status` / `list_projects` | `repo_path` or project |

If MCP server `codebase-memory-mcp` is not connected, tell the user to install/configure it (see README / `docs/cbm-mcp-setup.md`) — do **not** silently fall back to whole-tree Grep.
