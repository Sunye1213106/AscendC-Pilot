# 审绑定草稿

通读 `parts/harness.yaml` 与 `parts/bind.yaml`。不要写文件。本步只判过不过：放行后引擎才 `bind_promote` 合并正式 `init.yaml`。两份没到齐不能判。

**禁止做 schema / YAML 审查。** 非法组合（`relation=candidate`、`confirmed` 却空 `uo.id`、非 active 却 `confirmed`）由引擎 validator 拒绝；`PASS` 时引擎会再跑同一 validator，失败是 `BIND_PART_INVALID`，不是「schema 看起来 OK 所以过」。本窗只抽查已 `confirmed` 行的 provenance：这条 `uo.id` 是否真是 CSV→API→Host→implementation state 闭合链上的实现状态。

**`inspect yaml` 过了只说明能合并。** 多数 active kwargs 列 `partial` + 空 `uo.id` → `REWORK bind`。不要因为能 parse 就 PASS。

不要自己补列、不要改口径。

## 输入 / 输出 / 停

读：两份草稿 + `repo_scan.yaml`。写：无。下一发必须是 `intent=PASS`，或 `REWORK harness` / `REWORK bind` / `REWORK harness,bind`，并写原因。

scan 的 `kind` 与草稿叙事必须一致：无仓时有没有假装 `script_repo`；点了仓却扫空则不应放行。

## Provenance audit（仅 confirmed 行）

对每条 `confidence: confirmed` 的列抽查，不要只看格子填了。任一项失败就 REWORK。

1. **`uo.id` 指对了闭合链上的符号。** CSV → runtime → Host/Tiling 整条可追。只碰到相似 UO 符号应是 `uo.candidate` + `unresolved`，不得标 `confirmed`。开关维 / `*TemplateNum` / 张量操作数不是 dtype / shape / layout 列的身份。尺寸列应是 tiling 字段短名，不要绑派生 kwargs。
2. **`relation` 描述 CSV→runtime API。** `direct` = identity / 平凡转换；`derived` = 非 identity 脚本变换；张量用 `tensor_shape` / `tensor_dtype` / `presence`。分不清应空 relation + `unresolved`。layout 列到开关维的投影写在 `domains.projection`。
3. **`call_args` 的 `sources[]` 对得上这条 confirmed 列。** 张量多源必须分条。两列不得共用一个 `uo.id`。
4. **domains 拆开。** `applicability` / `value` / `projection` 分开写。`domains.profile` 引用 scan profile。`operator` 空却 `compare=match` → `REWORK bind`。
5. **plan 消费面。** 只有上述 confirmed 行可当确定性 Target/Dimension control。kwargs 的 source 列若大量 `partial` 空 `uo.id`，plan 会丢控制维 → `REWORK bind`。本步不写 plan。

## 清单（其余，叙事不是 schema）

6. **两份自洽。** harness 引用的表 / 入口 / `--case` 与 bind 的列集合对得上。
7. **没有发明列。** bind 列名必须来自 scan 表头或（无仓时）Host API。
8. **精度口径来自脚本。** `modes.precision` / `modes.perf` 与 argparse 一致。`--golden-only` 写成精度 → `REWORK harness`。
9. **无仓叙事。** `kind=default_input` 时 harness 应写缺口而不是假入口。
10. **generate_inputs 缺口诚实。** runner 造不出的标缺口。
11. **运行上下文。** 确定性 / 设备列若 host 会读，标成 metadata → `REWORK bind`。

## 常驻判断

正式产物只有 `init.yaml`。草稿里若又写出 inventory / audit / fingerprint，退回重写，不要 promote。

精度/性能 oracle 是 harness mode，不是 Host TilingKey HIT，也不是 plan `evidence.field`。

冲突时写清改哪一路：列错了改 bind；怎么跑/怎么比错了改 harness；两边叙事打架就两路都 REWORK。

放行后才 plan/solve。本步不写 `init.yaml`。

## 看到这样

| 现象 | 下一发 |
| --- | --- |
| confirmed 行的 `uo.id` 不是闭合链上的实现状态 | `REWORK bind` |
| 两列共 `uo.id` / 开关维或 TemplateNum 当 dtype/shape 身份 / 尺寸列绑操作数名 / kwargs 列大量空 `uo.id` | `REWORK bind` |
| 确定性列标 metadata | `REWORK bind` |
| 精度口径与 argparse 不符 / 编了阈值 / golden-only 当精度 | `REWORK harness` |
| 无仓却写成 script_repo，或两边叙事打架 | `REWORK harness,bind` |
| 抽查过、叙事自洽 | `PASS` |

原因写一句人能改的话：改哪一字段、为什么。不要做 YAML schema 点评。

## 完成勾选

- [ ] 两份都读完，不是只看文件在不在
- [ ] 只抽查了 confirmed 行的 provenance，没有把 inspect ok 当 PASS
- [ ] 精度/性能没有被写成 Host HIT 或 evidence.field
- [ ] 下一发是 PASS 或带原因的 REWORK，没有自己补 YAML

## 输出形状

```text
intent=PASS
```

或：

```text
intent=REWORK bind
原因：列 Foo 的 uo.id 不是闭合链上的实现状态
```
