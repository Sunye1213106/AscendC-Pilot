# Semantic residual investigation

调查 `ir/unresolved.yaml` 中的 residual；分类根因，给出 deterministic engine 改进建议。
**不得**把 LLM 推断写入 canonical `.uo`。

## When to use

- `/uo-investigate`
- 用户问某个 TilingKey / field / call 为何 unresolved
- 需要评估 analyzer 缺什么 pass（loop summary、opaque op 等）

## Method

1. 读取 blocker + CodeMap 查询 + 最小源码窗口
2. 分类：`deterministic_engine_gap` / `unsupported_operator` / `needs_loop_summary` / …
3. 产出调查报告与 suggested engine fix；保留 unresolved

## Hard limits

- 不得伪造闭合关系
- 不得产出可 merge 的 gap patch 进 canonical IR
- 不得处理目标集外 ID

证据硬规则见 policy `evidence`。
