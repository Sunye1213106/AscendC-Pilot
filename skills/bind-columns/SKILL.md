---
name: bind-columns
description: 把测试表列映射到算子变量。tg-init 的 columns 切片使用。
---

# 绑定列

只写 `parts/bind.yaml`。本路回答「脚本读到的每一列对应哪个算子变量」。不要写 golden / compare / modes，不要读另一路的 `harness.yaml`。列值域以 `tables[].profile` 为准，不要通读 CSV。

控制面是列。声明 Key 空间仍来自 UO，但 mapping 绑的是脚本仓的列，不是全部合法 TilingKey。

## 输入 / 输出 / 停

读：`repo_scan.yaml`（表头、`tables[].profile`：type / n_unique / min/max / topk）。有仓则打开入口确认脚本怎么读列；无仓则列来自 Host API，不要发明 CSV 列名。

有仓却 mapping 空 → 本切片失败。

完成：mapping 覆盖脚本读到的列，domains 引用 profile。

## 步骤

1. **确认列集合。** 多张 csv/xls 以 scan 的 `tables[]` 为准。用户没点名的表不当本次目标。扫描含 xls/xlsx。
2. **为每一列写 mapping。** 三项都要有：脚本读点（如 `get_case` / `CaseConfig.xxx`）+ UO 标识符 + Host API。缺一项就标缺口，不要用列名相似来猜。
3. **值域引用 profile。** domains 必须引用 `tables[].profile`，禁止通读几千行再手抄枚举。shape 列写成 range；不要把一次抽样的 topk 当成合法全集。
4. **TilingKey 维。** 用查图覆盖列表，不要把列标成 PR 焦点。`dim_*` 用先无参数索引再 `Dim=Name`。查语义优先查图；Grep 只作定位辅助。
5. **对照 CodeMap。** 表允许但算子非法的组合、缺的 INPUT、发明的张量，记进 findings。参数之间有依赖时，记成约束，不要当成两列独立可填。
6. **无仓路径。** 列来自 Host API / InputSemantics。mapping 说明「无脚本读点」，不要假装 `script_repo`。

## 常驻判断

有脚本仓必须有 mapping：每一列同时绑脚本读点与 UO 标识符。这是 init 失败条件，不是「plan 时再补」。

不要把某一个算子的列名写进引擎。不要把列标成审查焦点或精度场景 id。

生成行必须填满该表，现有 runner 才能直接吃——本路负责列与值域，不负责写出 case 行（case 属于 solve）。

`uo_digest` 由 promote 写入。TG 不改 `.uo`。digest 变了必须重跑 `/tg-init`。

缺列 → `test_harness_gap` 说明书（补哪一列、脚本哪里读），不要在草稿里发明列。缺 `generate_inputs` 是 harness 路的事；本路只在 findings 里点名「某列无生成器」即可。

## 看到这样

| 现象 | 判断 |
| --- | --- |
| 有仓、表头很多 | mapping 按 scan 表头走，值域引用 profile |
| 想通读 CSV 确认枚举 | 禁止；用 profile |
| shape 列 | 写成 range |
| `dim_*` / TilingKey 维 | 查图覆盖列表，先无参数索引再 `Dim=Name` |
| 列名像算子变量但脚本没读 | 不要发明 mapping；记 findings |
| 表允许、算子非法 | findings，不要删列 |
| 无仓 | 列来自 Host API，mapping 标明无脚本读点 |
| 有仓 mapping 空 | 本切片失败 |

## 完成勾选

- [ ] 脚本读到的每一列都有脚本读点 + UO 标识符（有仓时）
- [ ] domains 引用 profile，shape 是 range
- [ ] 没有读 harness.yaml，没有把列标成 PR 焦点
- [ ] 依赖列没有当成独立笛卡尔维

## 循环

1. 从 scan 拿表头与 `profile`，不要打开 CSV 正文。
2. 打开入口，确认每一列的脚本读点。脚本没读的列不要硬 mapping。
3. 对每一列查图拿到 UO 标识符。局部名对不上就跟卡片 `canonical`，不要用列名相似凑。
4. shape 写成 range；TilingKey 维写成覆盖列表。依赖记成约束。
5. 有仓且仍有列缺 mapping → 失败，不要交半份。

输出：`mapping[]`（读点 + 标识符 + Host API）与 `domains`（引用 profile）。findings 只记非法组合 / 缺 INPUT / 发明张量。

## 输出形状

```yaml
mapping:
  - column: ...
    script_read: ...
    uo_id: ...
    host_api: ...
domains:
  - column: shape
    from: tables[].profile   # range, 不是 topk 枚举
```

有仓却 `mapping` 空 → 失败。不要发明列名。

## 指针

脚本仓与 profile 纪律：`references/test-script-repo.md`。init 易错点：`references/construction-gotchas.md`。合同（一份 init.yaml、mapping 空则失败）：`references/construction-contract.md`。
