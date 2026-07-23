# Policy: evidence

## Purpose

关键结论必须可追溯；禁止伪造置信度。

## Rules

1. 关键结论必须有 `path:line`、KB reference 或确定性产物证据。
2. 不能以命名猜测闭合 KEY。
3. 不能伪造 `confidence: high`。
4. 推断必须明确标记为 `inference`。
5. 证据不足时保留 `unresolved` / `needs_human`，不得猜测闭合。
6. 仅 `confidence: high` 可闭合 true / false / not_input_derivable 类字段。

## Hard Constraints

- MUST：每个闭合结论附证据类型与引用。
- MUST NOT：发明证据、行号或 KB 节点。
