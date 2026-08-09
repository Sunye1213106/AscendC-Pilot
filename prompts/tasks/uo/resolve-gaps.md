<task>
只处理当前 Action Bundle 分配的 unresolved CodeMap semantic gaps。
</task>

<context>
确定性 CompilerFacts 与 CodeMap Pass 是默认事实来源。你的职责是补充它们无法可靠闭合、且当前 bundle 明确分配给你的语义缺口。
</context>

<instructions>
1. 读取当前 gap/batch identity、已有 relation 和 provenance。
2. 使用结构化 CodeMap 查询定位最小证据面；必要时再读取最小源码窗口。
3. 只有直接证据足够时才产出 staged relation/attribute patch，并保留证据位置。
4. 证据不足时保留 unresolved，写明 blocker 与缺少的证据，不猜测、不补笛卡尔积关系。
5. 若根因是 frontend / deterministic pass 漏抽或错误归一，标记 deterministic rework；不要用模型结果掩盖确定性缺陷。
</instructions>

<output>
只写当前 Output Contract 允许的 staging part。不要修改 canonical `.uo` / UO IR，不要 finalize Action，不要处理 bundle 之外的 gap。
</output>
