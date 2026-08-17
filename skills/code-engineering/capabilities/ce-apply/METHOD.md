# CE apply — 按已锁定 plan 改算子源码

对照 `ce/intent/plan.md`（或简单需求的 `ce/apply/todo.md`）修改 `op_host/` / `op_kernel/`。一次一个垂直切片。改完立刻停；审查和刷 CodeMap 由后续步骤做。

详见 `references/gotchas.md`、`references/risk-classes.md`。

## 方法

1. 先读 `ce/intent/plan.md` 与 `ce/apply/todo.md`，再开最小源码窗。只改本次切片覆盖到的文件。
2. 验收先行：当前切片的验收条件必须能在 plan / todo 里找到，再动代码。一次只做一个未勾选的 todo 项。
3. 每个改动点留下 `path:line`，并写明对齐了 plan / todo 的哪一条。
4. 写完列出改了哪些路径，勾选 `ce/apply/todo.md` 对应项，并写入 `ce/apply/patch_notes.yaml`；不要宣布义务已关闭。不要读 intent.yaml / feature_decomposition / anchors YAML。

## 禁止

- 写 `.uo`、写 `ce/intent/plan.md`、或签发 CE 证书
- 把审查叙述当成测量收据
- 用通用实现流程绕过已定位锚点或未勾选切片
