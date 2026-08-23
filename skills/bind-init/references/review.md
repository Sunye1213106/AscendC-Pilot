# 审绑定草稿

通读 `parts/harness.yaml` 与 `parts/bind.yaml`。不要写文件。本步只判过不过：放行后引擎才 `bind_promote` 合并正式 `init.yaml`。两份没到齐不能判。

只判草稿自洽与否。不要自己补列、不要改口径。旧扁平 `role` + `uo_id` / 单 `source_column` 不是绑定，见即 `REWORK bind`。

## 输入 / 输出 / 停

读：两份草稿 + `repo_scan.yaml`。写：无。下一发必须是 `intent=PASS`，或 `REWORK harness` / `REWORK bind` / `REWORK harness,bind`，并写原因。

scan 的 `kind` 与草稿叙事必须一致：无仓时有没有假装 `script_repo`；点了仓却扫空则不应放行。

## Provenance audit

逐列核对，不要只看「格子填了」。任一项失败就 REWORK。

1. **`control.status` 对得上 corpus / runner。** 表 100% 空且 runner 从别列重算 → 空列必须是 `shadowed`，不得 `active`。API 语义对但当前 corpus 全空 → `unwired`。不进调用的 harness 标志 → `metadata`。把这些写成 active 控制 → `REWORK bind`。
2. **`uo.id` 仅当链路闭合。** CSV → runtime → Host/Tiling 整条可追才允许 `uo.id` + `confidence: confirmed`。只碰到相似 UO 符号 → `uo.candidate` + `unresolved`。**禁止把 `candidate` 升格成 `uo.id`。**
3. **`relation` 不要压成一种。** 直接传参 `direct`；脚本变换 `derived`；张量构造 `tensor_shape` / `tensor_dtype`。`Input_Layout → IsTnd` 写在 `domains.projection`，不是 mapping.relation。
4. **`call_args` 用 `sources[]`。** 出现 `source_column` → `REWORK bind`。张量多源必须分条，不要挑一列当整个张量的身份。
5. **domains 拆开。** `applicability` / `value` / `projection` 分开写。`domains.profile` 引用 scan profile，不要改引擎写入的 profile。`operator` 空却 `compare=match` → `REWORK bind`。
6. **plan 消费面。** 未 `confirmed` + `active` + 非空 `uo.id` 的列不得当确定性 classifier。本步不写 plan，但草稿若把 unresolved / candidate 写成已绑定控制 → `REWORK bind`。后续 plan 会把未确认轴标 `untestable + needs_binding`。

## 清单（其余）

7. **两份自洽。** harness 引用的表 / 入口 / `--case` 与 bind 的列集合对得上。
8. **没有发明列。** bind 列名必须来自 scan 表头或（无仓时）Host API。
9. **精度口径来自脚本。** `modes.precision` / `modes.perf` 与 argparse 一致。`--golden-only` 写成精度 → `REWORK harness`。
10. **两路 `call.kind` 同一世界。** 非法 kind（不是 `pta` / `aclnn` / `mixed`）→ `REWORK bind`。
11. **无仓叙事。** `kind=default_input` 时 harness 应写缺口而不是假入口。
12. **generate_inputs 缺口诚实。** runner 造不出的标缺口。encoding 非平凡列应说明脚本写入什么、算子读成什么。

## 常驻判断

正式产物只有 `init.yaml`。草稿里若又写出 inventory / audit / fingerprint，退回重写，不要 promote。

精度/性能 oracle 是 harness mode，不是 Host TilingKey HIT。

冲突时写清改哪一路：列错了改 bind；怎么跑/怎么比错了改 harness；两边叙事打架就两路都 REWORK。

放行后才 plan/solve。`confirmed` 由 `bind_promote` 写在 `init.yaml` 上，本步不写。

## 看到这样

| 现象 | 下一发 |
| --- | --- |
| 旧 `role`/`uo_id`/`source_column`；`control.status` 与空列/派生不符；`candidate` 写成 `uo.id` | `REWORK bind` |
| 精度口径与 argparse 不符 / 编了阈值 / golden-only 当精度 | `REWORK harness` |
| 无仓却写成 script_repo，或两边叙事打架 | `REWORK harness,bind` |
| 清单全过 | `PASS` |

原因写一句人能改的话：改哪一字段、为什么。不要只说「不自洽」。

## 完成勾选

- [ ] 两份都读完，不是只看文件在不在
- [ ] 逐列做过 provenance：status / relation / confidence / `uo.id` vs `candidate`
- [ ] 精度/性能没有被写成 Host HIT
- [ ] 下一发是 PASS 或带原因的 REWORK，没有自己补 YAML

## 输出形状

```text
intent=PASS
```

或：

```text
intent=REWORK bind
原因：列 Foo 的 uo.candidate 被写成了 uo.id，链路未闭合
```
