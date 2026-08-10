# resolve

只消解 `analyze` 明确产出的 unresolved semantic gaps。

Agent：`uo-semantic-resolver`。Task prompt：`uo/resolve-gaps`。Producer 只写当前 Action Bundle 允许的 staging parts；确定性 `apply_gap_patch` 负责校验并合并。

不要重新执行确定性抽取，不要处理未分配的 gap，不要直接写 canonical `.uo` / UO IR。
