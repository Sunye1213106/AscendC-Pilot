# input_derivable 断边 — 不在 uo-query 处理

**短指针：** 建库期 `input_derivable` 图断边请看：

`skills/uo-init/references/uo-input-derivable-resolve.md`

## 边界

| 阶段 | 谁处理 | 禁止 |
|---|---|---|
| `/uo-init` 建库期 | `uo-semantic-resolve` + CBM | **禁止**派发 per-KEY `uo-query` |
| KB 定稿后 | `/uo-query` 只读问答 | 不在 uo-query 修补 `input_derivable_gaps` |

## 紧凑产物（init 侧）

- `host_parent`：一跳 writer / set_by 上级 symbol
- `derivation_roots`：闭合时的输入面节点
- **禁止**完整 `host_derivation_chain` / 长 `function_chain` dump

沿 KB 图 `determined_by` 逐跳 walk，勿把整条 chain 写入契约或 TG prompt。
