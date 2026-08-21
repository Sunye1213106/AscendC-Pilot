# 列绑定边角

**何时加载**：调用接口对不上表头、列值是编码控制面、或查图形态写错时。

## 先接口再表头

打开入口记下 `call.kind` + `call.api` + `call.site`。API 入参列 `role: api_arg`，必须有 `uo_id`。`script_meta`（名字、来源、是否使能）禁止编造 `uo_id`。

## 值域两源

`domains.profile` 引用 `tables[].profile`（range，不通读 CSV）。`domains.operator` 只对 API/ATTR 查图：覆盖列表用 `Dim=<维名>`，组合过滤用 `Name=Value`。声明面与产品覆盖面分开写。`compare` 只能是 `match` / `tighter_profile` / `tighter_operator` / `mismatch`。

## 查图

未从卡片复制 `file:line` 时禁止 around。不要把 `Dim=` 当成 `Name=Value` 的前缀胡写。

## 编码

列值可能是前缀和、打包 flag、枚举别名。每个非平凡列写一句 `encoding`。不要按列名字面理解成物理量。
