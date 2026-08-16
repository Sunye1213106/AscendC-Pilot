# Lemma review — 回放裁决，不开启新假设

回放并裁决本轮 producer 提交的引理证书（轮内 expected-growth rejects，不是搜完清理）。

详见 `references/referee-replay.md`、`references/proof-obligations.md`、`references/static-evidence.md`、`references/failure-patterns.md`、`references/gotchas.md`，以及 `skills/testcase-generation/references/closure-safety.md`。

## 方法

1. 只做 replay 裁决，不开启新假设。
2. 把「搜索未命中」或「裸 Host reject」当成不可达的证书一律 `reject`。
3. 证据不足时 `defer`，禁止用猜测补全证明链。
4. 每个候选返回 `accept` | `reject` | `defer`，并附简短理由。

## 禁止

- 发明新 lead 或新 exclusion 规则
- 用搜索失败证明不可达
