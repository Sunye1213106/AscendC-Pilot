# 列绑定边角

**何时加载**：6 步与现场脚本冲突时。本路只改 FOCUS 里的 `bindN.yaml`。`call_args.sources` 只点名本路 mapping 列；草稿里已有 `call` 与 arg 名。

本页是主文的例子，不是第二套规则。分类、对名、禁止追加 `call_args` 只认 `columns.md`。

## 调用点仍是唯一入口

先写 `call_args.sources[]` 再写 `control` / `relation`。禁止造伪 kwargs。禁止用 AttrIndex / `dim_names` 有无改 `control.status`。某 mode 省略了 kwargs → findings 记未接线，列仍按草稿 `call_args` 分类。

`call.kind` ∈ {`pta`, `aclnn`, `mixed`}。不要写 `attr` 或 `pta_direct`。

## 空列、改写、运行上下文

全空且 runner 从另一列重算 → 空列 `shadowed`。`call_args.sources[]` 仍点名该列 → 必须 `active`。调用里根本没有该实参 → `unwired`。

Enable / 用例名 / 是否跑行 → `metadata` + 空 relation + `unresolved`，禁止 `uo.id`。

确定性 / 设备等运行上下文：不进 kwargs 但 host 会读 → `active` + `derived`，绑无参查询里的那一维。不要标 metadata。

改写列（截短 / 过滤 / 重映射另一列）→ `active` + `derived`，绑被改写对象，不借邻居。

## 张量多源与身份

一个张量实参对应多列时，全部进该 arg 的 `sources[]`。不要挑一列当「这个张量的 uo.id」。输出 dtype 若只做 `tensor.to(...)` → `tensor_dtype`，不是 `direct`。

尺寸列绑本列对应的维，不要绑派生 kwargs（scale 一类），也不要把尺寸列写进该 kwargs 的 `sources[]`。标量 kwargs source 的入边数规则见主文。

## 查图只为闭合链路

仅 `active` 之后才 `uo-query`。必须先做一次无参查询。尺寸列用列名查，只取 `TILING_FIELD.name`。

`uo.id` 填短名 / `canonical`。只碰到相似符号且该列没有标量 kwargs source → `uo.candidate` + `unresolved`。

projection 写在 `domains.projection`。不要改引擎写入的 `domains.profile`。`compare=match` 仅当 `operator` 非空。
