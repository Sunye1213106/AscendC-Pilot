# CE apply — 按当前计划 todo 改算子源码

对照当前 `{slug}_plan.md` 的未完成 `- [ ]` 修改 `op_host/` / `op_kernel/` / `common/` / `test_script/`。一次一个 todo。改完立刻停；审查和测试由后续 slash 做。

详见 `references/gotchas.md`、`examples/deter-band-schedule_plan.md`。

## 方法

1. 先读当前 `ce/plan/{slug}_plan.md`，再开最小源码窗。只改本次 todo 覆盖到的文件。
2. 一次只做一个未勾选的 todo 项。做完把该文件里对应项改成 `- [x]`。
3. 每个改动点留下 `path:line`，并写明对齐了计划的哪一条。
4. 不要宣布测试已覆盖。不要写 patch_notes.yaml / change_capture.yaml。

## 禁止

- 写 `.uo`、任何 CE yaml、或 `ce/review/`
- 把审查叙述当成测量收据
- 超出计划声明的文件集
- 查图做语义（apply 不走 uo-query）
