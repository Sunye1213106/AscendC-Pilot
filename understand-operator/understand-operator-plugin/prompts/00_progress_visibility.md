# Progress Visibility Protocol

User-facing progress is Chinese and concise. Use TodoWrite titles that match
the active high-level workflow only. Internal Phase 0 steps such as path
resolution, subagent preflight, prepare_operator, CBM status checks, scope scan,
and semantic enrichment must not become separate TodoWrite items.

| id | title |
|---|---|
| `uo-p0` | Phase 0：预检、CBM 索引与范围冻结 |
| `uo-p1` | Phase 1：算子边界事实 |
| `uo-p2` | Phase 2：Host、Compute、Kernel Overview 事实 |
| `uo-p3` | Phase 3：Kernel Slice 分析 |
| `uo-p4` | Final：验证、图生成与最终门禁 |

Do not create Todo items outside the five active milestones above. Final is the
last milestone and completion stops there.

Subagents must be foreground tasks. After every subagent batch, run the
appropriate validator/review barrier before consuming its artifacts or advancing
the workflow.

When a barrier fails, keep the current phase in progress and resume the owning
subagent with the validator output. Do not summarize a failed subagent as
complete.
