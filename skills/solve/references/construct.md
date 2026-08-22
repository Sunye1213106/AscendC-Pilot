# 构造用例

按已批准 `plan.md` 的 `variables[].direction` 写出脚本能吃的行。第一轮默认 **L0+L1**。正式表由 `construct_promote` 写出。

造行是为了让 Host 跑完能判 `TARGET_HIT`。尺子是每条变量的 `evidence`：丢掉尺子去盲搜，下一轮还是 miss。direction 不准也可以——Host 在编译运行时才算出 TilingKey / s2Inner，第一轮只要走到大概那条分支。

列是控制面。每一行填满 `init.yaml` 的列，runner 才能用 `--case` 直接吃。

## 输入 / 输出 / 停

读：已批准 `plan.md`（`variables` / `direction` / `evidence` / `ladder` / 可选 `oracle`）、`init.yaml` 列与 defaults、上轮 worklog（若有）。计划未批准 → 停。

写：本 Action 草稿行。

完成：L0 每个变量至少一行；变量 ≥2 时 L1 每对一行；每行填满 init 列；`direction` 点名的列已改。

## 步骤

1. **读 ladder。** 未指定则只造 L0+L1。用户点名全覆盖 / 异常才升 L2 或 L3。L3 特殊值单列，不铺进每一组 L0。
2. **按 direction 填列。** `note` 是第一轮往哪边走（哪列、哪边分支）。Host 派生字段（s2Inner、usedCoreNum、TilingKey）先造候选，跑 Replay 再看——direction 不必一次算对。
3. **填满其余列。** defaults 或 recipe（轴∈rank、`dim_*`）。空格会让 `--case` 崩。
4. **已有 TARGET_MISS。** 读上轮 worklog 的「改哪几列」，对照**同一条** evidence 再填。换尺子等于没迭代。
5. **TARGET_HIT 之后。** `oracle` 非空才读本窗邻域表加精度/性能行。怎么跑以 `init.yaml` 为准。clean（normal / zero / near_zero / all_ones）是精度必过门。
6. **不可达命题。** `evidence.kind=source_proof` 时读 `skills/source-proof/SKILL.md`。`REFUSE` 是观测，不够当不可达。

## 常驻判断

本步只交能跑的行。`open:` 由 analyze 维护；签发是后一步。

未指定时第一轮只造 L0+L1：变量已经正交，每维一次加成交足以开工；全量笛卡尔会把预算花在 evidence 判不了的组合上。

`HIT / REWRITE / REFUSE` 是 Host tiling 裁决。`TARGET_HIT` 看 evidence 是否对上。二者分开记账，除非 evidence 就是那条 TilingKey / 字段。

`uo_digest` 对不上 init → 停，去 `/tg-init`。缺列或缺生成器 → 写 `test_harness_gap`，用现有列凑值过不了闸。

## 看到这样

| 现象 | 判断 |
| --- | --- |
| 计划未批准 | 停 |
| 未指定档 | 造 L0+L1 |
| 用户点名异常 / 全覆盖 | 再造 L3 / L2 |
| direction 只给了大致边 | 先填那一列，Replay 后迭代 |
| 上轮 TARGET_MISS | 按 worklog 改列，同一条 evidence |
| `oracle` 非空且已 TARGET_HIT | 读邻域表加行 |
| 行缺 init 列 | defaults / recipe 补齐 |
| 缺列 / 缺生成器 | 停并写缺口 |

## 完成勾选

- [ ] L0（及该造的 L1）每条组合都有一行
- [ ] 每行填满 init 列；direction 点名的列已动
- [ ] 迭代时仍对着同一条 evidence
- [ ] `oracle` 行只加在 TARGET_HIT 之后

## 循环

1. 取出下一条未造的 L0 / L1 组合（或 worklog 指定的 MISS 变量）。
2. 按 direction 填控制列，其余 defaults。
3. 确认 `--case` 能吃。
4. 本轮档造完就停。签发是后一步。

一行 = 脚本能跑的一条。缺值用 defaults，不留空碰运气。

## 输出形状

草稿 yaml：`columns` 与 `rows`。控制列来自 direction，其余 defaults/recipe。需要改构造时在回复里点名变量 id，等 analyze 写入 `open:`。

## 反模式

- 丢掉 evidence 盲搜合法 Key
- 未指定就造 L2/L3 或全量 TilingKey
- 用 Host `HIT` 当作精度 / 性能已过
- `CRASH` / `NOT_RUN` 当负样本

## 指针

定向规则与命中后邻域取值由本窗装载。硬命题：`skills/source-proof/SKILL.md`。
