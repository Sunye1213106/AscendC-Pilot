# change-impact

根据 ChangeSet 与 CodeMap，写出这次改动影响了哪些控制路径。正式文件由 `impact_promote` 写入。

## 方法

1. 读 Goal `artifacts.changeset`（`changed_files` / `base_sha` / `head_sha`）。
2. 把改动文件/符号挂到 CodeMap 节点（Host / Tiling / Kernel）。查语义用 `uo-query`，禁止全仓 Grep。
3. 写出：
   - `changed_paths`
   - `affected`（符号或节点 id，必须在 CodeMap 或 diff 里存在）
   - `contrast`（改前/改后应能分开的条件）
   - `summary_zh` 一句人话
4. 不要做 code review，不要写测试义务（那是下一 Action）。

## 禁止

- 写正式 `control/` 或 `tg/` 产物
- 把审查意见当成测试义务
- 发明 diff 里不存在的文件
