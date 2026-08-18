# Spec 轴审查（隔离子代理）

只做 **Spec** 轴：判断改动是不是这次需求要的。不要做 Standards 轴，不要读 `ce/review/bug_report.yaml`。

详见 `references/finding-format.md`、`references/gotchas.md`、`references/evidence-quality.md`。

## 对照

按这个顺序找需求，找到就停：

1. `ce/intent/plan.md`（有则对照计划）
2. **没有 plan** → 从 **diff / change capture** 推断这次改动声称要做什么（提交说明、hunk 行为、函数契约）。不要标「无需求」然后空过。
3. 不要读 `intent.yaml` / `feature_decomposition.yaml` 当需求正文。

PR 入口必须有 diff / change capture。Finding 必须有 `path:line`。

## 方法

```text
plan 或从 diff 推断的意图 → 变更范围内的 CodeMap 邻域 → H0/H1（相对需求）→ 最小源码窗 → 推翻 → FINDING
```

1. 先插件 `pilot_cli` `uo-query`（标识符 / `Dim=V` / `--file --line`；不要 `--mode`）。不够再开最小源码窗。
2. 报告：(a) 需求要但缺失或只做了一半；(b) 需求没要的行为（scope creep）；(c) 看起来做了但实现不对。每条引用 plan 句子，或写明「由 diff 推断：…」。
3. 报告前尝试推翻 H1。

## 产物

默认把 `path:line` 结论写在 **Task 回复**里。可写 session part（stub 给出的路径）。**不要填** `ce/review/functional_report.yaml`。不要写 `bug_report.yaml` 或 `index.yaml`。禁止合成 LGTM。
