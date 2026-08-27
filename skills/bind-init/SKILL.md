---
name: bind-init
description: 写出或审 harness / columns 绑定草稿。repo 已扫完、要填草稿或通读两路判 PASS/REWORK 时使用。不要用于规划覆盖、逐格求解、或已有正式 init.yaml 之后的步骤。
---

# 分路绑定

Primary 做两件事：派两轴写出草稿，通读后 PASS/REWORK。禁止混轴：harness 不读 bind.yaml，columns 不读 harness.yaml。代码访问遵守 `code-access`。本 Skill 不另定访问策略。

Harness 证明 CSV→API construct；UO 证明 semantic identity。`confidence` 只表示前者；后者未闭合时 `uo.id` 可空。

子代理只装本轴 HOW：

- 怎么跑：`references/harness.md`
- 列怎么绑：`references/columns.md`

引擎合并 `harness.yaml` 与全部 `bindN.yaml` → `bind.yaml`。`inspect yaml` 过了只说明能合并。正式产物只有将来的 `init.yaml`。

## 审草稿

通读 `parts/harness.yaml` 与 `parts/bind.yaml`。不要写文件。不要打开 `references/harness.md` / `references/columns.md`。放行后引擎才 `bind_promote`。两份没到齐不能判。

**禁止做 schema / YAML 审查。** 非法组合由引擎 validator 拒绝；`PASS` 时引擎会再跑同一 validator，失败是 `BIND_PART_INVALID`。本窗只抽查 validator 不能证明的 provenance。

下一发必须是 `intent=PASS`，或 `REWORK harness` / `REWORK bind` / `REWORK harness,bind`，并写原因。不要自己补列、不要改口径。不要因为能 parse 就 PASS。confirmed 却空 `uo.id` 不是 REWORK 理由。

## 出处抽查（仅 confirmed 行）

对每条 `confidence: confirmed` 抽查。任一项失败就 REWORK。

1. **身份真伪。** 有 `uo.id` 时必须是 query 命中的 canonical / 短名，且落在 CSV→API→Host→implementation 闭合链上。禁止把 `call_args.name` / `runtime_expr` 当身份来源。短名碰巧与 arg 名相同、但能对上 identifier 命中，不算抄名。空 id + `candidate` 且有 `runtime.target` / `evidence` 是合法 construct。
2. **construct 证据在不在现场。** confirmed 行要能指到调用点窗口，不是格子填了就算。kwargs 的 source 列若大量 construct 未闭合（`unresolved` / 无 evidence）→ `REWORK bind`。本步不写 plan。
3. **两份叙事。** harness 引用的表 / 入口 / case 选择与 bind 的列集合对得上。bind 列名必须来自 scan 表头或（无仓时）Host API。scan 的 `kind` 与草稿一致：无仓时没有假装 `script_repo`；点了仓却扫空则不放行。

## 看到这样

| 现象 | 下一发 |
| --- | --- |
| confirmed 行的 `uo.id` 只是抄 `call_args.name`（对不上 query 命中），或绑成邻居维 / 派生 kwargs / 开关维冒充 dtype/shape | `REWORK bind` |
| confirmed 却无 harness 证据（空 evidence 且无 runtime.target / sources） | `REWORK bind` |
| 两列共非空 `uo.id` / 尺寸列绑操作数名 / shadowed 列进 `sources[]` / 大量 active kwargs construct 未闭合 | `REWORK bind` |
| 确定性列标 metadata | `REWORK bind` |
| 精度口径与 argparse 不符 / 编了阈值 / golden-only 当精度 | `REWORK harness` |
| 无仓却写成 script_repo，或两边叙事打架 | `REWORK harness,bind` |
| 抽查过、叙事自洽 | `PASS` |

原因写一句人能改的话：改哪一字段、为什么。不要做 YAML schema 点评。精度/性能 oracle 是 harness mode，不是 Host TilingKey HIT，也不是 plan `evidence.field`。草稿里若又写出 inventory / audit / fingerprint，退回重写，不要 promote。

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
原因：列 Foo 的 uo.id 是抄的 call_args.name，不是 query 命中
```
