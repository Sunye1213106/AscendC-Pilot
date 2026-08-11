<task>
（已移出默认 `/uo-init`）历史 resolve-gaps 任务壳保留仅供 debug。
默认请使用 `/uo-investigate` + `uo/investigate-gaps`。
</task>

<context>
Canonical `.uo` = Compiler truth + deterministic derivation。
LLM 不得把 semantic patch 写进产品面。
</context>

<instructions>
1. 若目标是理解 unresolved：改走 investigate，输出根因分类与 engine 改进建议。
2. 若被显式要求 debug 草案区：只写草案区产物，不得合并进 canonical IR。
3. 证据不足时保留 unresolved；不得猜测闭合。
</instructions>

<output>
优先产出调查报告；禁止写入 canonical `.uo`。
</output>
