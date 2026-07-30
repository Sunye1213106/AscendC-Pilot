# 导出分层 KB

> **cp 是真实 CLI。** 本 Action 走 uo_init.pilot_engines.export_kb。

## Goal

导出分层 KB（clang 确定性引擎）。

## Domain Procedure

`	ext
acp run-action export_kb --project <算子目录>
`

成功标志：finalize ok: true，并满足本 Action 的 output contract。

## Output

- 仅写 Spec / ownership 声明路径。
- 本文件不得描述 Pilot advance、complete 或其他阶段。
