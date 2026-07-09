# CBM-First Code Lookup Rule (mandatory)

This is the **global underlying rule** for every `uo-*` command and every subagent.

## Rule

When looking up **source code** (find symbol, read implementation, trace calls, verify a code claim):

1. **CBM first** — run `cbm_query.py` / `uo-cbm` (`search_graph`, `search_code`, `get_code_snippet`, `trace_path`, …).
2. **Only if CBM fails** (empty result, error, or incomplete macro/template/string coverage) may you fall back to reading source files.
3. Fallback order after CBM failure:
   - Prefer **line-scoped** `Read` when CBM already returned a file+line.
   - If CBM returned nothing useful, you may **read the whole file** as last resort.
4. **Never** open source files before attempting CBM for a code lookup.
5. Record the failed/empty CBM query in `cbm/query_journal.jsonl` (default) or in the answer evidence before whole-file fallback.

## Not covered by this rule

- Reading existing KB artifacts under `.understand-operator/<op_name>/` (YAML/MD) — these are **not** source lookups; read them freely.
- Reading prompt/contract files inside the plugin.

## Windows / PowerShell

Prefer shorthand flags; do not pass raw JSON as a positional argument:

```powershell
python "<abs>/cbm_query.py" "<PROJECT_ROOT>" search_graph --op-name "<OP_NAME>" --name-pattern ".*MyOp.*" --label Function
python "<abs>/cbm_query.py" "<PROJECT_ROOT>" search_code --op-name "<OP_NAME>" --code-pattern "tiling_key"
python "<abs>/cbm_query.py" "<PROJECT_ROOT>" get_code_snippet --op-name "<OP_NAME>" --file op_host/foo.cpp --symbol MyOpTiling
```

For detailed tool syntax, load `prompts/00_cbm_on_demand.md` only when needed.
