# 绑定列

只写 `parts/bind.yaml`。本路回答「脚本怎么调算子、每个入参来自哪一列、剩下的列是什么」。列值域以 `tables[].profile` 为准。

身份字段由框架写入草稿，不要从 stub 抄进 YAML。

控制面是列。声明 Key 空间仍来自 UO，但 mapping 绑的是脚本仓的列，不是全部合法 TilingKey。

## 输入 / 输出 / 停

读：`repo_scan.yaml`（表头、`tables[].profile`）。有仓则**自己打开入口脚本**。无仓则列来自 Host API，不要发明 CSV 列名。

有仓且 API 入参列 mapping 空 → 本切片失败。`script_meta` 允许无 `uo_id`。`api_arg` / `attr` 缺标识符仍失败。

完成：`call` 已记；API 入参已绑回列；剩余列有 role；domains 做了 profile vs operator 比较。本路交卷即停。

## 步骤

1. **调用接口。** 脚本怎么测：PTA / aclnn 直调 / 混合。记下 `call.kind` + `call.api` + `call.site`（file:line）。打开入口，不要猜。
2. **API 入参 ← CSV。** 从调用点往回追每个传入变量：对应哪一列、`get_case` / `CaseConfig` 哪一读点。这些列 `role: api_arg`，必须有 `uo_id`。
3. **剩余列分类**（不要强行绑 UO）：
   - `attr`：算子属性，可能另一套 Host setter；缺标识符仍失败
   - `feature`：功能开关，可能其它 API / 上下文
   - `script_meta`：名字、来源、是否使能等 runner 自己用的字段，**禁止编造 uo_id**
4. **两边比对。** scan 表头 ∪ API 入参。表有 API 无 → findings / `test_harness_gap`；API 有表无 → 缺口说明书。
5. **值域两源再比较。**
   - `domains.profile`：继续引用 `tables[].profile`（range，不通读 CSV）
   - `domains.operator`：只对 API/ATTR 变量查图。覆盖列表用 `Dim=<维名>`；组合过滤用 `Name=Value`（例如 `IsTnd=1`）。声明面与产品覆盖面分开写，不要和 CSV 抽样混成一个 enum
   - `compare`：`match` / `tighter_profile` / `tighter_operator` / `mismatch`
6. **宏观编码。** 列值可能是编码后的控制面（前缀和、打包 flag、枚举别名），不要按列名字面理解成物理量。每个非平凡列写一句 `encoding`：脚本写入什么、算子读成什么。禁止把某个算子的列名写进本文件。

## 常驻判断

有脚本仓必须把 API 入参列绑上：脚本读点 + UO 标识符。这是 init 失败条件，不是「plan 时再补」。

查图走 `skills/uo-query/SKILL.md`。本路只用标识符卡：覆盖列表写 `Dim=<维名>`，组合过滤写 `Name=Value`。`file:line` 只从上一张卡复制后再 around。

不要把列标成审查焦点或精度场景 id。PR 改了什么留给 `/tg-plan` 的用途草稿。

缺列 → `test_harness_gap` 说明书。生成行属于 solve。

shape 列继续写成 profile range。不要把一次抽样的 topk 当成算子合法全集，也不要把产品覆盖面当成声明面。

## 看到这样

| 现象 | 判断 |
| --- | --- |
| 有仓、表头很多 | 先接口再表头；script_meta 不要假 uo_id |
| 想通读 CSV 确认枚举 | 禁止；用 profile |
| 模板维 vs 产品覆盖 | 声明面 / 产品面分开写 |
| 列值像长度其实是前缀和 | 写 encoding，不要当物理量 |
| 未复制 file:line 就 around | 禁止 |
| 想把某列标成 PR 焦点 | 禁止；用途在 plan_scope |
| 表允许、算子非法 | findings，不要删列 |
| 列名像算子变量但脚本没读 | 不要发明 mapping |

## 完成勾选

- [ ] `call.kind` / `call.api` / `call.site` 来自入口脚本，不是列名猜测
- [ ] API 入参列都有脚本读点与标识符；`script_meta` 没有假标识符
- [ ] 每个非平凡列有一句 `encoding` 或明确「字面量」
- [ ] `domains.profile` 引用 scan profile；`domains.operator` 分开写声明面与产品面
- [ ] `compare` 是四者之一；未复制 file:line 时没有 around
- [ ] 没有把任何列标成 PR 焦点

## 循环

查不清某列时：缩短标识符再查一次，或把缺口写入 findings。不要为了「看起来绑完」去编 `uo_id`。

无仓时本路仍然要交：列来自 Host API，mapping 写明没有脚本读点。
