# Case study: accepted-but-undeclared dispatch（历史）

> 人类溯源材料。Agent 默认不读。方法见 `skills/code-review/references/cross-layer-contracts.md`。

## 一句话

某算子在特定 dtype + optional feature 组合上：Host 接受并编码 dispatch key，但 Kernel/TPL 实现声明空间中不存在对应实例 → **accepted-but-undeclared** 运行态。

## 为何值得留下

它不是单测编解码错误，而是跨层支持集合不一致：

```text
Interface/validation 允许
  → Host 编码成功
  → implementation declarations 无该组合
```

通用模式已蒸馏进 `cross-layer-contracts.md`（无算子字段名）。

## 历史材料位置

- 原 bug report（git 历史，已从工作树删除）：`docs/debug/bug_report_fag_fp32_rope_undeclared_key.md` @ pre-`ed73e9c`
- 闭合报告中的 undeclared 讨论（历史材料，不当权威）：[`../fag_test/tilingkey-closure-report.md`](../fag_test/tilingkey-closure-report.md)
