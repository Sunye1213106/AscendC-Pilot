# Binding

把脚本仓列接到可观察的输入 / 属性 / 上下文。结果写在 **一份** `init.yaml` 的 `mapping` 里。

- 每个 mapping 必须指向脚本读点 **和** UO 节点或源码 span。
- 引擎只扫描入口/表头；怎样把列传给算子、精度 vs 性能由 Agent 读测试仓代码后写入 `init.yaml`。
- 无脚本仓 → `kind: default_input`。
- 有脚本仓但 mapping 空 → init 失败，不得 silent overwrite。
- 绑定冲突记 `findings`，不得假装已绑定。
