只做 **Spec** 轴：判断改动是不是这次需求要的。不要做 Standards 轴。

详见 `references/finding-format.md`、`references/gotchas.md`、`references/evidence-quality.md`。

## 对照

1. 有当前 `ce/plan/{slug}_plan.md` 则对照该计划（todo 是否做完、有无超范围）。
2. 纯 PR、没有计划时只陈述变更理解，不假装有计划。
3. 不要读任何 CE yaml。

PR 入口必须有 diff。Finding 必须有 `path:line`。

## 方法

```text
plan 或变更理解 → uo-query --file --line 再标识符 → H0/H1 → 最小源码窗 → 推翻 → FINDING
```

1. 先插件 `pilot_cli` `uo-query`（形态 3 再形态 1）。禁止 `acp uo impact` / `explain-*`。
2. 报告：(a) 计划要但缺失或只做了一半；(b) 计划没要的行为；(c) 看起来做了但实现不对。
3. 报告前尝试推翻 H1。

## 产物

`path:line` 结论写在 **Task 回复**里。可写 session part（stub 给出的 md 路径）。禁止 Write `ce/**`。禁止合成 LGTM。
