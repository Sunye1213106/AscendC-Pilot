# 列绑定边角

**何时加载**：调用接口对不上表头、列值是编码控制面、或查图形态写错时。

本路只改 FOCUS 里的 `bindN.yaml`。`call_args` 仍写最富调用全貌；mapping / domains 只填本路列。

## 先调用点再表头

打开最富调用，先写 `call_args` 再写 role。传进 `torch_npu` / `aclnn` 的列是 `api_arg`，必须有 `uo_id`。不要用 `attr`。`call.kind` ∈ {`pta`, `aclnn`, `mixed`}。

`.pt` 加载不改变维 / dtype / layout 列的 `api_arg`。最富调用里出现的 kwargs，同名表列仍是 `api_arg`（表全空或值从 `.pt` 来也一样）。查不到图上的 AttrIndex 也不能改成 `script_meta`。

## 值域两源

`domains.profile` 引用 `tables[].profile`（range，不通读 CSV），不要改引擎已写入的 profile。`domains.operator` 只对已是 `api_arg` 的列查图：覆盖列表用 `Dim=<维名>`，组合过滤用 `Name=Value`。声明面与产品覆盖面分开写。`compare` 只能是 `match` / `tighter_profile` / `tighter_operator` / `mismatch`。**`compare=match` 仅当 `operator` 非空。**

## 查图只为 uo_id

role 冻结后再查。必须先做一次无参 `uo-query`（开关维以这次查询为准），不能用索引文件代替。`uo_id` 填短名 / `canonical`，禁止 `TDF::` id 和 `tiling_data_names` 结构名。形状列绑短 tiling 维，禁止 `query` / `key` / `value`。dtype 与 shape 不许共一个 `uo_id`。开关维不是 dtype 列的身份。未从卡片复制 `file:line` 时禁止 around。

## 编码

列值可能是前缀和、打包 flag、枚举别名。每个非平凡列写一句 `encoding`。不要按列名字面理解成物理量。
