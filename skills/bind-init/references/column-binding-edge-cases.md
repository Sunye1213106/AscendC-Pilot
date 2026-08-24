# 列绑定边角

**何时加载**：6 步与现场脚本冲突时。本路只改 FOCUS 里的 `bindN.yaml`。`call_args` 仍写最富调用全貌；mapping / domains 只填本路列。

与 [columns.md](columns.md) 冲突时以本页为例外，不要另起一套 role / `source_column` 世界观。

## 调用点仍是唯一入口

打开最富调用，先写 `call_args.sources[]` 再写 `control` / `relation`。禁止造伪 kwargs。禁止用 AttrIndex / `dim_names` 有无来改 `control.status`。`.pt` 加载不把维 / dtype / layout 列改成 metadata 或 unwired：该张量已在最富调用里，对应列仍是 `active`。某 mode 省略了 kwargs → findings 记未接线，列仍按最富调用分类。

`call.kind` ∈ {`pta`, `aclnn`, `mixed`}。不要写 `attr` 或 `pta_direct`。

## 空列、改写、运行上下文

当前 corpus 全空、runner 从另一列重算 → 空列 `shadowed`，源列才是 `active` + `derived`。API 语义对但表全空 → `unwired`，先修 harness。

Enable / 用例名 / 是否跑行 → `metadata` + 空 relation + `unresolved`，禁止 `uo.id`，禁止 `confirmed`。

确定性 / 设备等运行上下文：不进 kwargs，但 host 会读（如 GetDeterministic）→ `active` + `derived`，`uo.id` 绑无参查询里的那一维。不要标 metadata。

改写列（不在实参里，只截短 / 过滤 / 重映射另一列）→ `active` + `derived`，绑被改写对象的字段，不借邻居、不抄 keep/prob。

## 张量多源与身份

一个张量实参对应多列时，全部进该 arg 的 `sources[]`（`tensor_shape` / `tensor_dtype` / layout）。不要挑一列当「这个张量的 uo.id」。dtype 与 shape 不许共一个 `uo.id`。开关维不是 dtype 列的身份，也不进它的 `operator`。

尺寸列绑本列对应的维/字段，不要绑调用里用它算出来的派生 kwargs（scale 一类），也不要绑张量操作数名或 `*TemplateNum`。若该列出现在标量 kwargs 的 `sources[]`，`uo.id` **等于** 该 `call_args.name`，不要改走维字段候选、不要只放 `candidate`。

输出 dtype 列若只做 `tensor.to(...)` 间接进调用 → `tensor_dtype`，不是 `direct`。若调用根本没有该实参、只进比对 JSON → `unwired`（不要因为图上有 Out/Input DType 开关就标 active）。

## 查图只为闭合链路

仅 `control.status: active` 之后才 `uo-query`。必须先做一次无参查询（只认开关维）。不要 `Dim=`。不要用 `dim_names` 当尺寸/dtype 查询词。尺寸列用列名查，只取 `TILING_FIELD.name`。

`uo.id` 填短名 / `canonical`，禁止 `TDF::` 和 `tiling_data_names` 结构名。只碰到相似符号且该列**没有**标量 kwargs source → `uo.candidate` + `unresolved`。标量 kwargs 的 source 列：`uo.id` 等于 `call_args.name` 并 `confirmed`；Edit 后按 call_args 回扫，空 id 不许 inspect。

projection（layout 列 → 开关维）写在 `domains.projection`，不要当 equality 控制、不要当另一列的 `uo.id`。

`domains.profile` 引用 `tables[].profile`，不要改引擎已写入的 profile。`compare=match` 仅当 `operator` 非空。
