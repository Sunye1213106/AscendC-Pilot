# 审绑定草稿

通读 `parts/harness.yaml` 与 `parts/bind.yaml`。不要写文件。本步只判过不过：放行后引擎才 `bind_promote` 合并正式 `init.yaml`。两份没到齐不能判。

只判草稿自洽与否。不要自己补列、不要改口径。

## 输入 / 输出 / 停

读：两份草稿 + `repo_scan.yaml`。写：无。下一发必须是 `intent=PASS`，或 `REWORK harness` / `REWORK bind` / `REWORK harness,bind`，并写原因。

scan 的 `kind` 与草稿叙事必须一致：无仓时有没有假装 `script_repo`；点了仓却扫空则不应放行。

## 清单

逐项过。任一项失败就 REWORK，不要「先用着」。

1. **两份自洽。** harness 引用的表 / 入口 / `--case` 与 bind 的列集合对得上。一边有精度 mode、另一边没有对应列，要写原因。
2. **有仓则 API 入参 mapping 非空。** `api_arg` / `feature` 必须有脚本读点与 UO 标识符。`script_meta` 不得假造标识符。不要把传进调用的列标成 `attr`。有仓却 API 列空 → `REWORK bind`。
3. **没有发明列。** bind 列名必须来自 scan 表头或（无仓时）Host API。不要把计划意图里的场景 id 当成列。
4. **shape 列是 range，且做了双源比较。** `domains.profile` 引用 `tables[].profile`；`domains.operator` 分开写声明面与产品覆盖面。本步判「有没有做比较、叙事是否同一世界」。把一次抽样当成枚举全集 → `REWORK bind`。
5. **精度口径来自脚本。** `modes.precision` / `modes.perf` 与 argparse 一致。默认性能 mode 被写成精度 → `REWORK harness`。`--golden-only` 写成精度 → `REWORK harness`。argparse 没有的 atol/rtol 被编出来 → `REWORK harness`。
6. **两路 `call.kind` 同一世界。** 两边对 PTA / aclnn / mixed 的说法打架 → 两路 REWORK。任一路写出非法 kind（不是 `pta` / `aclnn` / `mixed`）→ `REWORK bind`。
7. **无仓叙事。** `kind=default_input` 时 harness 应写缺口而不是假入口；bind 不应假装有脚本读点。
8. **没有把列标成 PR 焦点。** 列是控制面，不是审查发现。
9. **依赖未拆成独立笛卡尔。** reduce 轴与 rank、shape 与派生维若被当成两列独立可填 → `REWORK bind` 或 harness（看缺口写在哪）。
10. **generate_inputs 缺口诚实。** 空 tensor / inf / 对齐+1 / 非法 range 等 runner 造不出的，应标缺口，不要假装已覆盖。
11. **预期报错行。** Disable / 预期错误没有被当成精度 golden。
12. **encoding。** 非平凡列应说明脚本写入什么、算子读成什么；按列名字面当物理量 → `REWORK bind`。

## 常驻判断

正式产物只有 `init.yaml`。草稿里若又写出 inventory / audit / fingerprint，退回重写，不要 promote。

精度/性能 oracle 是 harness mode，不是 Host TilingKey HIT。Host 口径写进 harness 当精度 → REWORK。

冲突时写清改哪一路：列错了改 bind；怎么跑/怎么比错了改 harness；两边叙事打架就两路都 REWORK。不要让一轮切片去改另一路的文件。

放行后才 plan/solve。`confirmed` 由 `bind_promote` 写在 `init.yaml` 上，本步不写。

## 看到这样

| 现象 | 下一发 |
| --- | --- |
| 列名对不上入口 / mapping 空 / 发明列 / shape 不是 range / 非法 call.kind | `REWORK bind` |
| 精度口径与 argparse 不符 / 编了阈值 / golden-only 当精度 | `REWORK harness` |
| 无仓却写成 script_repo，或两边叙事打架 | `REWORK harness,bind` |
| 清单全过 | `PASS` |

原因写一句人能改的话：改哪一字段、为什么。不要只说「不自洽」。

## 完成勾选

- [ ] 两份都读完，不是只看文件在不在
- [ ] 有仓检查过 mapping 非空；无仓检查过没有假装有仓
- [ ] 精度/性能没有被写成 Host HIT
- [ ] 下一发是 PASS 或带原因的 REWORK，没有自己补 YAML

## 循环

通读，不要抽样。先看 scan.kind 与两份叙事是否同一世界，再过清单十二条。

改哪一路按「事实在哪」：脚本怎么跑在 harness，列叫什么在 bind。两边都在撒谎就两路 REWORK。

下一发只有三种形态：`PASS` / `REWORK harness` / `REWORK bind`（可组合）。原因指向字段，例如「`modes.precision` 抄了默认性能 flag」或「列 `xxx` 无脚本读点」。不要写「再完善一下」。

## 输出形状

```text
intent=PASS
```

或：

```text
intent=REWORK bind
原因：有仓但列 Foo 没有脚本读点
```
