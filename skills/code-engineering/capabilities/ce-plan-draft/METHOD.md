# CE plan draft

把已问清的需求写成一份命名计划 markdown。这是 CE 给人看的正式产物。

路径：`<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/ce/plan/{slug}_plan.md`

形状参考 `examples/deter-band-schedule_plan.md`。不要把它当运行时真值。

## 必须包含的节

1. **实现分析**：跨层真值来自 `uo-query` 标识符查询，不是扫 host_view。列出会改的源码路径（`op_host/` / `op_kernel/` / `common/` / `test_script/`）。写明不做的范围。
2. **计划**：分步怎么改。
3. **Todo**：可勾选 `- [ ]` 列表，一次 apply 做一个。
4. **测试内容**：应覆盖的字段/开关、不要扩成全量 TilingKey、不要按误报维铺用例。`/tg-plan` 会读这一节自己总结义务。

## 方法

1. 读 grill `staging.md`。用 `uo-query` 形态 1/2/4 核对字段与邻域。
2. 选一个短 slug（小写、连字符），只写这一份 `*_plan.md`。
3. 文件路径写进反引号，便于 apply 的 patch_guard 收集声明文件集。

## 禁止

- 写 yaml、`todo.md`、`anchors.yaml`、`tg_plan_intent.yaml`
- 以 PR / diff 当输入
- `acp uo impact` / `explain-*`
