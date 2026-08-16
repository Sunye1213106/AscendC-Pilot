# CE apply — 按已锁定 spec 改算子源码

对照已确认的意图与锚点修改 `op_host/` / `op_kernel/`。改完立刻停；审查和刷 CodeMap 由后续步骤做。

详见 `references/gotchas.md`、`references/risk-classes.md`。

## 方法

1. 先读意图、特性清单和锚点，再开最小源码窗。只改锚点覆盖到的文件。
2. 验收先行：能对应意图里的 UT/ST/场景 knobs 再动代码。一次一个垂直切片。
3. 每个改动点留下 `path:line`。超出锚点的文件不要写。
4. 写完列出改了哪些路径，并写入 `ce/apply/patch_notes.yaml`；不要宣布义务已关闭。

## 禁止

- 写 `.uo` 或 CE 证书
- 把审查叙述当成测量收据
- 用通用实现流程绕过已定位锚点
