# Policy: source-authority

## Purpose

统一权威源优先级，防止模型记忆与命名猜测覆盖证据。

## Priority (high → low)

1. 当前源码（定向 `path:line` 阅读）
2. 当前确定性产物（Pilot 签发收据、Checker 报告、引擎输出）
3. 当前 UO / TG KB（定稿或本 run 内 IR）
4. 模型记忆与命名直觉

## Hard Constraints

- MUST：高优先级证据冲突时，以更高优先级为准并记录冲突。
- MUST：声称「已核对源码」时，证据层级必须落到第 1 级（定向 `path:line` 窗口），并满足 `evidence` 策略的 snippet 磁盘比对。
- MUST NOT：用模型记忆或命名猜测闭合 KEY / 合同字段。
- MUST NOT：用候选表 / 搜索摘要当作第 1 级源码权威。
