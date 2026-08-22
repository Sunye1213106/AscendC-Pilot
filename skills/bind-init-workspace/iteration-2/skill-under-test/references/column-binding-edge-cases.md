# 列绑定边角

**何时加载**：调用接口对不上表头、列值是编码控制面、或查图形态写错时。

## 先调用点再表头

打开最富调用，先写 `call_args` 再写 role。传进 `torch_npu` / `aclnn` 的列是 `api_arg`，必须有 `uo_id`。不要用 `attr`。`call.kind` ∈ {`pta`, `aclnn`, `mixed`}。

`.pt` 加载不改变维 / dtype / layout 列的 `api_arg`。查不到图上的 AttrIndex 也不能改成 `script_meta`。

## 值域两源

`domains.profile` 引用 `tables[].profile`（range，不通读 CSV）。`domains.operator` 只对已是 `api_arg` 的列：填该列短名。覆盖列表 `Dim=<维名>` 仅当该列本身就是那个开关。只在某种模板/layout 下才出现的列，仍绑该列自己的短名，不要把开关维写成它的 `operator`。`compare=match` 仅当 `operator` 非空。`compare` ∈ {`match`, `tighter_profile`, `tighter_operator`, `mismatch`}。

## 查图只为 uo_id

role 冻结后对名：先读一次 tiling 头文件，得到本次短名全集。该列是某个 kwargs 的 `source_column` 才抄那个 kwargs 的短名；列只是公式输入则抄本列对应的维/字段。对不上时 findings 写 PARTIAL，格子留空，不借邻居短名。头文件有哪些字段以这次打开的文件为准。

改写列（本身不在实参里，只截短 / 过滤 / 重映射另一列）是 `feature`；头文件里的开关字段有就填 `uo_id`，没有就留空，不要抄被改写列的短名。

`uo_id` 填短名 / `canonical`，禁止 `TDF::` id 和 `tiling_data_names` 结构名。尺寸列绑「这一列对应的维/字段」，不要绑调用里的张量操作数名。dtype 与 shape 不许共一个 `uo_id`。未从卡片复制 `file:line` 时禁止 around。

## 编码

列值可能是前缀和、打包 flag、枚举别名。每个非平凡列写一句 `encoding`。不要按列名字面理解成物理量。
