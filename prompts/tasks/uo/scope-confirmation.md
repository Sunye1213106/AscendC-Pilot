<task>
（已降级）`prepare` 不再做人工文件清单确认。本 prompt 仅作历史兼容说明，正式路径不加载。
</task>

<context>
用户已指定 `operator_root` + `architecture`。UO 由机器建立 Source Scope（layout bootstrap + Clang include closure），并校验 Build Context。
失败记为 blocker，不询问「这些文件是不是你要分析的」。
</context>

<instructions>
1. 不要手工构造源码清单，不要让用户确认候选文件列表。
2. 若仍被错误派发到本 prompt：检查 `prepare` 是否应为 `deterministic`，并回报 SCOPE_VALIDATE_BLOCKED。
3. 唯一可向用户索取的输入是缺失的 operator 根目录或 architecture；不是文件列表。
</instructions>

<output>
不产出人工 scope 决策。正式产物由 `scope_validate` 写入 `scope_confirmed.yaml`（`source: machine`）。
</output>
