# 列绑定边角

**何时加载**：6 步算法与现场脚本冲突时。本路只改 FOCUS 里的 `bindN.yaml`。`call_args` 仍写最富调用全貌；mapping / domains 只填本路列。

与 [columns.md](columns.md) 6 步冲突时以本页为例外，不要另起一套 role / `source_column` 世界观。

## 调用点仍是唯一入口

打开最富调用，先写 `call_args.sources[]` 再写 `control` / `relation`。禁止造伪 kwargs。禁止用 AttrIndex / `dim_names` 有无来改 `control.status`。`.pt` 加载不把维 / dtype / layout 列改成 metadata。某 mode 省略了 kwargs → findings 记未接线，列仍按最富调用分类。

`call.kind` ∈ {`pta`, `aclnn`, `mixed`}。不要写 `attr` 或 `pta_direct`。

## 空列与派生

当前 corpus 全空、runner 从另一列重算 → 空列是 `shadowed`，源列才是 `active` + `derived`。API 语义对但表全空 → `unwired`，先修 harness，不当 solve 控制。不进调用的 harness 标志（如 MD5 / deterministic）→ `metadata` + `uo.candidate`，禁止写成 `uo.id`。

## 张量多源

一个张量实参对应多列时，全部进该 arg 的 `sources[]`（`tensor_shape` / `tensor_dtype` / layout）。不要挑一列当「这个张量的 uo.id」。dtype 与 shape 不许共一个 `uo.id`。`out_dtype` 若只是 `.to(pttype)` 间接进调用 → `tensor_dtype`，不是 `direct`。

## 查图只为闭合链路

仅 `control.status: active` 之后才 `uo-query`。必须先做一次无参查询。`uo.id` 填短名 / `canonical`，禁止 `TDF::` 和 `tiling_data_names` 结构名。只碰到相似符号 → `uo.candidate` + `unresolved`，不要升格。projection（`Input_Layout → IsTnd`）写在 `domains.projection`，不要当 equality 控制。

`domains.profile` 引用 `tables[].profile`，不要改引擎已写入的 profile。`compare=match` 仅当 `operator` 非空。
