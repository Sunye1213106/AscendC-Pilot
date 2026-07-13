# Tool Selection Rule for Source and Scope Work

This is the global rule for every `uo-*` command and every subagent. It replaces
the old absolute "all source lookup must use CBM first" wording with a
question-type decision rule:

- Repository structure, file boundaries, path membership, generated/test/sample
  classification, and raw text occurrence locations use deterministic
  filesystem tools first.
- Symbol resolution, call relations, registration semantics, IO semantics,
  Host/Kernel correspondence, and source-backed behavior claims use
  `codebase-memory-mcp` first.

CBM is still mandatory for semantic source analysis. This rule only permits
filesystem-first discovery for macro scope and file-boundary work.

## 1. Filesystem Discovery Questions

The following are not semantic code queries. Prefer deterministic repository
traversal and text search inside `$PROJECT_ROOT`, with ignore rules applied:

- Which directories and files exist in the repository.
- Which paths belong to `op_host`, `op_kernel`, `op_api`, `proto`, `tests`,
  `examples`, `golden`, docs/config, generated/build output, or unknown groups.
- Which file or directory names contain architecture markers such as `arch22`,
  `arch35`, `regbase`, SoC names, or architecture condition markers.
- Where a literal string, macro name, architecture marker, or entrypoint-looking
  text occurs.
- Which files are likely generated, test/sample, legacy, build output, or large.
- Building the complete candidate file list for Phase 0.5 Macro Scope Review.

Preferred tools:

```text
Glob
filesystem listing
Get-ChildItem
find
rg --files
rg -l
rg -n
```

Recommended bounded commands:

```powershell
rg --files "$PROJECT_ROOT"
rg -n -i "arch22|arch35|regbase|ASCEND[0-9_]+" "$PROJECT_ROOT"
rg -n "REGISTER_TILING|REGISTER_OP|TILING_KEY_IS|GET_TILING_DATA|__global__" "$PROJECT_ROOT"
```

If `rg` is unavailable, fall back to ignore-limited `Get-ChildItem` +
`Select-String` on Windows or `find` + `grep` on POSIX. Do not scan outside
`$PROJECT_ROOT`. A scan failure records a warning and continues with the best
bounded fallback; it must not abort the workflow by itself.

Filesystem/text hits are candidate evidence only. A literal match is not enough
to mark a semantic fact as confirmed.

## 2. Semantic Source Questions

The following remain CBM MCP first:

- Where a function, class, struct, macro-like symbol, or entrypoint is defined.
- Who calls a symbol, or what a symbol calls.
- Which registration macro maps to which tiling or kernel entry.
- How Host tiling maps to Kernel dispatch.
- IO semantics, call chains, reference chains, and cross-file behavior paths.
- Reading a function implementation or validating a source behavior claim.

Preferred CBM tools:

```text
search_graph
search_code
get_code_snippet
trace_path
get_architecture
query_graph
```

Every MCP query in Phase 0.5-B and later must be grounded in at least one
already discovered candidate file, symbol, registration macro, or architecture
variant. Do not repeatedly search the whole project for the same path marker
after Phase 0.5-A has produced the candidate list.

If CBM returns empty, errors, or lacks macro/template/string coverage, fallback
to precise `rg` and line-scoped `Read` within the approved scope. Record that
fallback in warnings or evidence.

## 3. Precise Source Evidence

When the exact file and line are already known:

- Prefer `get_code_snippet`.
- If CBM cannot return the snippet, use line-scoped `Read`.
- Do not read a large whole file just because its path is known.
- Whole-file `Read` is the last resort, after targeted CBM and line-scoped
  fallback have failed or are impossible.

## 4. Tool Decision Table

| Question | First choice | Supplement / fallback |
|---|---|---|
| Which files and directories exist | filesystem / `rg --files` | bounded `Get-ChildItem` or `find` |
| Where a string or macro text occurs | `rg -n` | `Select-String` / `grep` |
| Where a symbol is defined | CBM `search_graph` | `search_code` then targeted `rg` |
| Read function implementation | CBM `get_code_snippet` | line-scoped `Read` |
| Trace call chain | CBM `trace_path` | targeted source analysis |
| Confirm registration relation | CBM plus targeted macro search | line-scoped `Read` |
| Discover architecture directories | filesystem / `rg` | CBM semantic confirmation |
| Build complete candidate scope | filesystem / `rg` | CBM enrichment |
| Validate semantic fact | CBM plus evidence | targeted `Read` |
| Query existing KB knowledge | read `.understand-operator` artifacts | no CBM required |

## 5. Forbidden Behavior

- Recursively reading all `.cpp` / `.h` files before candidate scope is known.
- Running recursive filesystem scans outside `$PROJECT_ROOT`.
- Using `rg` as a substitute for call-chain or semantic analysis.
- Guessing function semantics from file names.
- Reading a whole large file when CBM has already returned the symbol snippet.
- Using `cbm_query.py`, `uo-cbm`, or the `codebase-memory-mcp` CLI instead of
  the connected MCP server.
- Marking a semantic fact as confirmed only because a text search matched.
- Reading user-excluded paths in Phase 1 or later.

## 6. Invalid Pattern and Correct Replacement

Invalid:

```text
search_code("arch22|arch35")
-> search_code(path_filter="op_host\\.*arch35")
-> search_code(path_filter="specific file", pattern="arch35")
-> get_code_snippet(huge entry file)
-> finally Read file
```

Correct:

```text
rg --files
-> rg -n "arch22|arch35|regbase"
-> build architecture candidate list
-> query search_graph/search_code for candidate symbols only
-> get_code_snippet for precise evidence
```

If `rg` shows that `arch35` appears only in comments, do not treat that file as
an architecture implementation entry without CBM or line-scoped confirmation.

## 7. MCP Setup Boundary

`/uo-init` Phase 0 still must call MCP `index_repository` and write
`cbm/index_meta.json`. Do not silently replace a missing MCP server with CLI
indexing. If MCP is not connected, stop Phase 0 and tell the user to configure
`codebase-memory-mcp`.
