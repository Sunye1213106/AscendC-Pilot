# Query primitives

语义走 `pilot_cli uo-query`，不要封装第二套图 walker。形态与禁止项见 code-access 不变量。

Hits 是投影后的卡片（`id/kind/name/file/line` + 少量 `facts`），不是整份 `entity.data`。禁止调用已删除的 `slice_forward` / `slice_backward`。预算截断不能证明「没有影响」——标未决，不要写成无义务。
