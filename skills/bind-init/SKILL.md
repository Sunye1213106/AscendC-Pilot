---
name: bind-init
description: 写出 harness 或 columns 绑定草稿。repo 已扫完、要填草稿时使用。不要用于通读两路裁判、规划覆盖、或已有正式 init.yaml 之后的步骤。
---

# 分路绑定

本步只生产语义草稿。harness 与 columns 是两条独立写面，禁止混轴。代码访问遵守 `code-access`。本 Skill 不另定访问策略，也不做通读裁判。

Harness 证明 CSV→API construct；UO 证明 semantic identity。`confidence` 只表示前者；后者未闭合时 `uo.id` 可空。

## 输入 / 输出 / 停

读：`repo_scan` 与引擎已写出的本轴草稿 stub。
写：本轴语义格。不要写正式 `init.yaml`，不要读对轴产物。

- harness 不读 bind.yaml
- columns 不读 harness.yaml

`inspect yaml` 过了只说明本轴能过机器合同。正式产物只有将来的 `init.yaml`。

## 步骤

1. **认本轴交付物。** harness 回答现有 runner 怎么跑、怎么比、精度/性能入口在哪。columns 给本路列写 `control` / `relation` / construct 证据，并只给 active 列解析 identity。
2. **需要算子语义身份时走 uo-query 合同。** 只采用返回的 canonical / 短名。不要复制查询 CLI，不要自己规划无参还是 identifier。
3. **Edit 本轴草稿。** `inspect yaml --rel <本轴 yaml>` 返回 ok 立刻停。失败就改到过。不要补对轴的格子。

## 常驻判断

construct ≠ identity。1:1 `sources[]` 只证明 CSV→API。空 `uo.id` + `candidate` 且有 harness 证据仍是合法 construct。禁止把 `call_args.name` / `runtime_expr` 抄进 `uo.id`。

两列不许共非空 `uo.id`。开关维不是 dtype / shape / layout 的身份。`metadata` 只有 Enable / 用例名 / 是否跑这行。

## 看到这样

| 现象 | 判断 |
| --- | --- |
| confirmed 空 evidence | 未完成，补调用点窗口 |
| 把 `call_args.name` 抄进 `uo.id` | 禁止；空 id + `candidate` |
| 尺寸列绑操作数名 / 派生 kwargs | 禁止 |
| 读了对轴产物 | 停，退回本轴 |
| inspect 未 ok | 未完成 |

## 完成勾选

- [ ] 只写了本轴语义格，没有读对轴产物
- [ ] construct 与 identity 分开；空 `uo.id` 没有把 construct 降成 unresolved
- [ ] `inspect yaml` 返回 ok

## 指针

- 怎么跑：`references/harness.md`
- 列怎么绑：`references/columns.md`
