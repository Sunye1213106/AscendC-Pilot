# Third-Party Binaries

`understand-operator` uses `codebase-memory-mcp` as the preferred code intelligence backend.

This directory is intentionally ignored by git. Put the binary here if you do not want to install
it globally:

- Windows: `thirdparty/codebase-memory-mcp.exe`
- macOS/Linux: `thirdparty/codebase-memory-mcp`

You can also set `UNDERSTAND_OPERATOR_CBM_BIN` or configure `[scanner].cbm_binary` in a target
repository's `.understand.toml`.
