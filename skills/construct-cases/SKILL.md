---
name: construct-cases
description: 按已批准计划定向构造用例行。执行 /tg-solve 的 construct_cases 时使用。
---

# 构造用例

按已批准 `plan.md` 构造脚本能吃的用例行。正式表由 `construct_promote` 写出。本步是定向构造，不是搜索全部合法 Key，也不是签发闭合。

列是控制面。草稿行必须填满 `init.yaml` 的列，现有 runner 才能用 `--case` 直接吃。不要发明列。

## 输入 / 输出 / 停

读：已批准 `plan.md` 的 YAML 义务、`init.yaml` 列与 defaults、本轮已有观测（若有）。没有批准计划 → 停。

写：本 Action 草稿行。不要写 `tg/closure/**` 证书森林。不要改 `.uo`。

完成：草稿行覆盖批准义务，没有发明列。需要改构造就保持 open，不要假装闭合。

## 步骤

1. **按义务定向。** 只构造计划里的控制列；其余用 defaults。不要把 L3 特殊值铺进每一组 L0 shape。
2. **填满表。** 每一行覆盖 init 声明的列。缺值用 defaults 或 recipe 复算（轴∈rank、`dim_*` 派生），不要留空让 runner 崩。
3. **精度 / 性能旋钮。** 碰到 `P-*` 读 `skills/precision-testing/SKILL.md`；碰到 `F-*` 读 `skills/performance-testing/SKILL.md`。clean（normal / zero / near_zero / all_ones）是必过门；stress 不当唯一硬门。性能预算 3–8 条，禁止枚举全部 legal key。任一性能场景带上 `F-SHAPE-TYPICAL`。
4. **硬命题。** 义务需要「源码不可达 / P⇒Q」时读 `skills/source-proof/SKILL.md`。不要把 Host Replay reject 写成不可达证明。
5. **观测怎么用。** Host Replay 无 NPU，只看 tiling key / TD / OP_CHECK / 分支。HIT 可增长 dispatch/key；REWRITE / REFUSE 是观测，供引理；CRASH / NOT_RUN 是环境，禁止当负样本，也不是 golden 失败。`Replay reject ≠ E`。
6. **精度 oracle 是 harness mode。** Host 命中 TilingKey 关不了 `P-*`。预期报错 / Disable 行不上 NPU，也不要写成精度失败。

## 常驻判断

正式产物是稍后的 `worklog.md` + cases 表。本步只交能跑的行。worklog 文首 `open:` 由 analyze-round 维护；本步不要签发。

引理 span 来自查图。Grep 只作定位辅助。禁止把搜索失败或裸 Host reject 升级为 exclusion。

`uo_digest` 变了必须重跑 `/tg-init`，不要用过期列构造。缺列或缺生成器应在 plan 阶段已变成 `test_harness_gap`；本步撞上 → 停并写缺口，不要发明值。

## 看到这样

| 现象 | 判断 |
| --- | --- |
| 计划未批准 | 停 |
| 义务要改某几列 | 只动这些列，其余 defaults |
| `P-*` | 读精度原语；clean 是必过门 |
| `F-*` | 读性能原语；带 `F-SHAPE-TYPICAL` |
| 需要「不可达」 | 读源码证明；Replay reject 不够 |
| HIT | 可增长 dispatch/key |
| REWRITE / REFUSE | 观测，给引理 |
| CRASH / NOT_RUN | 环境，禁止当 E |
| 行填不满 init 列 | 用 defaults/recipe，不要留空 |
| 缺列 / 缺生成器 | 停并写缺口，不要发明值 |

## 完成勾选

- [ ] 草稿行覆盖批准义务，列与 init 一致
- [ ] 没有发明列，没有把 L3 铺进每一组 L0
- [ ] 精度/性能 oracle 指向 harness，不是 Host HIT
- [ ] 需要改构造时保持 open，没有签发闭合

## 循环

1. 取出下一条未覆盖的批准义务。不要另开义务。
2. 填控制列；其余 defaults / recipe。检查行能被 `--case` 吃。
3. 碰到 `P-*` / `F-*` / 硬命题，打开对应原语，不要在本步发明口径。
4. 已有 Replay 则按 HIT / REWRITE / REFUSE / CRASH 记账，不要把 reject 写成 E。
5. 义务覆盖完就停。签发是后一步。

一行 = 脚本能跑的一条。缺值不要空着碰运气。`uo_digest` 对不上 init 时停，去重跑 `/tg-init`。

## 输出形状

一行填满 init 声明的列。控制列来自义务，其余 defaults/recipe。不要多列、不要缺列。需要改构造时在回复里写 open，不要签发。

## 反模式

- 发明列或留空让 runner 崩
- 把 L3 特殊值铺进每一组 L0
- Host reject 写成 E 或不可达
- 用 Host HIT 关 `P-*` / `F-*`
- CRASH 当负样本
- 未批准计划就开始构造

## 指针

定向构造：`references/targeted-construct.md`。精度义务：`skills/precision-testing/SKILL.md`。性能义务：`skills/performance-testing/SKILL.md`。硬命题：`skills/source-proof/SKILL.md`。
