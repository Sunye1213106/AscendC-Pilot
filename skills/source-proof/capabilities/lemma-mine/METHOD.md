# Lemma mine — 轮内证明或反驳

对本轮 Round Analysis 给出的源码引理线索做证明或反驳（轮内 claim，不是搜完后的清理）。

权威闭合证据只有 Host Replay（R）与经审查的源码引理（E）。搜索失败或裸 Host reject 本身不等于不可达。

详见 `references/proof-obligations.md`、`references/failure-patterns.md`、`references/static-evidence.md`、`references/gotchas.md`。闭合不变量见 `pilot/domain-contracts/closure-safety.md`（由 Context Profile 物化 owner 文件，禁止打开 testcase-generation SKILL）。

## 方法

1. 只处理 closed lead pack 中的线索，禁止发明新 lead；有 companion evidence pack 时一并使用。
2. 优先对照最新一轮 Host `refuse` / rewrite 观察与 `round_analysis.yaml` 模式。
3. 主动寻找反例；按 `references/proof-obligations.md` 关闭证明义务。
4. 每个候选给出 `PROVED` | `REFUTED` | `INSUFFICIENT`，并附源码窗口。只写入本 Action 的 `parts/` 草稿。

## 禁止

- 把 missing / search failure / replay reject 单独升级为 exclusion
- 写正式 closure IR
