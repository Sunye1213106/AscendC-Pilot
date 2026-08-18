# Query primitives

语义只走 `pilot_cli uo-query` 四种形态，不要封装第二套图 walker：

- 标识符：实体卡片（定义点 + 按边类型分组的邻居 + `next`）
- `Dim=V`：模板覆盖
- `--file --line`：从位点走图（审查 diff hunk 用这个）
- 无参数：算子索引

Hits 是投影后的卡片（`id/kind/name/file/line` + 少量 `facts`），不是整份 `entity.data`。

不要传 `--mode`。禁止 `explain-*`、`search`、`locate`，也禁止调用已删除的 `slice_forward` / `slice_backward`。预算截断不能证明「没有影响」——标未决，不要写成无义务。
