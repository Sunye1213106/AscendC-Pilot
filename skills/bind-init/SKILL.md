---
name: bind-init
description: tg-init 在 repo_scan 之后分两路：一路写怎么跑，一路写列怎么绑。执行 bind_init 父 Action 时使用。
---

# 分两路绑定

本步自己不写 YAML。`repo_scan` 之后分两路：一路写测试怎么跑，一路写表列怎么绑到算子变量。正式产物只有一份 `tg/init.yaml`，主控审过两份草稿后由 `bind_promote` 写入。本文件不代替那两路各自的 Skill。

无测试仓也两路都跑。`kind=default_input` 不是失败，是「列来自 Host API、没有脚本口径」。有仓却 mapping 空才是失败。

## 为什么拆成两路

引擎能扫表头和 argparse，但不能替你判断「这个 flag 算精度还是造数」「这一列是 shape 还是 Key 维」。这两类判断互读会串口径：harness 用列名猜 mapping，columns 用精度 mode 反推列。所以两路隔离写草稿，父步只保证到齐与边界，主控再通读裁判。

不要因为「真正的活在切片里」就把本文件留成三句话。切片装载前，父窗口必须知道各交什么、什么算混轴、无仓怎么叙事。

## 输入 / 输出 / 停

读：`repo_scan.yaml`（仓根、入口、表头、`tables[].profile`）。写：两路切片各自的草稿；本步不写正式 `init.yaml`。

两路：

- `bind-harness` → `parts/harness.yaml`（golden / compare / 精度性能入口 / call.kind / generate_inputs / findings）
- `bind-columns` → `parts/bind.yaml`（调用接口 + 列 mapping + 双源 domains）

完成：两份草稿到齐，等待主控裁判。ACK 只认到齐数量，不替裁判读内容。

## 步骤

1. **确认 scan 口径。** `kind=script_repo` 才把脚本仓当 runner；`kind=default_input` 不要假装已有仓、不要把算子仓 `tests/` 当 harness。用户改过路径则以最新 scan 为准，不要沿用旧表。
2. **两路同时交卷，互不抄作业。** harness 不读 bind.yaml，columns 不读 harness.yaml。列值域以 `tables[].profile` 为准，禁止通读 CSV。身份字段由框架写入。
3. **有仓则 API 入参 mapping 必须有。** 这些列同时绑：脚本读点 + UO 标识符。`script_meta` 不要假标识符。有仓却 API 列空 → 本轮失败。
4. **精度/性能口径来自脚本事实。** argparse 的精度 mode 与性能 mode 分开写。默认值若是性能 mode，不得把默认当精度。`--golden-only`（不调 pta / 无需 NPU）是造数，不是精度。
5. **裁判在主控。** 本步不 PASS、不 REWORK。切片写完即停。

## 常驻判断

控制面是脚本仓的列，不是全部合法 TilingKey。不要把某一个算子的列名写进引擎或本文件。

参数有依赖时禁止独立笛卡尔（reduce 轴必须落在 rank 内；shape 与 `*TemplateNum` / `dim_*` 同理）。生成器做不到 → `test_harness_gap`，由后续改**测试脚本仓**，不要在本步改算子仓。

预期报错 / Disable 行不上精度 oracle，也不要写成 Host HIT 失败。`uo_digest` 由 promote 写入；digest 变了必须重跑 `/tg-init`。不要再写 inventory / audit / fingerprint / contract YAML。

无仓时：harness 写明缺口（没有 compare / 没有精度入口），columns 从 Host API 列变量，不要发明 CSV 列。

## 两路各交什么

harness 必须能回答：现有 runner 怎么选 case、golden 怎么比、精度/性能分别怎么跑、现在造得出什么 / 造不出什么。

columns 必须能回答：脚本怎么调算子、API 入参对应哪一列、剩余列是 attr/feature/script_meta；shape 列是 range；TilingKey 维用查图覆盖列表。不要把列标成 PR 焦点。

冲突（列名对不上入口、精度口径与 argparse 矛盾、无仓却写成 script_repo）留给 `bind-review`，本步不合并。

## 看到这样

| 现象 | 判断 |
| --- | --- |
| `kind=script_repo` | 两路都按脚本仓写；bind 必须有 mapping |
| `kind=default_input` | 两路都跑；harness 写缺口，columns 用 Host API |
| 用户改了测试仓路径 | 以最新 scan 为准，旧草稿作废 |
| 某一路想读另一路 YAML | 禁止；冲突留给裁判 |
| 想写正式 `init.yaml` | 禁止；promote 是引擎的事 |
| 想把列名写进「通用规则」 | 禁止 |

## 完成勾选

- [ ] 两份草稿路径都有：`parts/harness.yaml`、`parts/bind.yaml`
- [ ] 有仓则 bind 覆盖脚本读到的列；无仓则没有假装 script_repo
- [ ] 本步没有 PASS / REWORK，没有合并两路

父步只保证到齐与边界。质量由 `bind-review` 判。

## 循环

本步几乎没有「再想一轮」：两路交卷，停。

1. 读 `repo_scan.yaml` 的 `kind` 与仓根。路径被用户改过则以最新 scan 为准。
2. 确认两路边界写进各自 prompt：harness 不写 mapping，columns 不写 modes。
3. 等两份草稿到齐。缺一份不要让另一路补写。
4. 把两份交给主控裁判。本步不读内容做 PASS。

为什么拆两路：入口/精度口径与列 mapping 是两类事实，混在一份 YAML 里会互相迁就（没仓却编 argparse，有仓却空 mapping）。切片隔离才能让裁判看到真实缺口。

## 输出形状

本步不写 YAML 正文。完成态是两份草稿到齐：`parts/harness.yaml` 与 `parts/bind.yaml`。缺一份不算完成。

## 指针

两路各自只读自己的 Skill：`skills/bind-harness/SKILL.md`、`skills/bind-columns/SKILL.md`。
