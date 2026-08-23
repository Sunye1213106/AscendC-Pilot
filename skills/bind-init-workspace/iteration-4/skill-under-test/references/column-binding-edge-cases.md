# 列绑定边角

**何时加载**：调用接口对不上表头、列值是编码控制面、或查图形态写错时。

## 先调用点再表头

打开最富调用，先写 `call_args` 再写 role。传进 `torch_npu` / `aclnn` 的列是 `api_arg`，必须有 `uo_id`。`call_args.name` 用 API 形参名，不用 runner 局部变量。不要用 `attr`。`call.kind` ∈ {`pta`, `aclnn`, `mixed`}。

`.pt` 加载不改变维 / dtype / layout 列的 `api_arg`。最富调用里出现的 kwargs，同名表列仍是 `api_arg`（表全空或值从 `.pt` 来也一样）。查不到图上的 AttrIndex 也不能改成 `script_meta`。

## 值域两源

`domains.profile` 引用 `tables[].profile`（range，不通读 CSV）。`domains.operator` 只对已是 `api_arg` 的列：填该列短名。覆盖列表 `Dim=<维名>` 仅当该列本身就是那个开关。只在某种模板/layout 下才出现的列，仍绑该列自己的短名，不要把开关维写成它的 `operator`。`compare=match` 仅当 `operator` 非空。`compare` ∈ {`match`, `tighter_profile`, `tighter_operator`, `mismatch`}。

## 查图只为 uo_id

role 冻结后再对名。必须先做一次无参 `uo-query`（开关维以这次查询为准）。字段名直接 Read session `refs/bind/name-index.md`，不要 Glob；没有这份文件才读一次头文件。然后只在名单里挑，不要按列回头 Grep。该列是某个 kwargs 的 `source_column` 则**必须**有短名：优先字段名同名，否则 `uo_id` 就是该 `call_args.name`，禁止空、禁止为此 PARTIAL。列只是公式输入则抄本列对应的维/字段。开关维不是 dtype 列的身份。改写 mask/flag 生成的列抄字段名单里的该对象（含 inner/outer），不要抄 keep/prob。对不上时 findings 写 PARTIAL，格子留空，不借邻居短名。Enable / 用例名 / 是否跑行 才是 `script_meta`；确定性一类运行上下文是 `feature`。追列时以读表函数为准。落盘写 `parts/bind.fill.yaml`，不要 Edit `bind.yaml`。

改写列（本身不在实参里，只截短 / 过滤 / 重映射另一列）是 `feature`。头文件字段必须表示同一量才抄进 `uo_id`；同一开关的两侧仍抄该字段。词形相近但量不同就留空，也不要抄被改写列的短名。无参查询里的开关维只写到「列本身就是该开关」的 `operator`，不要写到只在该开关下才出现的列，也不要写到 dtype 列的 `operator`。

`uo_id` 填短名 / `canonical`，禁止 `TDF::` id 和 `tiling_data_names` 结构名。尺寸列绑「这一列对应的维/字段」，不要绑调用里的张量操作数名。dtype 与 shape 不许共一个 `uo_id`。未从卡片复制 `file:line` 时禁止 around。

## 编码

列值可能是前缀和、打包 flag、枚举别名。每个非平凡列写一句 `encoding`。不要按列名字面理解成物理量。
